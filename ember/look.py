"""The look page: for the human, on this computer only.

Everything the mind keeps, plainly readable. Delete a line, export it all,
pour in old summaries, and write the "ours" list. Plain HTML made on the
server, no scripts, nothing loaded from the internet.

It listens on 127.0.0.1 on its own port. Never tunnel that port.
"""

from __future__ import annotations

import secrets
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import re

from .store import BY_HUMAN, Mind, date_words, kind_words, short_date

CSS = """
body{font:17px/1.5 system-ui,sans-serif;max-width:54rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fbfaf7}
h1{font-size:1.6rem} h2{font-size:1.2rem;margin-top:2.5rem;border-bottom:1px solid #ccc;padding-bottom:.2rem}
table{border-collapse:collapse;width:100%} td,th{text-align:left;vertical-align:top;padding:.4rem .5rem;border-bottom:1px solid #ddd}
td.words{white-space:pre-wrap} .small{font-size:.85rem;color:#555} .old{color:#777}
textarea,input[type=text]{width:100%;box-sizing:border-box;font:inherit;padding:.4rem}
button{font:inherit;padding:.3rem .8rem} .box{background:#fff;border:1px solid #ccc;padding:.8rem 1rem;margin:.8rem 0;border-radius:6px}
.suggested{border-left:5px solid #c80} .said{background:#e7f4e4;border:1px solid #9c9;padding:.5rem 1rem;border-radius:6px}
code{word-break:break-all} form.inline{display:inline}
.you{background:#fde9a8;color:#5a4300;border-radius:4px;padding:0 .35rem;font-size:.8rem;white-space:nowrap} .new{border-left:5px solid #58a}
@media (prefers-color-scheme:dark){body{background:#1c1c1c;color:#ddd}.box{background:#262626;border-color:#444}
td,th{border-color:#333}.small{color:#aaa}.said{background:#243524;border-color:#474}a{color:#9cf}}
"""


def page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{escape(title)}</title>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'><style>{CSS}</style></head>"
            f"<body>{body}</body></html>").encode()


def start_look_page(mind: Mind, secret: str, host: str, port: int, mcp_port: int) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(16)  # stops other web pages from pressing these buttons
    hidden = f"<input type='hidden' name='token' value='{token}'>"
    good_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def ours_form(entry=None) -> str:
        title = escape(entry["title"]) if entry else ""
        words = escape(entry["words"]) if entry else ""
        which = f"<input type='hidden' name='id' value='{entry['id']}'>" if entry else ""
        return (f"<form method='post' action='/ours'>{hidden}{which}"
                f"<p><label>Title<br><input type='text' name='title' value='{title}' maxlength='120' required></label></p>"
                f"<p><label>Words<br><textarea name='words' rows='6' required>{words}</textarea></label></p>"
                f"<p><button>{'Save changes' if entry else 'Add to ours'}</button></p></form>")

    def about_you(row) -> bool:
        """Is this line about the human? Their own words, what they taught, how they are, or their name."""
        names = [n.strip() for n in mind.setting("names").split(",") if n.strip()]
        return row["kind"] in ("said", "taught", "weather") or any(
            re.search(rf"(?<!\w){re.escape(n)}(?!\w)", row["words"], re.I) for n in names)

    def line_row(r, now) -> str:
        badge = " <span class='you'>about you</span>" if about_you(r) else ""
        fix = "" if r["state"] in ("corrected", "replaced") else f"<a href='/correct?id={r['id']}'>Correct</a> &nbsp; "
        return (f"<tr{' class=old' if r['state'] in ('corrected', 'replaced') else ''}><td>{r['id']}</td><td class='small'>{short_date(r['at'])}</td>"
                f"<td class='small'>{escape(kind_words(r, now))}{badge}</td><td class='words'>{escape(r['words'])}</td>"
                f"<td class='small'>{fix}<a href='/delete?what=line&amp;id={r['id']}'>Delete</a></td></tr>")

    HEAD = "<table><tr><th>No.</th><th>Date</th><th>Kind</th><th>Words</th><th></th></tr>"

    def home(said: str = "") -> bytes:
        now = mind.now()
        b = ["<h1>What your companion's mind keeps</h1>",
             "<p>This page is only on this computer. Everything here is yours. You can read it, delete it, or save a copy.</p>"]
        if said:
            b.append(f"<p class='said'>{escape(said)}</p>")
        b.append("<p><a href='/export'>Save everything as one text file</a></p>")

        if not mind.setting("names"):
            b.append(f"<div class='box'><form method='post' action='/name'>{hidden}<label>What does your companion call you? "
                     "Lines that mention you will then be marked <span class='you'>about you</span>. This stays on this computer. "
                     "<input type='text' name='names' maxlength='200' placeholder='your name, and any nicknames, with commas between'></label>"
                     "<p><button>Save</button></p></form></div>")

        last = mind.setting("last_looked")
        fresh = mind.since(last)
        waiting = [o for o in mind.ours_list("proposed") if o["at"] > last]
        b.append("<h2>New since you last looked</h2>")
        if fresh or waiting:
            b.append(f"<p class='small'>{'Since ' + short_date(last) if last else 'You have not marked anything as seen yet, so this is everything'}. "
                     "Nothing is written about you behind your back: whatever your companion keeps shows up here first.</p>")
            if waiting:
                b.append(f"<p>Your companion suggested {len(waiting)} new entr{'ies' if len(waiting) != 1 else 'y'} for Ours. See below.</p>")
            if fresh:
                b.append("<div class='new'>" + HEAD + "".join(line_row(r, now) for r in fresh) + "</table></div>")
            b.append(f"<form method='post' action='/seen'>{hidden}<p><button>I have seen these</button></p></form>")
        else:
            b.append(f"<p>Nothing new{' since ' + short_date(last) if last else ''}.</p>")

        b.append("<h2>Ours</h2><p>Your agreements: a few things you and your companion write together. Your companion gets these whole and "
                 "unchanged at the start of every chat. Only you can change them. Standing rules and signals between the two of you "
                 "belong here, because they must never drift. One good use: an entry called "
                 "<em>For hard days</em>, in your own words: what helps, and what does not.</p>")
        for o in mind.ours_list("proposed"):
            b.append(f"<div class='box suggested'><p class='small'>Suggested by your companion on {short_date(o['at'])}. "
                     f"It is not in use unless you accept it.</p><p><strong>{escape(o['title'])}</strong></p>"
                     f"<p style='white-space:pre-wrap'>{escape(o['words'])}</p>"
                     f"<form class='inline' method='post' action='/ours/accept'>{hidden}<input type='hidden' name='id' value='{o['id']}'><button>Accept</button></form> "
                     f"<form class='inline' method='post' action='/delete'>{hidden}<input type='hidden' name='what' value='ours'><input type='hidden' name='id' value='{o['id']}'><button>Decline</button></form> "
                     f"<a href='/edit-ours?id={o['id']}'>Change the words first</a></div>")
        for o in mind.ours_list():
            b.append(f"<div class='box'><p><strong>{escape(o['title'])}</strong> <span class='small'>last written {short_date(o['at'])}</span></p>"
                     f"<p style='white-space:pre-wrap'>{escape(o['words'])}</p>"
                     f"<p><a href='/edit-ours?id={o['id']}'>Edit</a> &nbsp; <a href='/delete?what=ours&amp;id={o['id']}'>Delete</a></p></div>")
        b.append(f"<details><summary>Add an entry to ours</summary>{ours_form()}</details>")
        if mind.ours_history():
            b.append("<details><summary>Earlier wordings of ours</summary><table>")
            b += [f"<tr><td class='small'>until {short_date(h['replaced_at'])}</td><td class='words old'><strong>{escape(h['old_title'])}</strong>\n{escape(h['old_words'])}</td>"
                  f"<td><a href='/delete?what=ours_history&amp;id={h['id']}'>Delete</a></td></tr>" for h in mind.ours_history()]
            b.append("</table></details>")

        b.append("<h2>Pour in old summaries</h2><p>Paste summaries you wrote by hand. Each paragraph becomes one kept line, "
                 "marked as <em>from before</em>, so your companion always knows it came from you and not from its own memory.</p>"
                 f"<form method='post' action='/pour'>{hidden}<p><textarea name='text' rows='8' required></textarea></p>"
                 "<p><label>About when is this from? You can leave this empty. <input type='text' name='about_when' maxlength='80' placeholder='for example: spring 2026'></label></p>"
                 "<p><button>Pour in</button></p></form>")

        b.append("<h2>Who your companion says it is</h2><p class='small'>The steady list. Your companion wrote these itself.</p><table>")
        b += [f"<tr><td class='small'>{short_date(m['at'])}</td><td class='words'>{escape(m['words'])}</td>"
              f"<td><a href='/delete?what=me&amp;id={m['id']}'>Delete</a></td></tr>" for m in mind.me_list()] or ["<tr><td>Nothing yet.</td></tr>"]
        b.append("</table>")
        if mind.me_history():
            b.append("<details><summary>Earlier wordings</summary><table>")
            b += [f"<tr><td class='small'>until {short_date(h['replaced_at'])}</td><td class='words old'>{escape(h['old_words'])}</td>"
                  f"<td><a href='/delete?what=me_history&amp;id={h['id']}'>Delete</a></td></tr>" for h in mind.me_history()]
            b.append("</table></details>")

        found = mind.dates_all()
        if found:
            b.append("<h2>Dates your companion wrote down</h2><table>")
            b += [f"<tr><td class='words'>{escape(r['title'])}</td><td class='small'>{escape(date_words(r))}</td>"
                  f"<td><a href='/delete?what=date&amp;id={r['id']}'>Delete</a></td></tr>" for r, _, _ in found]
            b.append("</table>")

        rows = mind.all_lines()
        b.append(f"<h2>Every kept line ({len(rows)}), newest first</h2>"
                 "<p class='small'>Ember is a notebook. It is not a medical or veterinary record. Log entries are kept exactly as your "
                 "companion wrote them, so read them, and press Correct on any that is wrong. Always check a dose against the "
                 "packet, the prescription, or the vet or doctor.</p>" + HEAD)
        b += [line_row(r, now) for r in rows] or ["<tr><td colspan='5'>Nothing kept yet.</td></tr>"]
        b.append("</table>")

        b.append("<h2>The address for the Claude app</h2><p>Put your own https address in front of this:</p>"
                 f"<p><code>/{escape(secret)}/mcp</code></p><p class='small'>So the whole thing looks like "
                 f"<code>https://YOUR-ADDRESS/{escape(secret)}/mcp</code>. Keep it private. Anyone who has it can read and write this mind. "
                 f"The tunnel should point at port {mcp_port}. Never at this page.</p>")
        b.append(f"<details><summary>Change the name your companion calls you</summary><form method='post' action='/name'>{hidden}"
                 f"<p><input type='text' name='names' maxlength='200' value='{escape(mind.setting('names'), quote=True)}'></p><p><button>Save</button></p></form></details>")
        return page("Ember", "".join(b))

    WHAT = {  # what can be deleted: (how to find it, how to delete it, how to show it)
        "line": (lambda i: mind.get(i), mind.delete_line, lambda r: r["words"]),
        "me": (lambda i: next((m for m in mind.me_list() if m["id"] == i), None), mind.delete_me, lambda r: r["words"]),
        "me_history": (lambda i: next((h for h in mind.me_history() if h["id"] == i), None), mind.delete_history, lambda r: r["old_words"]),
        "ours": (lambda i: next((o for o in mind.ours_list() + mind.ours_list("proposed") if o["id"] == i), None), mind.ours_delete, lambda r: f"{r['title']}\n{r['words']}"),
        "date": (lambda i: next((r for r, _, _ in mind.dates_all() if r["id"] == i), None), mind.date_delete, lambda r: f"{r['title']}\n{date_words(r)}"),
        "ours_history": (lambda i: next((h for h in mind.ours_history() if h["id"] == i), None), mind.ours_history_delete, lambda r: f"{r['old_title']}\n{r['old_words']}"),
    }

    class Look(BaseHTTPRequestHandler):
        server_version = "ember-look"

        def log_message(self, *args):  # quiet
            pass

        def answer(self, body: bytes, status: int = 200, kind: str = "text/html; charset=utf-8", extra=()):
            self.send_response(status)
            for name, value in (("Content-Type", kind), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"), *extra):
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def back_home(self, said: str = ""):
            self.answer(home(said))

        def allowed(self) -> bool:
            if self.headers.get("Host") in good_hosts:
                return True
            self.answer(b"Not Found", 404, "text/plain")
            return False

        def do_GET(self):
            if not self.allowed():
                return
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/":
                return self.back_home()
            if url.path == "/export":
                name = f"ember-{mind.now().astimezone():%Y-%m-%d}.txt"
                return self.answer(mind.export_text().encode(), kind="text/plain; charset=utf-8",
                                   extra=[("Content-Disposition", f'attachment; filename="{name}"')])
            if url.path == "/delete" and query.get("what") in WHAT and query.get("id", "").isdigit():
                find, _, show = WHAT[query["what"]]
                row = find(int(query["id"]))
                if row:
                    return self.answer(page("Delete?", "<h1>Delete this for good?</h1>"
                        f"<div class='box' style='white-space:pre-wrap'>{escape(show(row))}</div>"
                        "<p>It will be gone from the mind. This cannot be undone.</p>"
                        f"<form method='post' action='/delete'>{hidden}<input type='hidden' name='what' value='{query['what']}'>"
                        f"<input type='hidden' name='id' value='{int(query['id'])}'><button>Yes, delete it</button> &nbsp; <a href='/'>No, keep it</a></form>"))
            if url.path == "/correct" and query.get("id", "").isdigit():
                row = mind.get(int(query["id"]))
                if row and row["state"] not in ("corrected", "replaced"):
                    return self.answer(page("Correct", "<h1>Correct this line</h1>"
                        f"<form method='post' action='/correct'>{hidden}<input type='hidden' name='id' value='{row['id']}'>"
                        f"<p><textarea name='words' rows='8' required>{escape(row['words'])}</textarea></p>"
                        "<p><button>Save the right words</button> &nbsp; <a href='/'>Back without saving</a></p></form>"
                        "<p class='small'>The wrong wording is kept, marked as corrected, so you can always see what was there. "
                        "Your companion will be shown your wording from now on.</p>"))
            if url.path == "/edit-ours" and query.get("id", "").isdigit():
                entry = WHAT["ours"][0](int(query["id"]))
                if entry:
                    return self.answer(page("Edit", f"<h1>Edit this entry</h1>{ours_form(entry)}<p><a href='/'>Back without saving</a></p>"
                                                    "<p class='small'>The wording you replace is kept under earlier wordings.</p>"))
            self.answer(page("Not here", "<h1>That is not here.</h1><p><a href='/'>Back</a></p>"), 404)

        def do_POST(self):
            if not self.allowed():
                return
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True).items()}
            if not secrets.compare_digest(form.get("token", ""), token):
                return self.answer(page("Try again", "<h1>This page was open too long.</h1><p><a href='/'>Go back and try again.</a></p>"), 403)
            path, number = urlparse(self.path).path, int(form["id"]) if form.get("id", "").isdigit() else None
            try:
                if path == "/pour":
                    ids = mind.pour(form.get("text", ""), form.get("about_when"))
                    return self.back_home(f"Poured in {len(ids)} line{'s' if len(ids) != 1 else ''}. They are marked as from before."
                                          if ids else "There was nothing to pour in.")
                if path == "/name":
                    mind.setting("names", ", ".join(n.strip() for n in form.get("names", "")[:200].split(",") if n.strip()))
                    return self.back_home("Saved.")
                if path == "/seen":
                    mind.setting("last_looked", mind.now().isoformat(timespec="seconds"))
                    return self.back_home("Marked as seen.")
                if path == "/correct" and number is not None:
                    mind.correct(number, form.get("words", "").replace("\r\n", "\n"), BY_HUMAN)
                    return self.back_home("Corrected. The earlier wording is kept and marked.")
                if path == "/ours":
                    if number is None:
                        mind.ours_write(form.get("title", ""), form.get("words", ""))
                        return self.back_home("Added to ours.")
                    mind.ours_edit(number, form.get("title", ""), form.get("words", ""))
                    return self.back_home("Saved. The earlier wording is kept.")
                if path == "/ours/accept" and number is not None:
                    return self.back_home("Accepted. It is part of ours now." if mind.ours_accept(number) else "That one was not waiting.")
                if path == "/delete" and form.get("what") in WHAT and number is not None:
                    return self.back_home("Deleted for good." if WHAT[form["what"]][1](number) else "That was already gone.")
            except ValueError as problem:
                return self.back_home(str(problem))
            self.answer(page("Not here", "<h1>That is not here.</h1><p><a href='/'>Back</a></p>"), 404)

    server = ThreadingHTTPServer((host, port), Look)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
