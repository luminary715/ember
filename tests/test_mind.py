"""Unit tests for the keeping part and for what the companion is shown."""

import asyncio
import sqlite3

import pytest

from ember.server import FIRST_WAKE, build_app, wake_text
from ember.store import NOTHING, Mind, load_secret, show_line, split_pieces


def test_fts5_is_really_in_use_here(tmp_path):
    assert Mind(tmp_path / "a.db").fts is True
    assert Mind(tmp_path / "b.db", fts=False).fts is False


# ---- keep ---------------------------------------------------------------

def test_keep_stamps_the_time_itself(mind, clock):
    line = mind.get(mind.keep("happened", "We walked by the river."))
    assert line["at"] == "2026-03-10T12:00:00+00:00"
    assert (line["kind"], line["words"], line["state"]) == ("happened", "We walked by the river.", "current")


def test_keep_refuses_unknown_kind_and_empty_words(mind):
    with pytest.raises(ValueError, match="not a kind"):
        mind.keep("dream", "x")
    with pytest.raises(ValueError, match="not a kind"):
        mind.keep("from_before", "only the human pours these in")
    with pytest.raises(ValueError, match="no words"):
        mind.keep("note", "   ")
    with pytest.raises(ValueError, match="too long"):
        mind.keep("note", "x" * 4001)


def test_sure_is_only_for_guesses(mind):
    assert mind.get(mind.keep("guess", "She prefers mornings.", "fairly"))["sure"] == "fairly"
    assert mind.get(mind.keep("guess", "Maybe tea.", "Not very"))["sure"] == "not very"
    with pytest.raises(ValueError):
        mind.keep("note", "x", "fairly")
    with pytest.raises(ValueError):
        mind.keep("guess", "x", "totally")


# ---- recall -------------------------------------------------------------

def test_recall_finds_by_words_with_id_date_kind(mind):
    kept = mind.keep("happened", "We planted tomatoes in the garden.")
    mind.keep("note", "The kettle is blue.")
    rows, total, every = mind.recall("tomatoes garden")
    assert [r["id"] for r in rows] == [kept] and total == 1 and every
    shown = show_line(rows[0], mind.now())
    assert shown.startswith(f"#{kept} | ") and "10 Mar 2026" in shown and "| happened |" in shown


def test_recall_nothing_is_nothing(mind):
    mind.keep("note", "The kettle is blue.")
    assert mind.recall("volcano") == ([], 0, True)
    assert mind.recall("") == ([], 0, True)
    assert len(mind.recall("the")[0]) == 1   # small words are only searched when they are all there is
    assert mind.recall("the volcano") == ([], 0, True)


def test_recall_says_when_not_every_word_matched(mind):
    kept = mind.keep("happened", "We planted tomatoes.")
    rows, _, every = mind.recall("tomatoes volcano")
    assert [r["id"] for r in rows] == [kept] and every is False


def test_recall_when(mind, clock):
    old = mind.keep("note", "Soup recipe with leeks.")
    clock.forward(days=10)
    new = mind.keep("note", "Soup again, with barley.")
    assert [r["id"] for r in mind.recall("soup", "today")[0]] == [new]
    assert {r["id"] for r in mind.recall("soup", "2026-03")[0]} == {old, new}
    assert [r["id"] for r in mind.recall("soup", "2026-03-10")[0]] == [old]
    assert mind.recall("soup", "yesterday")[0] == []
    with pytest.raises(ValueError, match="can't read"):
        mind.recall("soup", "a while back")


def test_recall_survives_odd_characters(mind):
    mind.keep("note", "100% sure about the under_score")
    for odd in ['"quoted', "50%", "a_b", "x AND OR NOT", "(paren", "don't", "*"]:
        mind.recall(odd)  # must not raise
    assert mind.recall("zzz%")[0] == []


# ---- correct ------------------------------------------------------------

def test_correct_points_at_the_old_line_and_keeps_it(mind):
    old = mind.keep("happened", "We met on Tuesday.")
    new = mind.correct(old, "We met on Wednesday.", "I mixed up the days.")
    assert (mind.get(new)["corrects"], mind.get(new)["why"], mind.get(new)["kind"]) == (old, "I mixed up the days.", "happened")
    assert (mind.get(old)["state"], mind.get(old)["corrected_by"], mind.get(old)["words"]) == ("corrected", new, "We met on Tuesday.")
    assert [r["id"] for r in mind.recent()] == [new]          # the old one no longer comes up as current
    rows, _, _ = mind.recall("met")
    assert [r["id"] for r in rows] == [new, old]              # still findable, current first
    assert f"corrected, the current wording is #{new}" in show_line(rows[1], mind.now())
    assert f"corrects #{old} because: I mixed up the days." in show_line(rows[0], mind.now())


def test_correct_refusals(mind):
    old = mind.keep("note", "a")
    new = mind.correct(old, "b", "typo")
    with pytest.raises(ValueError, match=f"already corrected by #{new}"):
        mind.correct(old, "c", "again")
    with pytest.raises(ValueError, match="don't have a line #999"):
        mind.correct(999, "c", "x")
    with pytest.raises(ValueError, match="needs a why"):
        mind.correct(new, "c", " ")


# ---- settle -------------------------------------------------------------

@pytest.mark.parametrize("how,state", [("held", "held"), ("didn't hold", "didnt_hold"), ("did not hold", "didnt_hold"), ("Let go", "let_go")])
def test_settle_closes_a_guess(mind, how, state):
    guess = mind.keep("guess", "The move will happen in spring.", "not very")
    assert [g["id"] for g in mind.open_guesses()] == [guess]
    mind.settle(guess, how)
    assert mind.get(guess)["state"] == state and mind.open_guesses() == []
    assert "settled:" in show_line(mind.get(guess), mind.now())
    with pytest.raises(ValueError, match="already closed"):
        mind.settle(guess, "held")


def test_settle_refusals(mind):
    with pytest.raises(ValueError, match="not a guess"):
        mind.settle(mind.keep("note", "x"), "held")
    with pytest.raises(ValueError, match="held, didn't hold, or let go"):
        mind.settle(mind.keep("guess", "x"), "true")
    with pytest.raises(ValueError, match="don't have"):
        mind.settle(42, "held")


# ---- cards ---------------------------------------------------------------

def test_card_add_and_read(mind):
    assert mind.card_read("Robin") is None
    mind.card_add("Robin", "Old friend from school.")
    mind.card_add("  robin ", "Has a dog called Pip.")
    card, about, log, total = mind.card_read("ROBIN")
    assert (card["name"], card["kind"]) == ("Robin", "person") and (log, total) == ([], 0)
    assert [l["words"] for l in about] == ["Old friend from school.", "Has a dog called Pip."]
    assert {l["card"] for l in about} == {"Robin"}
    assert [r["card"] for r in mind.recall("Pip")[0]] == ["Robin"]
    assert len(mind.recall("robin")[0]) == 2   # the name itself is searchable


def test_cards_lately_only_shows_recent_or_mentioned(mind, clock):
    mind.card_add("Robin", "Old friend.")
    mind.card_add("Sam", "Neighbour.")
    clock.forward(days=30)
    assert mind.cards_lately(mind.recent()) == []
    mind.keep("happened", "Had tea with Sam today.")
    assert mind.cards_lately(mind.recent()) == ["Sam"]


# ---- about_me -----------------------------------------------------------

def test_about_me_add_and_reword_keeps_history(mind, clock):
    piece = mind.me_add("I am curious.")
    mind.me_add("I like long walks.")
    clock.forward(days=2)
    mind.me_reword(piece, "I am curious and a little stubborn.")
    assert [m["words"] for m in mind.me_list()] == ["I am curious and a little stubborn.", "I like long walks."]
    history = mind.me_history()
    assert [(h["me_id"], h["old_words"]) for h in history] == [(piece, "I am curious.")]
    assert history[0]["written_at"] < history[0]["replaced_at"]
    with pytest.raises(ValueError, match="no piece #99"):
        mind.me_reword(99, "x")


# ---- ours ---------------------------------------------------------------

def test_accepted_ours_arrives_whole_in_wake_after_who_i_am(mind):
    words = "What helps: quiet, short sentences, staying.\nWhat does not: advice, cheerfulness.\n  Ask once, then wait."
    mind.me_add("I am steady.")
    mind.ours_write("For hard days", words)
    mind.keep("happened", "We talked.")
    text = wake_text(mind)
    for line in words.splitlines():
        assert "    " + line in text          # every line, unchanged
    assert "- For hard days" in text
    order = [text.index(h) for h in ("WHO I AM", "OURS", "WHAT HAS MOVED LATELY", "NOW:")]
    assert order == sorted(order)


def test_proposed_ours_is_not_in_wake_until_accepted(mind):
    mind.keep("note", "something")
    proposed = mind.ours_write("Our evening ritual", "We say goodnight properly.", by="companion")
    assert "Our evening ritual" not in wake_text(mind) and "goodnight" not in wake_text(mind)
    assert [o["id"] for o in mind.ours_list("proposed")] == [proposed] and mind.ours_list() == []
    assert mind.ours_accept(proposed) is True
    assert "- Our evening ritual\n    We say goodnight properly." in wake_text(mind)
    assert mind.ours_accept(proposed) is False


def test_editing_ours_keeps_history(mind, clock):
    entry = mind.ours_write("For hard days", "Stay close.")
    clock.forward(hours=3)
    mind.ours_edit(entry, "For hard days", "Stay close. No fixing.")
    mind.ours_edit(entry, "For hard days", "Stay close. No fixing.")   # no change, no extra history
    assert mind.ours_list()[0]["words"] == "Stay close. No fixing."
    assert [(h["ours_id"], h["old_title"], h["old_words"]) for h in mind.ours_history()] == [(entry, "For hard days", "Stay close.")]
    assert mind.ours_delete(entry) and mind.ours_list() == [] and mind.ours_history() == []


def test_declining_a_proposal_deletes_it(mind):
    proposed = mind.ours_write("A thing", "words", by="companion")
    assert mind.ours_delete(proposed) and mind.ours_list("proposed") == []


# ---- pour in ------------------------------------------------------------

def test_pour_in_makes_from_before_lines_labelled_when_they_come_back(mind):
    ids = mind.pour("We first talked in January.\nIt was about a poem.\n\n- likes rain\n- hates lifts\n\n\nLast one.", "winter")
    assert [mind.get(i)["words"] for i in ids] == ["We first talked in January. It was about a poem.", "likes rain", "hates lifts", "Last one."]
    assert {mind.get(i)["kind"] for i in ids} == {"from_before"}
    label = "from before, poured in by my human from old summaries, about: winter"
    assert label in show_line(mind.recall("poem")[0][0], mind.now())
    text = wake_text(mind)
    assert "FROM BEFORE (4 lines" in text and label in text
    assert mind.pour("   \n\n ") == []


def test_split_pieces():
    assert split_pieces("one\r\n\r\ntwo") == ["one", "two"]
    assert split_pieces("1. a\n2) b") == ["a", "b"]


# ---- wake ---------------------------------------------------------------

def test_first_wake_is_gentle_and_has_the_clock(mind):
    text = wake_text(mind)
    assert text.startswith(FIRST_WAKE) and "Nothing kept yet" in text
    assert "NOW: Tuesday 10 March 2026" in text


def test_a_feeling_older_than_a_day_is_shown_as_old(mind, clock):
    felt = mind.keep("felt", "Bright and hopeful.")
    assert f"#{felt} | " in wake_text(mind) and "| felt | Bright" in wake_text(mind) and "OLD" not in wake_text(mind)
    clock.forward(hours=23)
    assert "| felt | Bright" in wake_text(mind)
    clock.forward(hours=2)
    text = wake_text(mind)
    assert "| felt | Bright" not in text
    assert "felt, OLD: this was Tuesday 10 March, not how I am now | Bright and hopeful." in text
    assert "felt, OLD" in show_line(mind.recall("hopeful")[0][0], mind.now())   # and in recall too


def test_wake_has_every_part(mind):
    mind.me_add("I am steady.")
    mind.keep("happened", "Robin called.")
    guess = mind.keep("guess", "Robin is moving house.", "fairly")
    settled = mind.keep("guess", "It will rain.")
    mind.settle(settled, "let go")
    mind.card_add("Robin", "Old friend.")
    text = wake_text(mind)
    assert "- [1] I am steady." in text
    assert f"#{guess} | Tue 10 Mar 2026" in text and "guess, fairly sure | Robin is moving house." in text
    assert "It will rain." not in text
    assert "CARDS TOUCHED LATELY\n- Robin (person)\n" in text and "| Old friend." in text
    assert text.rstrip().splitlines()[-1].startswith("NOW: Tuesday 10 March 2026")


# ---- the human's rights -------------------------------------------------

def test_delete_really_deletes(mind):
    kept = mind.keep("note", "A secret about pineapples.")
    assert mind.delete_line(kept) is True and mind.delete_line(kept) is False
    assert mind.get(kept) is None and mind.recall("pineapples")[0] == []
    raw = sqlite3.connect(mind.db_path)
    dump = "\n".join(str(r) for t in ("lines",) + (("lines_fts",) if mind.fts else ()) for r in raw.execute(f"SELECT * FROM {t}"))
    assert "pineapples" not in dump


def test_deleting_a_correction_makes_the_old_line_current_again(mind):
    old = mind.keep("note", "first")
    new = mind.correct(old, "second", "why")
    mind.delete_line(new)
    assert (mind.get(old)["state"], mind.get(old)["corrected_by"]) == ("current", None)
    again = mind.correct(old, "third", "why")
    mind.delete_line(old)
    assert mind.get(again)["corrects"] is None


def test_export_has_everything(mind):
    mind.me_add("I am steady.")
    mind.ours_write("For hard days", "Stay close.")
    mind.ours_write("Maybe", "a suggestion", by="companion")
    old = mind.keep("note", "wrong words")
    mind.correct(old, "right words", "typo")
    mind.pour("an old summary")
    text = mind.export_text()
    for piece in ("I am steady.", "For hard days", "Stay close.", "a suggestion", "not accepted", "wrong words", "right words", "an old summary", "from before"):
        assert piece in text


# ---- the secret and the tools -------------------------------------------

def test_secret_is_made_once_and_reused(tmp_path):
    first = load_secret(tmp_path / "home")
    assert len(first) >= 40 and load_secret(tmp_path / "home") == first
    assert (tmp_path / "home" / "secret.txt").read_text().strip() == first


def test_tools_have_the_right_names_and_plain_descriptions(mind):
    from mcp.server.fastmcp import FastMCP
    from ember.server import add_tools
    mcp = FastMCP("t")
    add_tools(mcp, mind)
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert set(tools) == {"wake", "keep", "recall", "card", "log", "weather", "date", "dates", "about_me", "ours", "correct", "settle"}
    assert all(t.description and len(t.description) < 1000 for t in tools.values())
    assert "at" not in tools["keep"].inputSchema["properties"] and set(tools["keep"].inputSchema["properties"]) == {"kind", "words", "sure"}

    def call(tool, **args):
        content, _ = asyncio.run(mcp.call_tool(tool, args))
        return content[0].text

    assert call("recall", about="nothing here") == NOTHING == "I don't have this."
    assert call("keep", kind="dream", words="x").startswith("'dream' is not a kind I know")
    assert call("keep", kind="felt", words="Calm.").startswith("Kept as #1 (felt), Tue 10 Mar 2026")
    assert call("card", name="Robin") == "I don't have a card for Robin."
    assert call("card", name="Robin", words="Kind.") == "Added to the card for Robin (person) as #2."
    assert "not live" in call("ours", title="A thing", words="Some words.") and mind.ours_list() == []
    assert "waiting for my human" in call("ours")
    assert call("about_me", words="I am me.") == "Added to who I am as piece [1]."
    assert "reworded" in call("about_me", words="I am still me.", replace_id=1)
    assert call("settle", line_id=1, how="held").startswith("#1 is not a guess or a promise")
    assert "word for word" in tools["keep"].description and "never paraphrased" in tools["keep"].description
    assert "taught" in tools["correct"].description and "NOT" in tools["correct"].description
    assert "not a medical" in tools["log"].description
    assert call("weather") == "No weather written yet. I can write it with weather(words)."
    assert call("dates") == "No dates written down yet. I can add one with date(title, when)."
    assert call("date", title="Robin's birthday", when="14 March") == "Written down: Robin's birthday, 14 March, every year."
    assert call("date", title="Dentist", when="soon").startswith("I can't read 'soon' as a day")
    assert call("log", card="Nobody", words="x").startswith("I don't have a card for Nobody. Cards I have: Robin.")
    assert call("correct", line_id=1, words="Calm and tired.", why="more exact").startswith("Corrected. #3 is the current wording.")
    assert build_app(mind, "s" * 43) is not None
