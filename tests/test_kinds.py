"""Unit tests for: said, taught, weather, promises, dates, cards with logs, and the wake order."""

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from mcp.server.fastmcp import FastMCP

from ember.server import STALE, add_tools, card_text, wake_text
from ember.store import BY_HUMAN, Mind, show_line

ODD = '  “Don’t—ever… call it ‘fine’.”  It\'s NOT fine!!  🙃🫶🏽 ¯\\_(ツ)_/¯ <b>&amp;</b> 100% | #7\ttab\n   second line,  two  spaces.  '


def tools_for(mind):
    mcp = FastMCP("t")
    add_tools(mcp, mind)

    def call(tool, **args):
        content, _ = asyncio.run(mcp.call_tool(tool, args))
        return content[0].text
    return call


# ---- said ---------------------------------------------------------------

def test_said_is_kept_and_returned_byte_for_byte(mind):
    call = tools_for(mind)
    assert call("keep", kind="said", words=ODD).startswith("Kept as #1 (said)")
    assert mind.get(1)["words"] == ODD
    assert mind.get(1)["words"].encode("utf-8") == ODD.encode("utf-8")
    raw = sqlite3.connect(mind.db_path).execute("SELECT words FROM lines WHERE id = 1").fetchone()[0]
    assert raw == ODD                                          # on disk too
    assert f'| said by my human, word for word | "{ODD}"' in call("recall", about="fine")   # in quotation marks, with its date
    assert "Tue 10 Mar 2026" in call("recall", about="fine")
    assert f'- "{ODD}" (Tue 10 Mar 2026' in call("wake")       # and on the shelf at wake
    assert ODD in mind.export_text()


def test_said_refuses_blank_and_a_correction_stays_exact(mind):
    with pytest.raises(ValueError, match="no words"):
        mind.keep("said", "   \n ")
    old = mind.keep("said", "I need quiet")
    new = mind.correct(old, " I need quiet, not silence. ", "I left half of it out")
    assert mind.get(new)["words"] == " I need quiet, not silence. " and mind.get(new)["kind"] == "said"


def test_the_shelf_shows_only_the_newest_few(mind):
    for n in range(8):
        mind.keep("said", f"quote number {n}")
    text = wake_text(mind)
    assert [f'"quote number {n}"' in text for n in range(8)] == [False] * 3 + [True] * 5
    assert text.index("quote number 7") < text.index("quote number 3")


# ---- taught -------------------------------------------------------------

def test_every_taught_line_is_in_wake_in_full_even_under_200_newer_lines(mind, clock):
    long = "When I go quiet, do not fill the silence. " * 40
    taught = [mind.keep("taught", "Never say 'calm down'."), mind.keep("taught", long), mind.keep("taught", "Ask before giving advice.")]
    clock.forward(days=400)
    for n in range(200):
        mind.keep(("happened", "note", "felt", "said", "guess", "promise")[n % 6], f"newer line {n}")
        clock.forward(hours=1)
    text = wake_text(mind)
    section = text[text.index("TAUGHT ("):text.index("PROMISES I MADE")]
    assert "- #1 | Tue 10 Mar 2026" in section and "Never say 'calm down'." in section
    assert long.strip() in section and "Ask before giving advice." in section
    assert len(mind.current("taught")) == 3 and [t["id"] for t in mind.current("taught")] == taught


def test_a_corrected_taught_line_is_replaced_by_its_new_wording(mind):
    old = mind.keep("taught", "Call in the morning.")
    mind.correct(old, "Text in the morning, never call.", "I wrote it down wrong")
    text = wake_text(mind)
    assert "Text in the morning, never call." in text and "| Call in the morning." not in text


# ---- weather ------------------------------------------------------------

def test_weather_replaces_keeps_history_and_is_first_in_wake(mind, clock):
    mind.me_add("I am steady.")
    first = mind.weather("Tired after the move.\nSleeping badly.")
    clock.forward(days=2)
    second = mind.weather("Brighter.\nSlept well twice.\nWorried about Friday.")
    assert mind.weather_now()["id"] == second
    assert (mind.get(first)["state"], mind.get(first)["words"]) == ("replaced", "Tired after the move.\nSleeping badly.")
    text = wake_text(mind)
    assert text.startswith("HOW MY HUMAN IS (the weather; written less than an hour ago, Thu 12 Mar 2026")
    assert text.splitlines()[1:4] == ["Brighter.", "Slept well twice.", "Worried about Friday."]
    assert "Tired after the move." not in text
    assert "an earlier weather, replaced since" in show_line(mind.recall("tired move")[0][0], mind.now())


def test_weather_shows_its_age_and_goes_stale_after_7_days(mind, clock):
    call = tools_for(mind)
    assert call("weather", words="Steady. Eating well.") == "The weather is written. It replaces the one before, which is kept as history."
    clock.forward(hours=5)
    assert "written 5 hours ago" in call("weather")
    clock.forward(days=4)
    assert "written 4 days ago" in call("wake") and STALE not in call("wake")
    clock.forward(days=2, hours=19)                    # exactly 7 days old: not yet
    assert "written 7 days ago" in call("wake") and STALE not in call("wake")
    clock.forward(minutes=1)                           # older than 7 days: stale
    text = call("wake")
    assert "written 7 days ago" in text and STALE in text and "may no longer be true" in STALE
    assert text.index("Steady. Eating well.") < text.index(STALE) < text.index("NOW:")
    clock.forward(days=30)
    assert "written 37 days ago" in call("weather") and STALE in call("weather")
    call("weather", words="New and fresh.")
    assert STALE not in call("wake") and "Steady. Eating well." not in call("wake")


# ---- promises -----------------------------------------------------------

def test_a_promise_stays_at_every_wake_until_settled(mind, clock):
    promise = mind.keep("promise", "I will ask how the appointment went.")
    guess = mind.keep("guess", "The appointment is on Friday.")
    for _ in range(3):
        clock.forward(days=60)
        for n in range(30):
            mind.keep("note", f"filler {n}")
        text = wake_text(mind)
        promises = text[text.index("PROMISES I MADE"):text.index("WHAT HAS MOVED LATELY")]
        guesses = text[text.index("OPEN GUESSES"):]
        assert "I will ask how the appointment went." in promises and "appointment is on Friday" not in promises
        assert "The appointment is on Friday." in guesses and "I will ask" not in guesses
    with pytest.raises(ValueError, match="A promise is settled as: done, or let go"):
        mind.settle(promise, "held")
    with pytest.raises(ValueError, match="A guess is settled as"):
        mind.settle(guess, "done")
    assert mind.settle(promise, "Done") == "done" and mind.get(promise)["state"] == "done"
    assert "PROMISES I MADE" not in wake_text(mind) and "I will ask" not in wake_text(mind)
    assert "settled: done" in show_line(mind.get(promise), mind.now())
    other = mind.keep("promise", "I will find that poem.")
    mind.settle(other, "let go")
    assert mind.current("promise") == []


# ---- dates --------------------------------------------------------------

def test_dates_show_today_and_the_next_14_days(mind, clock):
    mind.date_add("Robin's birthday", "03-10")
    mind.date_add("Dentist", "2026-03-12 15:30")
    mind.date_add("Edge of the window", "2026-03-24")
    mind.date_add("Just outside", "2026-03-25")
    mind.date_add("Long past", "2025-01-01")
    mind.date_add("Anniversary", "2019-03-11", yearly=True)
    text = wake_text(mind)
    section = text[text.index("DATES (today and the next 14 days)"):text.index("NOW:")]
    assert section.splitlines()[1:] == [
        "- TODAY, Tue 10 Mar: Robin's birthday (10 March, every year)",
        "- tomorrow, Wed 11 Mar: Anniversary (11 March, every year (since 2019))",
        "- in 2 days, Thu 12 Mar: Dentist (12 March 2026, 15:30)",
        "- in 14 days, Tue 24 Mar: Edge of the window (24 March 2026)", ""]
    listing = tools_for(mind)("dates")
    assert "Just outside (25 March 2026)" in listing and listing.index("Just outside") < listing.index("PAST")
    assert listing.rstrip().endswith("- Long past (1 January 2025)")


def test_a_yearly_date_rolls_over_the_end_of_the_year(mind, clock):
    mind.date_add("New year walk", "01-03")
    mind.date_add("Old one-off", "2026-01-02")
    mind.date_add("Leap day", "02-29")
    clock.t = datetime(2026, 12, 28, 12, 0, tzinfo=timezone.utc)
    assert "- in 6 days, Sun 3 Jan: New year walk (3 January, every year)" in wake_text(mind)
    assert "Old one-off" not in wake_text(mind)
    clock.t = datetime(2027, 1, 3, 12, 0, tzinfo=timezone.utc)
    assert "- TODAY, Sun 3 Jan: New year walk" in wake_text(mind)
    clock.t = datetime(2027, 1, 4, 12, 0, tzinfo=timezone.utc)
    assert "New year walk" not in wake_text(mind)                     # next one is a year away
    assert [(r["title"], days) for r, _, days in mind.dates_all()][:2] == [("Leap day", 55), ("New year walk", 364)]
    clock.t = datetime(2027, 2, 28, 12, 0, tzinfo=timezone.utc)       # 2027 has no 29 February
    assert "- TODAY, Sun 28 Feb: Leap day (29 February, every year)" in wake_text(mind)


def test_dates_refuse_what_they_cannot_read(mind):
    for bad in ("soon", "31 feb", "2027-02-29", "13-45", ""):
        with pytest.raises(ValueError, match="can't read"):
            mind.date_add("x", bad)
    with pytest.raises(ValueError, match="needs a year"):
        mind.date_add("x", "03-14", yearly=False)
    with pytest.raises(ValueError, match="needs a title"):
        mind.date_add(" ", "03-14")
    assert mind.dates_all() == [] and mind.date_delete(1) is False


# ---- cards with logs ----------------------------------------------------

LOG = ["08:10 gave 0.25 ml metacam (1.5 mg/ml), with food. Weight 4.35 kg.",
       "  Vet rang 14:05 – bloods: creatinine 212 µmol/L (ref 71–212); recheck in 6 wks.\n  NEXT DOSE ½ tablet, NOT a whole one!  ",
       "temp 38.9°C; ate ~40 g; 2x insulin 1.0 IU @ 07:30 & 19:30"]


def test_log_entries_come_back_unchanged_and_in_order(mind, clock):
    call = tools_for(mind)
    assert call("card", name="Pip", words="A small grey cat, fourteen.", kind="animal") == "Added to the card for Pip (animal) as #1."
    for entry in LOG:
        clock.forward(hours=3)
        assert "exactly as written" in call("log", card="pip", words=entry)
    card, about, log, total = mind.card_read("Pip")
    assert card["kind"] == "animal" and total == 3 and [l["words"] for l in log] == LOG
    read = call("card", name="PIP")
    assert read.startswith("Pip (animal)\n    #1 | Tue 10 Mar 2026") and "LOG (3 entries in all; showing all of them, oldest first" in read
    assert "not a medical or veterinary record" in read
    places = [read.index(entry) for entry in LOG]                   # every entry whole, byte for byte, oldest first
    assert places == sorted(places)
    assert f"#2 | Tue 10 Mar 2026 15:00 | {LOG[0]}\n#3 | Tue 10 Mar 2026 18:00 | {LOG[1]}\n#4 | Tue 10 Mar 2026 21:00 | {LOG[2]}" in read
    wake = call("wake")
    assert "CARDS TOUCHED LATELY\n- Pip (animal)" in wake and all(entry in wake for entry in LOG)


def test_log_refuses_an_unknown_card_and_never_makes_one_by_accident(mind):
    mind.card_add("Pip", "A cat.", "animal")
    with pytest.raises(ValueError, match="I don't have a card for Pipp. Cards I have: Pip."):
        mind.log_add("Pipp", "0.5 ml")
    assert [c["name"] for c in mind.card_names()] == ["Pip"]
    with pytest.raises(ValueError, match="kind is one of"):
        mind.card_add("Rex", "A dog.", "pet")
    with pytest.raises(ValueError, match="too long"):
        mind.log_add("Pip", "x" * 4001)          # refused whole, never cut short


def test_a_long_log_shows_the_newest_30_in_order_with_the_count_and_a_way_to_get_all(mind, clock):
    mind.card_add("Pip", "A cat.", "animal")
    entries = [f"day {n}: {n * 0.05:.2f} ml, weight {4.0 + n / 100:.2f} kg" for n in range(45)]
    for entry in entries:
        clock.forward(hours=12)
        mind.log_add("Pip", entry)
    _, _, log, total = mind.card_read("Pip")
    assert total == 45 and [l["words"] for l in log] == entries[-30:]
    read = card_text(mind, "Pip")
    assert "LOG (45 entries in all; showing the newest 30, oldest first" in read
    assert "(15 older entries are not shown. card(name, whole_log=true) gives every one.)" in read
    assert "day 14:" not in read and read.index("day 15:") < read.index("day 44:")
    whole = card_text(mind, "Pip", whole_log=True)
    assert "showing all of them" in whole and [whole.count(f"| {e}\n") + whole.endswith(f"| {e}") for e in entries] == [1] * 45
    big = "dose table\n" + "\n".join(f"{n:03d}  {n * 0.1:.1f} mg" for n in range(300))
    mind.log_add("Pip", big)
    assert big in card_text(mind, "Pip")           # a long entry is never truncated


def test_a_corrected_log_entry_stays_in_the_log_marked(mind):
    mind.card_add("Pip", "A cat.", "animal")
    wrong = mind.log_add("Pip", "gave 2.5 ml")
    mind.log_add("Pip", "ate well")
    right = mind.correct(wrong, "gave 0.25 ml", "decimal point in the wrong place")
    read = card_text(mind, "Pip")
    assert f"#{wrong} | Tue 10 Mar 2026 12:00 | CORRECTED, THE CURRENT WORDING IS #{right} | gave 2.5 ml" in read
    assert f"#{right} | Tue 10 Mar 2026 12:00 | corrects #{wrong} because: decimal point in the wrong place | gave 0.25 ml" in read
    assert read.index("gave 2.5 ml") < read.index("ate well") < read.index("gave 0.25 ml")


def test_people_from_the_first_layout_are_carried_over_to_cards(tmp_path, clock):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""CREATE TABLE lines (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, words TEXT NOT NULL,
        sure TEXT, state TEXT NOT NULL DEFAULT 'current', person TEXT, tag TEXT, corrects INTEGER, corrected_by INTEGER, why TEXT, settled_at TEXT);
        CREATE VIRTUAL TABLE lines_fts USING fts5(words, person);
        INSERT INTO lines (at, kind, words, person) VALUES ('2026-01-01T10:00:00+00:00', 'person', 'Old friend.', 'Robin');
        INSERT INTO lines (at, kind, words) VALUES ('2026-01-01T10:00:00+00:00', 'note', 'A note.');""")
    old.commit(); old.close()
    mind = Mind(path, now=clock)
    card, about, _, _ = mind.card_read("robin")
    assert (card["name"], card["kind"], about[0]["words"]) == ("Robin", "person", "Old friend.")
    assert [r["words"] for r in mind.recall("friend")[0]] == ["Old friend."]


# ---- wake, whole --------------------------------------------------------

def test_wake_order_and_no_empty_sections(mind, clock):
    mind.keep("note", "only a note")
    text = wake_text(mind)
    assert [l for l in text.splitlines() if l.isupper() or l.startswith(("WHAT", "NOW"))][0].startswith("WHAT HAS MOVED LATELY")
    for heading in ("HOW MY HUMAN IS", "WHO I AM", "OURS", "TAUGHT", "PROMISES", "DATES", "THEIR WORDS", "OPEN GUESSES", "CARDS", "FROM BEFORE", "(nothing"):
        assert heading not in text

    mind.weather("Doing all right.")
    mind.me_add("I am steady.")
    mind.ours_write("Our signal", "If I say 'harbour', we stop and rest.")
    mind.keep("taught", "Ask before giving advice.")
    mind.keep("promise", "I will ask about Friday.")
    mind.date_add("Dentist", "2026-03-12 15:30")
    mind.keep("said", "I just need you to stay.")
    mind.keep("guess", "Friday is the hard part.")
    mind.card_add("Pip", "A cat.", "animal")
    mind.pour("An old summary.")
    text = wake_text(mind)
    order = [text.index(h) for h in ("HOW MY HUMAN IS", "WHO I AM", "OURS (", "TAUGHT (", "PROMISES I MADE", "DATES (", "WHAT HAS MOVED LATELY",
                                     "THEIR WORDS (", "OPEN GUESSES", "CARDS TOUCHED LATELY", "FROM BEFORE (", "NOW: ")]
    assert order == sorted(order) and order[0] == 0
    assert "\n\n\n" not in text


def test_what_the_human_corrects_is_not_listed_as_new_from_the_companion(mind, clock):
    first = mind.keep("note", "wrong")
    mind.pour("old summary")
    stamp = mind.now().isoformat(timespec="seconds")
    clock.forward(minutes=5)
    kept = mind.keep("happened", "something new")
    mind.correct(first, "right", BY_HUMAN)
    assert [r["id"] for r in mind.since(stamp)] == [kept]
    assert [r["id"] for r in mind.since("")] == [kept, first]      # not the poured-in line, not the human's own correction
    assert mind.setting("names") == "" and mind.setting("names", "Robin, Rob") == "Robin, Rob" and mind.setting("names") == "Robin, Rob"
