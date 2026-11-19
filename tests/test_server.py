"""End to end: the real server, started as its own process, on 127.0.0.1:8970 and 8971."""

import asyncio
import os
import re
import socket
import subprocess
import sys
import time

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP = "http://127.0.0.1:8970"
LOOK = "http://127.0.0.1:8971"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    home = tmp_path_factory.mktemp("ember-home")
    env = {**os.environ, "EMBER_HOME": str(home), "EMBER_PORT": "8970", "EMBER_LOOK_PORT": "8971"}
    proc = subprocess.Popen([sys.executable, "-m", "ember"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError("the server stopped at once:\n" + proc.stdout.read())
            try:
                socket.create_connection(("127.0.0.1", 8970), timeout=0.2).close()
                socket.create_connection(("127.0.0.1", 8971), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("the server did not start")
        secret = (home / "secret.txt").read_text().strip()
        yield {"secret": secret, "url": f"{MCP}/{secret}/mcp", "home": home}
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def token_from(html: str) -> str:
    return re.search(r"name='token' value='([^']+)'", html)[1]


def test_end_to_end_wake_keep_recall_through_the_secret_path(server):
    async def chat():
        async with streamable_http_client(server["url"]) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                first = (await session.call_tool("wake", {})).content[0].text
                kept = (await session.call_tool("keep", {"kind": "happened", "words": "We watched the heron on the canal."})).content[0].text
                found = (await session.call_tool("recall", {"about": "heron"})).content[0].text
                missing = (await session.call_tool("recall", {"about": "volcano"})).content[0].text
                second = (await session.call_tool("wake", {})).content[0].text
                return names, first, kept, found, missing, second

    names, first, kept, found, missing, second = asyncio.run(chat())
    assert names == {"wake", "keep", "recall", "card", "log", "weather", "date", "dates", "about_me", "ours", "correct", "settle"}
    assert first.startswith("Nothing kept yet.") and "NOW: " in first
    assert kept.startswith("Kept as #1 (happened), ")
    assert found.startswith("#1 | ") and "| happened | We watched the heron on the canal." in found
    assert missing == "I don't have this."
    assert "WHAT HAS MOVED LATELY" in second and "We watched the heron on the canal." in second
    assert (server["home"] / "mind.db").exists()


def test_wrong_or_missing_secret_is_a_bare_404(server):
    secret = server["secret"]
    flipped = ("A" if secret[0] != "A" else "B") + secret[1:]
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    headers = {"Accept": "application/json, text/event-stream"}
    answers = set()
    for path in ["/", "/mcp", "/mcp/", "/wrong/mcp", f"/{flipped}/mcp", f"/{secret}", f"/{secret}/", f"/{secret}/mcp/x",
                 f"/{secret}/sse", f"/x/{secret}/mcp", "/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server",
                 "/favicon.ico", "/robots.txt"]:
        for answer in (httpx.get(MCP + path), httpx.post(MCP + path, json=body, headers=headers)):
            assert answer.status_code == 404, path
            assert secret not in answer.text
            answers.add((answer.status_code, answer.text, answer.headers["content-type"]))
    assert answers == {(404, "Not Found", "text/plain")}   # every wrong door looks exactly the same
    assert httpx.post(server["url"], json=body, headers=headers).status_code == 200   # and the right one opens


def test_the_right_path_works_under_a_tunnel_host_name(server):
    """A tunnel sends requests with its own public name in the Host header."""
    answer = httpx.post(server["url"], headers={"Host": "my-laptop.example-tailnet.ts.net", "Accept": "application/json, text/event-stream",
                                                "Origin": "https://claude.ai"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert answer.status_code == 200 and answer.headers["content-type"].startswith("application/json")
    assert "wake" in answer.text


def test_look_page_is_not_reachable_on_the_mcp_port(server):
    for path in ["/", "/export", "/delete?what=line&id=1", "/edit-ours?id=1", f"/{server['secret']}/", f"/{server['secret']}/export"]:
        answer = httpx.get(MCP + path)
        assert (answer.status_code, answer.text) == (404, "Not Found"), path
    assert httpx.post(MCP + "/pour", data={"text": "x"}).status_code == 404
    home = httpx.get(LOOK + "/")   # while on its own port it is there
    assert home.status_code == 200 and "What your companion's mind keeps" in home.text


def test_look_page_refuses_a_foreign_host_name_and_a_missing_token(server):
    assert httpx.get(LOOK + "/", headers={"Host": "evil.example.com"}).status_code == 404
    assert httpx.get(LOOK + "/", headers={"Host": "my-laptop.example-tailnet.ts.net"}).status_code == 404
    assert httpx.post(LOOK + "/pour", data={"text": "sneaked in"}).status_code == 403
    assert "sneaked in" not in httpx.get(LOOK + "/").text


def test_both_ports_listen_on_this_computer_only(server):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))   # sends nothing: only asks which address would be used
        lan = probe.getsockname()[0]
    except OSError:
        pytest.skip("no network address to test from")
    finally:
        probe.close()
    if lan.startswith("127."):
        pytest.skip("no network address to test from")
    for port in (8970, 8971):
        with pytest.raises(OSError):
            socket.create_connection((lan, port), timeout=1).close()


def test_look_page_shows_pours_exports_and_deletes(server):
    page = httpx.get(LOOK + "/").text
    token = token_from(page)
    assert "We watched the heron on the canal." in page and f"/{server['secret']}/mcp" in page

    poured = httpx.post(LOOK + "/pour", data={"token": token, "text": "First summary, about a lighthouse.\n\nSecond summary.", "about_when": "last year"})
    assert "Poured in 2 lines" in poured.text and "First summary, about a lighthouse." in poured.text
    assert "from before, poured in by my human from old summaries, about: last year" in poured.text

    export = httpx.get(LOOK + "/export")
    assert export.headers["content-type"].startswith("text/plain") and "attachment" in export.headers["content-disposition"]
    assert "First summary, about a lighthouse." in export.text and "We watched the heron" in export.text

    line_id = re.search(r"<tr><td>(\d+)</td>(?:(?!</tr>).)*lighthouse", httpx.get(LOOK + "/").text, re.S)[1]
    confirm = httpx.get(LOOK + f"/delete?what=line&id={line_id}")
    assert "Delete this for good?" in confirm.text and "lighthouse" in confirm.text
    assert "lighthouse" in httpx.get(LOOK + "/").text   # asking is not deleting
    gone = httpx.post(LOOK + "/delete", data={"token": token, "what": "line", "id": line_id})
    assert "Deleted for good." in gone.text and "lighthouse" not in gone.text
    assert "lighthouse" not in httpx.get(LOOK + "/export").text


def test_ours_on_the_look_page_and_a_suggestion_from_the_companion(server):
    token = token_from(httpx.get(LOOK + "/").text)
    added = httpx.post(LOOK + "/ours", data={"token": token, "title": "For hard days", "words": "Stay close.\nNo advice."})
    assert "Added to ours." in added.text

    async def chat():
        async with streamable_http_client(server["url"]) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                said = (await session.call_tool("ours", {"title": "Our word for rest", "words": "We call it harbour."})).content[0].text
                return said, (await session.call_tool("wake", {})).content[0].text

    said, wake = asyncio.run(chat())
    assert "not live" in said
    assert "- For hard days\n    Stay close.\n    No advice." in wake and "harbour" not in wake

    page = httpx.get(LOOK + "/").text
    assert "Suggested by your companion" in page and "We call it harbour." in page
    suggestion = re.search(r"action='/ours/accept'>.*?name='id' value='(\d+)'", page, re.S)[1]
    assert "Accepted." in httpx.post(LOOK + "/ours/accept", data={"token": token, "id": suggestion}).text
    assert "harbour" in asyncio.run(chat())[1]

    saved = httpx.post(LOOK + "/ours", data={"token": token, "id": suggestion, "title": "Our word for rest", "words": "We call it the harbour."})
    assert "Saved. The earlier wording is kept." in saved.text and "Earlier wordings of ours" in saved.text


ODD = '  “Don’t—ever… call it ‘fine’.”  It\'s NOT fine!!  🙃🫶🏽 <b>&amp;</b> 100%\ttab\n   second line,  two  spaces.  '
DOSE = "08:10 gave 0.25 ml (1.5 mg/ml) with food; weight 4.35 kg; temp 38.9°C\n  next: ½ tablet @ 19:30  "


def test_exact_words_and_log_entries_survive_the_whole_trip(server):
    """Through the real server, as JSON over HTTP, into SQLite and back out again."""
    async def chat():
        async with streamable_http_client(server["url"]) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                async def call(tool, **args):
                    return (await session.call_tool(tool, args)).content[0].text
                await call("keep", kind="said", words=ODD)
                await call("card", name="Pip", words="A small grey cat.", kind="animal")
                await call("log", card="Pip", words=DOSE)
                await call("weather", words="Worn out but steady.")
                await call("keep", kind="taught", words="Ask before giving advice.")
                await call("keep", kind="promise", words="I will ask about Friday.")
                return await call("recall", about="fine"), await call("card", name="Pip"), await call("wake")

    found, card, wake = asyncio.run(chat())
    assert f'"{ODD}"' in found and f'"{ODD}"' in wake
    assert f"| {DOSE}" in card and DOSE in wake
    assert wake.startswith("HOW MY HUMAN IS (the weather; written less than an hour ago")
    assert "Ask before giving advice." in wake and "I will ask about Friday." in wake


def test_look_page_new_since_you_last_looked_and_about_you(server):
    def section(html):
        return html[html.index("<h2>New since you last looked</h2>"):html.index("<h2>Ours</h2>")]

    def kind_cell(html, words):
        row = next(r for r in html.split("<tr") if words in r)
        return row.split("</td>")[2]

    page = httpx.get(LOOK + "/").text
    token = token_from(page)
    assert "What does your companion call you?" in page
    assert "You have not marked anything as seen yet" in section(page) and "I will ask about Friday." in section(page)

    seen = httpx.post(LOOK + "/seen", data={"token": token}).text
    assert "Marked as seen." in seen and "Nothing new since " in section(seen) and "I will ask about Friday." not in section(seen)
    assert "I will ask about Friday." in seen                      # still on the page, only no longer new

    async def chat():
        async with streamable_http_client(server["url"]) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("keep", {"kind": "happened", "words": "Robin laughed at the heron today."})
                await session.call_tool("keep", {"kind": "note", "words": "The robin by the gate is singing... no, that is Robinson Lane."})
                await session.call_tool("keep", {"kind": "note", "words": "The kettle is blue."})
    time.sleep(1.1)                                                # times are kept to the second
    asyncio.run(chat())
    page = httpx.get(LOOK + "/").text
    assert "Robin laughed at the heron today." in section(page) and "The kettle is blue." in section(page)
    assert "Worn out but steady." not in section(page)             # seen already

    # before she gives her name: her words, what she taught and the weather are already marked
    for words in ("call it ‘fine’", "Ask before giving advice.", "Worn out but steady."):
        assert "about you" in kind_cell(page, words), words
    for words in ("Robin laughed", "The kettle is blue.", "I will ask about Friday."):
        assert "about you" not in kind_cell(page, words), words

    named = httpx.post(LOOK + "/name", data={"token": token, "names": " Robin , Rob "}).text
    assert "What does your companion call you?" not in named and "value='Robin, Rob'" in named
    assert "about you" in kind_cell(named, "Robin laughed")
    assert "about you" in kind_cell(named, "robin by the gate")            # her name in any case
    assert "about you" not in kind_cell(named, "The kettle is blue.")
    assert "Robin" not in httpx.get(LOOK + "/export").text.split("EVERY LINE")[0]   # the name is for the page only


def test_the_human_can_correct_a_log_entry_on_the_look_page(server):
    page = httpx.get(LOOK + "/").text
    token = token_from(page)
    assert "not a medical or veterinary record" in page and "check a dose" in page
    line_id = re.search(r"<tr><td>(\d+)</td>(?:(?!</tr>).)*gave 0\.25 ml", page, re.S)[1]
    form = httpx.get(LOOK + f"/correct?id={line_id}").text
    assert "Correct this line" in form and "gave 0.25 ml" in form
    fixed = DOSE.replace("0.25 ml", "0.20 ml")
    httpx.post(LOOK + "/seen", data={"token": token})
    time.sleep(1.1)
    saved = httpx.post(LOOK + "/correct", data={"token": token, "id": line_id, "words": fixed.replace("\n", "\r\n")}).text
    assert "Corrected. The earlier wording is kept and marked." in saved
    assert "Nothing new since" in saved                           # her own correction is not "new from the companion"

    async def chat():
        async with streamable_http_client(server["url"]) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return (await session.call_tool("card", {"name": "Pip"})).content[0].text

    card = asyncio.run(chat())
    assert f"| corrects #{line_id} because: corrected by my human on their own page | {fixed}" in card
    assert f"#{line_id} | " in card and "CORRECTED, THE CURRENT WORDING IS" in card and DOSE in card   # the wrong one is still there, marked
