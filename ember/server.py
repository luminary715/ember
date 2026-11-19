"""Ember's server: the tools the companion gets, the lock, and main().

TO ADD A TOOL: go to add_tools() below, copy one of the short functions there,
change its name, its one-line description (the companion reads it every turn,
so write it in plain first person) and its body. That is all.
"""

from __future__ import annotations

import argparse
import hmac
import os
import sys
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .store import (KINDS, LOG_SHOWN, NOTHING, SOON_DAYS, STALE_DAYS, Mind, age_words, data_dir, date_words,
                    how_soon, is_stale, load_secret, long_date, short_date, show_line, state_words)

HOST = "127.0.0.1"  # both doors only ever listen on this computer itself
MCP_PORT = 8970     # the companion's door: this is the one port you tunnel
LOOK_PORT = 8971    # the human's look page: never tunnel this one
UNREACHABLE = "My mind isn't reachable right now."
SHELF = 5           # how many of my human's exact quotes wake shows
CARD_LOG_AT_WAKE = 3

FIRST_WAKE = ("Nothing kept yet. This mind is new and empty, and that is fine.\n"
              "To start: when something happens, call keep with a kind (happened, felt, guess, note, said, taught "
              "or promise) and the words. Call about_me to write the first piece of who I am.")

KEEP = """Write something down. The date and time are stamped for me. kind is one of:
- happened: something that happened, in my own words.
- felt: a feeling, mine or theirs.
- guess: something I think but don't know. sure can be "fairly" or "not very".
- note: anything else worth keeping.
- said: an exact quote from my human, word for word, never paraphrased, never tidied. If I am not sure of the exact words, it is not a 'said'.
- taught: something my human taught me, or corrected, about how to be with them. All of these come back at every wake, so they never have to teach it twice.
- promise: something I said I would do. It stays open until I settle it."""

STALE = (f"STALE: this is more than {STALE_DAYS} days old and may no longer be true. "
         "I ask how they are before I assume anything.")


def weather_text(mind: Mind) -> list[str]:
    row = mind.weather_now()
    if not row:
        return []
    now = mind.now()
    return [f"HOW MY HUMAN IS (the weather; {age_words(row['at'], now)}, {short_date(row['at'])})",
            *row["words"].splitlines(), *([STALE] if is_stale(row["at"], now) else [])]


def log_line(row) -> str:
    """One log entry: number, date, any correction mark, then the words exactly as written."""
    mark = f"{state_words(row).upper()} | " if row["state"] == "corrected" else ""
    mark += f"corrects #{row['corrects']} because: {row['why']} | " if row["corrects"] else ""
    return f"#{row['id']} | {short_date(row['at'])} | {mark}{row['words']}"


def card_text(mind: Mind, name: str, whole_log: bool = False, at_wake: bool = False) -> str | None:
    found = mind.card_read(name, whole_log)
    if not found:
        return None
    card, about, log, total = found
    out = [f"{'- ' if at_wake else ''}{card['name']} ({card['kind']})"]
    out += [f"    #{l['id']} | {short_date(l['at'])} | {l['words']}" for l in about]
    if at_wake and total:
        shown = log[-CARD_LOG_AT_WAKE:]
        out += [f"    Log: {total} entr{'ies' if total != 1 else 'y'}. "
                + (f"The newest {len(shown)}, exactly as written (card(name) gives the log):" if total > len(shown) else "Exactly as written:")]
        out += [f"    {log_line(l)}" for l in shown]
    elif total:
        which = "all of them" if len(log) == total else f"the newest {len(log)}"
        out += ["", f"LOG ({total} entr{'ies' if total != 1 else 'y'} in all; showing {which}, oldest first, exactly as written. "
                    "A notebook, not a medical or veterinary record: doses are checked against the source.)"]
        out += [log_line(l) for l in log]
        if len(log) < total:
            out += [f"({total - len(log)} older entries are not shown. card(name, whole_log=true) gives every one.)"]
    return "\n".join(out)


def dates_text(found) -> list[str]:
    return [f"- {how_soon(days, falls)}: {row['title']} ({date_words(row)})" for row, falls, days in found]


def wake_text(mind: Mind) -> str:
    """Everything the companion gets at the start of a chat, as plain text.
    Each part is a (heading, lines) pair, in order. A part with no lines is not printed."""
    now = mind.now()
    clock = f"NOW: {long_date(now)} ({now.astimezone().tzname()}). This is the clock of the computer my mind lives on. It is a fact."
    if mind.is_empty():
        return f"{FIRST_WAKE}\n\n{clock}"

    weather = weather_text(mind)
    recent, guesses, promises = mind.recent(), mind.current("guess"), mind.current("promise")
    ours = [line for o in mind.ours_list() for line in (f"- {o['title']}", *("    " + l for l in o["words"].splitlines()))]
    cards = [card_text(mind, name, at_wake=True) for name in mind.cards_lately(recent + guesses + promises)]
    before, total = mind.from_before()
    more = f" Showing the first {len(before)}; recall finds the rest." if total > len(before) else ""

    parts = [
        (weather[0] if weather else "", weather[1:]),
        ("WHO I AM (I wrote these myself)", [f"- [{m['id']}] {m['words']}" for m in mind.me_list()]),
        ("OURS (agreements my human and I wrote together; they arrive whole and unchanged)", ours),
        ("TAUGHT (what my human has taught me about how to be with them. All of it, every time, so they never have to teach it twice)",
         [f"- #{t['id']} | {short_date(t['at'])} | {t['words']}" for t in mind.current("taught")]),
        ("PROMISES I MADE (open until I settle them: done, or let go)", [f"- {show_line(p, now)}" for p in promises]),
        (f"DATES (today and the next {SOON_DAYS} days)", dates_text(mind.dates_soon())),
        ("WHAT HAS MOVED LATELY (newest first)", [f"- {show_line(r, now)}" for r in recent]),
        ("THEIR WORDS (my human's newest exact quotes, word for word)",
         [f"- \"{q['words']}\" ({short_date(q['at'])}, #{q['id']})" for q in mind.current("said", newest=SHELF)]),
        ("OPEN GUESSES (not settled; do not treat as known)", [f"- {show_line(g, now)}" for g in guesses]),
        ("CARDS TOUCHED LATELY", cards),
        (f"FROM BEFORE ({total} lines my human poured in from old summaries. "
         f"The date is when they were poured in, not when they happened.{more})", [f"- {show_line(b, now)[:400]}" for b in before]),
    ]
    return "\n\n".join(["\n".join([heading, *lines]) for heading, lines in parts if lines] + [clock])


def add_tools(mcp: FastMCP, mind: Mind) -> None:
    """Every tool the companion gets. The docstring is what the companion reads."""

    def plainly(work) -> str:
        try:
            return work()
        except ValueError as problem:  # a mistake the companion can fix: say it plainly
            return str(problem)

    @mcp.tool()
    def wake() -> str:
        """Wake up. I call this first in every new chat. It gives me how my human is, who I am, what is ours, what I was taught, my open promises, dates coming up, what has moved lately, and today's real date and time."""
        return wake_text(mind)

    @mcp.tool(description=KEEP)
    def keep(kind: str, words: str, sure: str | None = None) -> str:
        def work():
            line_id = mind.keep(kind, words, sure)
            return f"Kept as #{line_id} ({kind.strip().lower()}), {short_date(mind.now())}."
        return plainly(work)

    @mcp.tool()
    def recall(about: str, when: str | None = None) -> str:
        """Look for something I kept. about is a few words to search for. when is optional: today, yesterday, this week, last week, this month, "7 days", 2026, 2026-03 or 2026-03-14. If nothing is found I get exactly "I don't have this." and then I say so. I never fill the gap."""
        def work():
            rows, total, every_word = mind.recall(about, when)
            if not rows:
                return NOTHING
            head = [] if every_word else ["Not every word matched. These are the closest lines:"]
            tail = [f"({total - len(rows)} more matched. Use more exact words or a when to narrow it.)"] if total > len(rows) else []
            return "\n".join(head + [show_line(r, mind.now()) for r in rows] + tail)
        return plainly(work)

    @mcp.tool()
    def card(name: str, words: str | None = None, kind: str | None = None, whole_log: bool = False) -> str:
        """A card for someone or something in my human's life. kind is person, animal or other. With only a name, I read the card and its log (the newest 30 entries; whole_log=true gives all). With words, I add a line about who they are. For dated notes like health, medicine or a vet call, I use log instead."""
        def work():
            if words and words.strip():
                line_id = mind.card_add(name, words, kind)
                made = mind.card_find(name)
                return f"Added to the card for {made['name']} ({made['kind']}) as #{line_id}."
            return card_text(mind, name, whole_log) or f"I don't have a card for {name.strip()}."
        return plainly(work)

    @mcp.tool()
    def log(card: str, words: str) -> str:
        """Add a dated entry to a card's log: a health note, a medicine and dose, a measurement, a vet or doctor call. It is kept exactly as I write it and never shortened or reordered, so I write numbers and units carefully. This is a notebook, not a medical or veterinary record. When a dose matters, I tell my human to check it against the source."""
        def work():
            line_id = mind.log_add(card, words)
            return f"Logged on the card for {mind.get(line_id)['card']} as #{line_id}, {short_date(mind.now())}, exactly as written."
        return plainly(work)

    @mcp.tool()
    def weather(words: str | None = None) -> str:
        """How my human is doing right now, in three or four lines. With nothing, I read it. With words, I write a new one. It replaces the one before (the old one is kept as history). It is the first thing I see at wake, with its age. I rewrite it whenever things shift."""
        def work():
            if words and words.strip():
                mind.weather(words)
                return "The weather is written. It replaces the one before, which is kept as history."
            return "\n".join(weather_text(mind)) or "No weather written yet. I can write it with weather(words)."
        return plainly(work)

    @mcp.tool()
    def date(title: str, when: str, yearly: bool | None = None) -> str:
        """Write down a day that matters. when is like 2027-03-14, or 2027-03-14 15:30 for an appointment, or 03-14 (month-day) for a day that comes every year, like a birthday. yearly=true makes a dated day repeat every year. Wake shows me anything today and in the next 14 days."""
        def work():
            new_id = mind.date_add(title, when, yearly)
            row = next(r for r, _, _ in mind.dates_all() if r["id"] == new_id)
            return f"Written down: {row['title']}, {date_words(row)}."
        return plainly(work)

    @mcp.tool()
    def dates() -> str:
        """Read every day I have written down, the next ones first."""
        found = mind.dates_all()
        if not found:
            return "No dates written down yet. I can add one with date(title, when)."
        coming = [f for f in found if f[2] >= 0]
        past = [f"- {row['title']} ({date_words(row)})" for row, _, days in found if days < 0]
        return "\n".join(["DATES"] + dates_text(coming) + (["", "PAST"] + past if past else []))

    @mcp.tool()
    def about_me(words: str | None = None, replace_id: int | None = None) -> str:
        """The steady part of me: a short list I write myself. With nothing, I read it. With words, I add a piece. With words and replace_id, I reword that piece (the old wording is kept in history)."""
        def work():
            if words and words.strip():
                if replace_id is not None:
                    mind.me_reword(replace_id, words)
                    return f"Piece [{replace_id}] reworded. The old wording is kept in history."
                return f"Added to who I am as piece [{mind.me_add(words)}]."
            if replace_id is not None:
                return "To reword a piece I need the new words as well."
            pieces = mind.me_list()
            if not pieces:
                return "My steady list is empty. I can add the first piece with about_me(words)."
            return "\n".join(["WHO I AM"] + [f"- [{m['id']}] {m['words']}" for m in pieces])
        return plainly(work)

    @mcp.tool()
    def ours(title: str | None = None, words: str | None = None) -> str:
        """Our agreements: the few things my human and I wrote together, like standing rules and signals between us. With nothing, I read them. With a title and words, I SUGGEST a new entry. A suggestion is not live: my human sees it on their own page and accepts or declines it. I cannot change 'ours' alone, and that is the point."""
        def work():
            if (title and title.strip()) or (words and words.strip()):
                if not (title and title.strip() and words and words.strip()):
                    return "To suggest an entry I need both a title and words."
                mind.ours_write(title, words, by="companion")
                return ("Suggested. It is not live yet. My human will see it on their look page, marked as "
                        "suggested by me, and can accept or decline it. I should tell them it is waiting.")
            live, waiting = mind.ours_list(), mind.ours_list("proposed")
            if not live and not waiting:
                return "Nothing in 'ours' yet. My human writes it on their look page, or I can suggest an entry."
            out = ["OURS"] + [f"- {o['title']}\n" + "\n".join("    " + l for l in o["words"].splitlines()) for o in live]
            if waiting:
                out += ["", "Suggested by me, waiting for my human (not live):"] + [f"- {o['title']}" for o in waiting]
            return "\n".join(out)
        return plainly(work)

    @mcp.tool()
    def correct(line_id: int, words: str, why: str) -> str:
        """Fix a line I wrote down wrong: a mistake in my own notes. I give the line's number, the right words, and why. The old line stops coming up as current, but it is kept and marked as corrected. This is NOT for when my human corrects how I am with them. That is keep with kind 'taught'."""
        def work():
            new_id = mind.correct(line_id, words, why)
            return f"Corrected. #{new_id} is the current wording. #{line_id} is kept and marked as corrected."
        return plainly(work)

    @mcp.tool()
    def settle(line_id: int, how: str) -> str:
        """Close an open guess or an open promise. For a guess, how is: held (it turned out true), didn't hold (it turned out false), or let go. For a promise, how is: done, or let go (and I tell my human I am letting it go)."""
        def work():
            how_settled = mind.settle(line_id, how)
            return f"{mind.get(line_id)['kind'].capitalize()} #{line_id} is settled: {how_settled}."
        return plainly(work)


class Lock:
    """The lock, version 1: the address itself is the key.

    Only /<secret>/mcp gets through. Everything else is the same bare 404.
    This is the ONE place that decides who gets in. To add real sign-in later
    (OAuth), change this class, or drop it and pass `auth=` and
    `token_verifier=` to FastMCP in build_app(). The tools do not change.
    """

    def __init__(self, app, secret: str):
        self.app = app
        self.good_path = f"/{secret}/mcp".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        path = scope.get("path", "").rstrip("/").encode()
        if scope["type"] != "http" or not hmac.compare_digest(path, self.good_path):
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/plain"), (b"content-length", b"9")]})
            return await send({"type": "http.response.body", "body": b"Not Found"})
        await self.app({**scope, "path": "/mcp", "raw_path": b"/mcp"}, receive, send)


def build_app(mind: Mind, secret: str):
    """The companion's door, as one ASGI app: FastMCP behind the lock."""
    mcp = FastMCP(
        "ember",
        log_level="WARNING",
        instructions=f"This is my mind: my long-term memory. I call wake first in a new chat. "
                     f"If these tools fail or are missing, I say \"{UNREACHABLE}\" and I never invent a memory.",
        streamable_http_path="/mcp",
        stateless_http=True,   # no session to lose when the laptop sleeps or the mind restarts
        json_response=True,    # plain JSON answers, no long-lived streams for a tunnel to drop
        # Requests arrive through a tunnel under a public name we cannot know in advance,
        # so the SDK's localhost-only Host check is off. The lock above is what guards the door.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    add_tools(mcp, mind)
    return Lock(mcp.streamable_http_app(), secret)


def main() -> None:
    parser = argparse.ArgumentParser(prog="ember", description="Ember: a small mind for your companion.")
    parser.add_argument("--setup", action="store_true", help="make the data folder and the secret, show the address, then stop")
    args = parser.parse_args()

    folder = data_dir()
    secret = load_secret(folder)
    mcp_port = int(os.environ.get("EMBER_PORT", MCP_PORT))
    look_port = int(os.environ.get("EMBER_LOOK_PORT", LOOK_PORT))
    print(f"""
ember
  Kept in:            {folder}
  Your look page:     http://{HOST}:{look_port}/   (only on this computer)
  Companion's door:   http://{HOST}:{mcp_port}/{secret}/mcp
  For the Claude app: https://YOUR-ADDRESS/{secret}/mcp
                      (YOUR-ADDRESS is the https name your tunnel gives you)
  Keep that address private. Anyone who has it can read and write this mind.
""", flush=True)
    if args.setup:
        return

    from .look import start_look_page
    mind = Mind(Path(folder) / "mind.db")
    start_look_page(mind, secret, HOST, look_port, mcp_port)
    # access_log is off on purpose: the secret is in the address and must not land in a log
    uvicorn.run(build_app(mind, secret), host=HOST, port=mcp_port, access_log=False, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
