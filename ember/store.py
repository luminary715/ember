"""The keeping part of Ember, a small mind: one SQLite file and plain functions.

Nothing here knows about MCP or web pages. The tools (server.py) and the
look page (look.py) both call into this file.

Every line is stamped by this computer's clock. Nobody passes a time in.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KINDS = ("happened", "felt", "guess", "note", "said", "taught", "promise")  # what the companion may keep
FROM_BEFORE = "from_before"  # poured in by the human from old summaries
CARD = "card"        # a line describing who or what a card is about
LOG = "log"          # a dated entry in a card's log, kept exactly as written
WEATHER = "weather"  # how the human is doing right now: one current, the rest history
VERBATIM = ("said", LOG)  # kept exactly as given: not trimmed, not tidied
CARD_KINDS = ("person", "animal", "other")
SURE = ("fairly", "not very")
SETTLED = {"guess": {"held": "held", "didn't hold": "didnt_hold", "let go": "let_go"},
           "promise": {"done": "done", "let go": "let_go"}}
STALE_DAYS = 7       # weather older than this is said to be stale
SOON_DAYS = 14       # how far ahead wake looks for dates
LOG_SHOWN = 30       # how many log entries a card shows unless asked for all
MONTHS = "january february march april may june july august september october november december".split()
MAX_WORDS = 4000
BY_HUMAN = "corrected by my human on their own page"
NOTHING = "I don't have this."

SCHEMA = """
CREATE TABLE IF NOT EXISTS lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL,              -- when it was kept (UTC)
    kind          TEXT NOT NULL,              -- happened felt guess note said taught promise from_before card log weather
    words         TEXT NOT NULL,
    sure          TEXT,                       -- guesses only: fairly / not very
    state         TEXT NOT NULL DEFAULT 'current',  -- current corrected held didnt_hold done let_go replaced
    card          TEXT,                       -- card and log lines only: the card's name
    tag           TEXT,                       -- from_before only: "about when", in the human's words
    corrects      INTEGER,                    -- the id of the line this one corrects
    corrected_by  INTEGER,                    -- the id of the line that corrected this one
    why           TEXT,                       -- why it was corrected, or how a guess was settled
    settled_at    TEXT
);
CREATE TABLE IF NOT EXISTS cards (
    name  TEXT PRIMARY KEY COLLATE NOCASE,
    kind  TEXT NOT NULL DEFAULT 'person',     -- person animal other
    at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dates (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,                     -- when it was written down
    title  TEXT NOT NULL,
    year   INTEGER,                           -- one-offs have a year; yearly ones may (the first year)
    month  INTEGER NOT NULL,
    day    INTEGER NOT NULL,
    time   TEXT,                              -- HH:MM, for appointments
    yearly INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (         -- small things for the look page: the human's name, when they last looked
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS me (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    at    TEXT NOT NULL,
    words TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ours (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    at    TEXT NOT NULL,
    title TEXT NOT NULL,
    words TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'accepted',   -- accepted, or proposed (suggested by the companion, not live)
    by    TEXT NOT NULL DEFAULT 'human'       -- who first wrote it: human or companion
);
CREATE TABLE IF NOT EXISTS ours_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ours_id     INTEGER NOT NULL,
    old_title   TEXT NOT NULL,
    old_words   TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    replaced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS me_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    me_id       INTEGER NOT NULL,
    old_words   TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    replaced_at TEXT NOT NULL
);
"""

STOP = set("a an and are as at be but by for from had has have he her his i in is it me my of on or our "
           "she so that the their them they this to was we were what when who with you your".split())


def data_dir() -> Path:
    """Where the mind lives. ~/.ember unless EMBER_HOME says otherwise."""
    return Path(os.environ.get("EMBER_HOME") or Path.home() / ".ember")


def load_secret(folder: Path) -> str:
    """The long random piece of the address. Made on first run, then reused."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        folder.chmod(0o700)  # other accounts on this computer cannot look inside
    except OSError:
        pass
    path = folder / "secret.txt"
    if path.exists() and len(path.read_text().strip()) >= 32:
        return path.read_text().strip()
    secret = secrets.token_urlsafe(32)
    path.write_text(secret + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows: the file sits in the user's own profile folder
    return secret


class Mind:
    def __init__(self, db_path: Path | str, now=None, fts: bool = True):
        self.db_path = str(db_path)
        self._now = now or (lambda: datetime.now(timezone.utc))
        with self._db() as db:
            self._from_first_layout(db)
            db.executescript(SCHEMA)
            self.fts = fts and self._make_fts(db)

    # ---- plumbing -------------------------------------------------------

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    @staticmethod
    def _from_first_layout(db) -> None:
        """The first version kept people as 'person' lines. Carry those over to cards."""
        columns = [r[1] for r in db.execute("PRAGMA table_info(lines)")]
        if "person" not in columns:
            return
        db.execute("ALTER TABLE lines RENAME COLUMN person TO card")
        db.execute("UPDATE lines SET kind = 'card' WHERE kind = 'person'")
        db.execute("DROP TABLE IF EXISTS lines_fts")
        db.execute("CREATE TABLE IF NOT EXISTS cards (name TEXT PRIMARY KEY COLLATE NOCASE, kind TEXT NOT NULL DEFAULT 'person', at TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO cards (name, kind, at) SELECT card, 'person', min(at) FROM lines WHERE kind = 'card' GROUP BY lower(card)")

    def _make_fts(self, db) -> bool:
        try:
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS lines_fts USING fts5(words, card)")
        except sqlite3.OperationalError:
            return False  # this SQLite has no FTS5: recall falls back to LIKE
        have = db.execute("SELECT count(*) FROM lines_fts").fetchone()[0]
        want = db.execute("SELECT count(*) FROM lines").fetchone()[0]
        if have != want:
            db.execute("DELETE FROM lines_fts")
            db.execute("INSERT INTO lines_fts(rowid, words, card) SELECT id, words, coalesce(card,'') FROM lines")
        return True

    def now(self) -> datetime:
        return self._now().astimezone(timezone.utc)

    def _insert(self, db, kind, words, **more) -> int:
        cols = {"at": self.now().isoformat(timespec="seconds"), "kind": kind, "words": words, **more}
        marks = ", ".join("?" for _ in cols)
        cur = db.execute(f"INSERT INTO lines ({', '.join(cols)}) VALUES ({marks})", list(cols.values()))
        if self.fts:
            db.execute("INSERT INTO lines_fts(rowid, words, card) VALUES (?, ?, ?)",
                       (cur.lastrowid, words, more.get("card") or ""))
        return cur.lastrowid

    @staticmethod
    def _clean(words, kind: str = "") -> str:
        """Trim the words. Quotes and log entries are NOT trimmed: they are kept exactly as given."""
        words = words or ""
        if not words.strip():
            raise ValueError("There are no words here to keep.")
        if kind not in VERBATIM:
            words = words.strip()
        if len(words) > MAX_WORDS:
            raise ValueError(f"That is too long for one line ({len(words)} characters, the most is {MAX_WORDS}). Keep it in smaller pieces.")
        return words

    def get(self, line_id: int):
        with self._db() as db:
            return db.execute("SELECT * FROM lines WHERE id = ?", (line_id,)).fetchone()

    def setting(self, key: str, value: str | None = None) -> str:
        """Read a small setting, or write it when a value is given."""
        with self._db() as db:
            if value is not None:
                db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
                return value
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else ""

    # ---- keeping --------------------------------------------------------

    def keep(self, kind: str, words: str, sure: str | None = None) -> int:
        kind = (kind or "").strip().lower()
        if kind not in KINDS:
            raise ValueError(f"'{kind}' is not a kind I know. The kinds are: {', '.join(KINDS)}.")
        words = self._clean(words, kind)
        sure = (sure or "").strip().lower() or None
        if sure and kind != "guess":
            raise ValueError("Only a guess can carry 'sure'.")
        if sure and sure not in SURE:
            raise ValueError("'sure' is either 'fairly' or 'not very'.")
        with self._db() as db:
            return self._insert(db, kind, words, sure=sure)

    def pour(self, text: str, about_when: str | None = None) -> list[int]:
        """Take the human's old summaries and keep each piece as a from_before line."""
        tag = (about_when or "").strip()[:80] or None
        ids = []
        with self._db() as db:
            for piece in split_pieces(text):
                for start in range(0, len(piece), MAX_WORDS):
                    ids.append(self._insert(db, FROM_BEFORE, piece[start:start + MAX_WORDS], tag=tag))
        return ids

    def weather(self, words: str) -> int:
        """Write how the human is doing now. It replaces the one before, which is kept as history."""
        words = self._clean(words)
        with self._db() as db:
            db.execute("UPDATE lines SET state = 'replaced' WHERE kind = 'weather' AND state = 'current'")
            return self._insert(db, WEATHER, words)

    def weather_now(self):
        with self._db() as db:
            return db.execute("SELECT * FROM lines WHERE kind = 'weather' AND state = 'current' ORDER BY id DESC LIMIT 1").fetchone()

    def correct(self, line_id: int, words: str, why: str) -> int:
        why = (why or "").strip()
        if not why:
            raise ValueError("A correction needs a why, even a short one.")
        with self._db() as db:
            old = db.execute("SELECT * FROM lines WHERE id = ?", (line_id,)).fetchone()
            if not old:
                raise ValueError(f"I don't have a line #{line_id}.")
            if old["corrected_by"]:
                raise ValueError(f"#{line_id} was already corrected by #{old['corrected_by']}. Correct #{old['corrected_by']} instead.")
            if old["state"] == "replaced":
                raise ValueError(f"#{line_id} is an old weather. Write a new weather instead.")
            new = self._insert(db, old["kind"], self._clean(words, old["kind"]), sure=old["sure"], card=old["card"],
                               tag=old["tag"], corrects=line_id, why=why,
                               **({} if old["state"] == "current" else {"state": old["state"], "settled_at": old["settled_at"]}))
            db.execute("UPDATE lines SET state = 'corrected', corrected_by = ? WHERE id = ?", (new, line_id))
            return new

    def settle(self, line_id: int, how: str) -> str:
        key = (how or "").strip().lower().replace("’", "'").replace("did not", "didn't").replace("didnt", "didn't")
        with self._db() as db:
            old = db.execute("SELECT * FROM lines WHERE id = ?", (line_id,)).fetchone()
            if not old:
                raise ValueError(f"I don't have a line #{line_id}.")
            if old["kind"] not in SETTLED:
                raise ValueError(f"#{line_id} is not a guess or a promise (it is '{old['kind']}'), so there is nothing to settle.")
            if key not in SETTLED[old["kind"]]:
                raise ValueError("A guess is settled as: held, didn't hold, or let go. A promise is settled as: done, or let go.")
            if old["state"] != "current":
                raise ValueError(f"#{line_id} is already closed ({state_words(old)}).")
            db.execute("UPDATE lines SET state = ?, settled_at = ? WHERE id = ?",
                       (SETTLED[old["kind"]][key], self.now().isoformat(timespec="seconds"), line_id))
        return key

    # ---- cards: people, animals, anything with a name --------------------

    def card_find(self, name: str):
        with self._db() as db:
            return db.execute("SELECT * FROM cards WHERE name = ?", (" ".join((name or "").split()),)).fetchone()

    def card_names(self) -> list:
        with self._db() as db:
            return db.execute("SELECT * FROM cards WHERE EXISTS (SELECT 1 FROM lines WHERE lines.card = cards.name COLLATE NOCASE) ORDER BY name").fetchall()

    def card_add(self, name: str, words: str, kind: str | None = None) -> int:
        """Add a describing line to a card. The first line makes the card."""
        name, kind = " ".join((name or "").split()), (kind or "").strip().lower() or None
        if not name:
            raise ValueError("A card needs a name.")
        if kind and kind not in CARD_KINDS:
            raise ValueError(f"A card's kind is one of: {', '.join(CARD_KINDS)}.")
        words = self._clean(words)
        known = self.card_find(name)
        with self._db() as db:
            if not known:
                db.execute("INSERT INTO cards (name, kind, at) VALUES (?, ?, ?)", (name, kind or "person", self.now().isoformat(timespec="seconds")))
            elif kind and kind != known["kind"]:
                db.execute("UPDATE cards SET kind = ? WHERE name = ?", (kind, name))
            return self._insert(db, CARD, words, card=known["name"] if known else name)

    def log_add(self, name: str, words: str) -> int:
        """Add a dated entry to a card's log, exactly as written. The card must already be there."""
        known = self.card_find(name)
        if not known:
            have = ", ".join(c["name"] for c in self.card_names()) or "none yet"
            raise ValueError(f"I don't have a card for {' '.join((name or '').split())}. Cards I have: {have}. "
                             "Make the card first with card(name, words, kind), then log to it.")
        with self._db() as db:
            return self._insert(db, LOG, self._clean(words, LOG), card=known["name"])

    def card_read(self, name: str, whole_log: bool = False):
        """(card, describing lines, log entries oldest first, how many log entries in all). None if there is no card."""
        known = self.card_find(name)
        if not known:
            return None
        with self._db() as db:
            about = db.execute("SELECT * FROM lines WHERE kind = 'card' AND card = ? COLLATE NOCASE AND state = 'current' ORDER BY id", (known["name"],)).fetchall()
            log = db.execute("SELECT * FROM lines WHERE kind = 'log' AND card = ? COLLATE NOCASE ORDER BY id", (known["name"],)).fetchall()
        if not about and not log:
            return None
        return known, about, (log if whole_log else log[-LOG_SHOWN:]), len(log)

    def cards_lately(self, recent_lines, days: int = 14) -> list:
        """Cards named in the recent lines, or that were written on lately."""
        since = (self.now() - timedelta(days=days)).isoformat(timespec="seconds")
        text = " ".join(r["words"] for r in recent_lines).lower()
        with self._db() as db:
            touched = {r[0].lower() for r in db.execute("SELECT DISTINCT card FROM lines WHERE card IS NOT NULL AND at >= ?", (since,))}
        return [c["name"] for c in self.card_names()
                if c["name"].lower() in touched or re.search(rf"\b{re.escape(c['name'].lower())}\b", text)]

    # ---- dates: days that matter ------------------------------------------

    def date_add(self, title: str, when: str, yearly: bool | None = None) -> int:
        title = " ".join((title or "").split())[:200]
        if not title:
            raise ValueError("A date needs a title.")
        year, month, day, time = read_day(when)
        if year is None and yearly is False:
            raise ValueError("A one-off date needs a year, like 2027-03-14.")
        with self._db() as db:
            return db.execute("INSERT INTO dates (at, title, year, month, day, time, yearly) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (self.now().isoformat(timespec="seconds"), title, year, month, day, time,
                               int(year is None or bool(yearly)))).lastrowid

    def dates_all(self) -> list[tuple]:
        """Every date as (row, the day it next falls on, days from today). Coming ones first, past one-offs last."""
        today = self.now().astimezone().date()
        with self._db() as db:
            rows = db.execute("SELECT * FROM dates ORDER BY id").fetchall()
        found = [(r, falls := next_day(r, today), (falls - today).days) for r in rows]
        return sorted(found, key=lambda f: (f[2] < 0, abs(f[2]), f[0]["time"] or "", f[0]["id"]))

    def dates_soon(self) -> list[tuple]:
        return [f for f in self.dates_all() if 0 <= f[2] <= SOON_DAYS]

    def date_delete(self, date_id: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM dates WHERE id = ?", (date_id,)).rowcount > 0

    # ---- the steady part ------------------------------------------------

    def me_list(self) -> list:
        with self._db() as db:
            return db.execute("SELECT * FROM me ORDER BY id").fetchall()

    def me_add(self, words: str) -> int:
        with self._db() as db:
            return db.execute("INSERT INTO me (at, words) VALUES (?, ?)",
                              (self.now().isoformat(timespec="seconds"), self._clean(words))).lastrowid

    def me_reword(self, me_id: int, words: str) -> None:
        words = self._clean(words)
        stamp = self.now().isoformat(timespec="seconds")
        with self._db() as db:
            old = db.execute("SELECT * FROM me WHERE id = ?", (me_id,)).fetchone()
            if not old:
                raise ValueError(f"There is no piece #{me_id} in my steady list.")
            db.execute("INSERT INTO me_history (me_id, old_words, written_at, replaced_at) VALUES (?, ?, ?, ?)",
                       (me_id, old["words"], old["at"], stamp))
            db.execute("UPDATE me SET words = ?, at = ? WHERE id = ?", (words, stamp, me_id))

    def me_history(self) -> list:
        with self._db() as db:
            return db.execute("SELECT * FROM me_history ORDER BY id").fetchall()

    # ---- ours: written together, never by the companion alone -----------

    def ours_list(self, state: str = "accepted") -> list:
        with self._db() as db:
            return db.execute("SELECT * FROM ours WHERE state = ? ORDER BY id", (state,)).fetchall()

    def ours_write(self, title: str, words: str, by: str = "human") -> int:
        """The human writes an entry (live at once). The companion can only propose one."""
        title = " ".join((title or "").split())[:120]
        if not title:
            raise ValueError("An entry in 'ours' needs a title.")
        state = "accepted" if by == "human" else "proposed"
        with self._db() as db:
            return db.execute("INSERT INTO ours (at, title, words, state, by) VALUES (?, ?, ?, ?, ?)",
                              (self.now().isoformat(timespec="seconds"), title, self._clean(words), state, by)).lastrowid

    def ours_edit(self, ours_id: int, title: str, words: str) -> None:
        title, words = " ".join((title or "").split())[:120], self._clean(words)
        if not title:
            raise ValueError("An entry in 'ours' needs a title.")
        stamp = self.now().isoformat(timespec="seconds")
        with self._db() as db:
            old = db.execute("SELECT * FROM ours WHERE id = ?", (ours_id,)).fetchone()
            if not old:
                raise ValueError(f"There is no entry #{ours_id} in 'ours'.")
            if (old["title"], old["words"]) == (title, words):
                return
            db.execute("INSERT INTO ours_history (ours_id, old_title, old_words, written_at, replaced_at) VALUES (?, ?, ?, ?, ?)",
                       (ours_id, old["title"], old["words"], old["at"], stamp))
            db.execute("UPDATE ours SET title = ?, words = ?, at = ? WHERE id = ?", (title, words, stamp, ours_id))

    def ours_accept(self, ours_id: int) -> bool:
        with self._db() as db:
            return db.execute("UPDATE ours SET state = 'accepted' WHERE id = ? AND state = 'proposed'", (ours_id,)).rowcount > 0

    def ours_delete(self, ours_id: int) -> bool:
        """Delete an entry, or decline a suggestion. Its earlier wordings go with it."""
        with self._db() as db:
            db.execute("DELETE FROM ours_history WHERE ours_id = ?", (ours_id,))
            return db.execute("DELETE FROM ours WHERE id = ?", (ours_id,)).rowcount > 0

    def ours_history_delete(self, history_id: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM ours_history WHERE id = ?", (history_id,)).rowcount > 0

    def ours_history(self) -> list:
        with self._db() as db:
            return db.execute("SELECT * FROM ours_history ORDER BY id").fetchall()

    # ---- reading back ---------------------------------------------------

    def recent(self, limit: int = 15) -> list:
        with self._db() as db:
            return db.execute("SELECT * FROM lines WHERE state = 'current' AND kind IN ('happened','felt','note') "
                              "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def current(self, kind: str, newest: int | None = None) -> list:
        """Every current line of one kind, oldest first. With newest=N, only the N newest (newest first).
        Used for: open guesses, open promises, everything taught, the shelf of quotes."""
        with self._db() as db:
            if newest:
                return db.execute("SELECT * FROM lines WHERE kind = ? AND state = 'current' ORDER BY id DESC LIMIT ?", (kind, newest)).fetchall()
            return db.execute("SELECT * FROM lines WHERE kind = ? AND state = 'current' ORDER BY id", (kind,)).fetchall()

    def open_guesses(self) -> list:
        return self.current("guess")

    def since(self, stamp: str) -> list:
        """Lines the companion wrote after this moment, newest first. For 'new since you last looked'."""
        with self._db() as db:
            return db.execute("SELECT * FROM lines WHERE at > ? AND kind != 'from_before' AND coalesce(why, '') != ? ORDER BY id DESC",
                              (stamp, BY_HUMAN)).fetchall()

    def from_before(self, limit: int = 20) -> tuple[list, int]:
        with self._db() as db:
            total = db.execute("SELECT count(*) FROM lines WHERE kind = 'from_before' AND state = 'current'").fetchone()[0]
            rows = db.execute("SELECT * FROM lines WHERE kind = 'from_before' AND state = 'current' ORDER BY id LIMIT ?", (limit,)).fetchall()
        return rows, total

    def is_empty(self) -> bool:
        with self._db() as db:
            return not db.execute("SELECT (SELECT count(*) FROM lines) + (SELECT count(*) FROM me) + (SELECT count(*) FROM dates) + (SELECT count(*) FROM ours WHERE state = 'accepted')").fetchone()[0]

    def all_lines(self) -> list:
        with self._db() as db:
            return db.execute("SELECT * FROM lines ORDER BY id DESC").fetchall()

    def recall(self, about: str, when: str | None = None, limit: int = 10) -> tuple[list, int, bool]:
        """Lines matching the words. Returns (lines, how many matched in all, every_word_matched)."""
        tokens = re.findall(r"\w+", (about or "").lower())
        strong = [t for t in tokens if t not in STOP] or tokens
        span = self.when_span(when) if (when or "").strip() else None
        for words, joiner in ((strong, "AND"), (strong, "OR")):
            if not words and not span:
                break
            ids = self._search(words, joiner, span)
            if ids:
                with self._db() as db:
                    marks = ",".join("?" for _ in ids[:limit])
                    rows = db.execute(f"SELECT * FROM lines WHERE id IN ({marks})", ids[:limit]).fetchall()
                order = {i: n for n, i in enumerate(ids)}
                rows.sort(key=lambda r: (r["state"] in ("corrected", "replaced"), order[r["id"]]))
                return rows, len(ids), joiner == "AND"
            if len(words) < 2:
                break
        return [], 0, True

    def _search(self, words, joiner, span) -> list[int]:
        where, args = [], []
        if span:
            where.append("l.at >= ? AND l.at < ?")
            args += [s.astimezone(timezone.utc).isoformat(timespec="seconds") for s in span]
        with self._db() as db:
            if words and self.fts:
                match = f" {joiner} ".join(f'"{w}"*' for w in words)
                sql = "SELECT l.id FROM lines_fts f JOIN lines l ON l.id = f.rowid WHERE lines_fts MATCH ?"
                sql += "".join(f" AND {w}" for w in where) + " ORDER BY bm25(lines_fts), l.id DESC"
                return [r[0] for r in db.execute(sql, [match] + args)]
            likes = [r"(lower(l.words) LIKE ? ESCAPE '\' OR lower(coalesce(l.card,'')) LIKE ? ESCAPE '\')" for _ in words]
            like_args = []
            for w in words:
                like_args += ["%" + w.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"] * 2
            parts = ([f"({f' {joiner} '.join(likes)})"] if likes else []) + where
            sql = "SELECT l.id FROM lines l WHERE " + " AND ".join(parts) + " ORDER BY l.id DESC"
            return [r[0] for r in db.execute(sql, like_args + args)]

    def when_span(self, when: str) -> tuple[datetime, datetime]:
        """Turn a plain 'when' into a start and end in local time."""
        w = " ".join(when.lower().split())
        today = self.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        day = timedelta(days=1)
        if w == "today":
            return today, today + day
        if w == "yesterday":
            return today - day, today
        if w == "this week":
            return today - day * today.weekday(), today + day
        if w == "last week":
            start = today - day * (today.weekday() + 7)
            return start, start + day * 7
        if w == "this month":
            return today.replace(day=1), today + day
        if m := re.fullmatch(r"(?:last |past )?(\d+) days?", w):
            return today - day * int(m[1]), today + day
        try:
            if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", w):
                start = today.replace(year=int(m[1]), month=int(m[2]), day=int(m[3]))
                return start, start + day
            if m := re.fullmatch(r"(\d{4})-(\d{2})", w):
                start = today.replace(year=int(m[1]), month=int(m[2]), day=1)
                return start, (start + day * 32).replace(day=1)
            if m := re.fullmatch(r"(\d{4})", w):
                start = today.replace(year=int(m[1]), month=1, day=1)
                return start, start.replace(year=start.year + 1)
        except ValueError:
            pass
        raise ValueError(f"I can't read '{when}' as a when. Use: today, yesterday, this week, last week, "
                         "this month, 7 days, 2026, 2026-03 or 2026-03-14.")

    # ---- the human's rights: delete and export --------------------------

    def delete_line(self, line_id: int) -> bool:
        """Really delete. If it was a correction, the line it corrected is current again."""
        with self._db() as db:
            row = db.execute("SELECT * FROM lines WHERE id = ?", (line_id,)).fetchone()
            if not row:
                return False
            if row["corrects"]:
                db.execute("UPDATE lines SET state = 'current', corrected_by = NULL WHERE id = ?", (row["corrects"],))
            db.execute("UPDATE lines SET corrects = NULL WHERE corrects = ?", (line_id,))
            db.execute("DELETE FROM lines WHERE id = ?", (line_id,))
            if self.fts:
                db.execute("DELETE FROM lines_fts WHERE rowid = ?", (line_id,))
        return True

    def delete_me(self, me_id: int) -> bool:
        with self._db() as db:
            db.execute("DELETE FROM me_history WHERE me_id = ?", (me_id,))
            return db.execute("DELETE FROM me WHERE id = ?", (me_id,)).rowcount > 0

    def delete_history(self, history_id: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM me_history WHERE id = ?", (history_id,)).rowcount > 0

    def export_text(self) -> str:
        out = ["EMBER: everything kept", f"Exported {long_date(self.now())}", ""]
        out += ["WHO I AM (the steady list, written by the companion)"]
        out += [f"  [{m['id']}] {m['words']}   (written {short_date(m['at'])})" for m in self.me_list()] or ["  (nothing)"]
        history = self.me_history()
        if history:
            out += ["", "EARLIER WORDINGS OF THE STEADY LIST"]
            out += [f"  piece [{h['me_id']}] used to say: {h['old_words']}   (until {short_date(h['replaced_at'])})" for h in history]
        out += ["", "OURS (written together)"]
        out += [f"  [{o['id']}] {o['title']}\n      {o['words']}" for o in self.ours_list()] or ["  (nothing)"]
        proposed = self.ours_list("proposed")
        if proposed:
            out += ["", "SUGGESTED FOR 'OURS' BY THE COMPANION (not accepted, not live)"]
            out += [f"  [{o['id']}] {o['title']}\n      {o['words']}" for o in proposed]
        if self.ours_history():
            out += ["", "EARLIER WORDINGS OF 'OURS'"]
            out += [f"  entry [{h['ours_id']}] used to say: {h['old_title']}: {h['old_words']}   (until {short_date(h['replaced_at'])})" for h in self.ours_history()]
        if self.dates_all():
            out += ["", "DATES"] + [f"  {date_words(r)}: {r['title']}" for r, _, _ in self.dates_all()]
        out += ["", "EVERY LINE, OLDEST FIRST"]
        rows = list(reversed(self.all_lines()))
        out += [f"  {show_line(r, self.now())}" for r in rows] or ["  (nothing)"]
        return "\n".join(out) + "\n"


# ---- how a line is shown, the same everywhere ---------------------------

def local(stamp) -> datetime:
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp)
    return stamp.astimezone()


def short_date(stamp) -> str:
    t = local(stamp)
    return f"{t:%a} {t.day} {t:%b %Y %H:%M}"


def long_date(stamp) -> str:
    t = local(stamp)
    return f"{t:%A} {t.day} {t:%B %Y}, {t:%H:%M}"


def state_words(row) -> str:
    return {"corrected": f"corrected, the current wording is #{row['corrected_by']}", "held": "settled: held",
            "didnt_hold": "settled: didn't hold", "let_go": "settled: let go", "done": "settled: done",
            "replaced": "an earlier weather, replaced since"}.get(row["state"], "")


def age_words(stamp: str, now: datetime) -> str:
    """How long ago, in plain words: 'written 4 days ago'."""
    age = now - datetime.fromisoformat(stamp)
    if age < timedelta(hours=1):
        return "written less than an hour ago"
    if age < timedelta(days=1):
        hours = int(age.total_seconds() // 3600)
        return f"written {hours} hour{'s' if hours != 1 else ''} ago"
    return f"written {age.days} day{'s' if age.days != 1 else ''} ago"


def is_stale(stamp: str, now: datetime) -> bool:
    return now - datetime.fromisoformat(stamp) > timedelta(days=STALE_DAYS)


def read_day(when: str) -> tuple:
    """Read a day someone wrote: 2027-03-14, 2027-03-14 15:30, 03-14, 14 March, March 14 2027.
    Gives (year or None, month, day, time or None)."""
    text = " ".join((when or "").lower().replace(",", " ").split())
    time = None
    if m := re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text):
        time = f"{int(m[1]):02d}:{m[2]}"
        text = " ".join(re.sub(r"\bat\b", " ", text[:m.start()].rstrip("t") + " " + text[m.end():]).split())
    year = month = day = None
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
        year, month, day = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"-{0,2}(\d{1,2})-(\d{1,2})", text):
        month, day = int(m[1]), int(m[2])
    elif (m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]+)(?: (\d{4}))?", text)) or \
         (m := re.fullmatch(r"(?P<mon>[a-z]+) (?P<d>\d{1,2})(?:st|nd|rd|th)?(?: (?P<y>\d{4}))?", text)):
        d, name, y = (m["d"], m["mon"], m["y"]) if "mon" in m.groupdict() else (m[1], m[2], m[3])
        hits = [i for i, full in enumerate(MONTHS, 1) if len(name) >= 3 and full.startswith(name)]
        if len(hits) == 1:
            year, month, day = int(y) if y else None, hits[0], int(d)
    try:
        datetime(year or 2000, month, day, *(map(int, time.split(":")) if time else ()))
    except (TypeError, ValueError):
        raise ValueError(f"I can't read '{when}' as a day. Use 2027-03-14, or 2027-03-14 15:30 for an appointment, "
                         "or 03-14 (month-day) for a day that comes every year.") from None
    return year, month, day, time


def next_day(row, today: date) -> date:
    """The day a date next falls on. A one-off stays where it is. 29 February falls on the 28th in short years."""
    def in_year(year):
        try:
            return date(year, row["month"], row["day"])
        except ValueError:
            return date(year, 2, 28)
    if not row["yearly"]:
        return in_year(row["year"])
    this = in_year(today.year)
    return this if this >= today else in_year(today.year + 1)


def date_words(row) -> str:
    """A date as it was written down: '14 March, every year (since 2019), 15:30'."""
    words = f"{row['day']} {MONTHS[row['month'] - 1].capitalize()}"
    if row["yearly"]:
        words += ", every year" + (f" (since {row['year']})" if row["year"] else "")
    else:
        words += f" {row['year']}"
    return words + (f", {row['time']}" if row["time"] else "")


def how_soon(days: int, falls: date) -> str:
    return {0: "TODAY", 1: "tomorrow"}.get(days, f"in {days} days") + f", {falls:%a} {falls.day} {falls:%b}"


def kind_words(row, now: datetime) -> str:
    """The kind, with the honest labels: old feelings, from before, how sure, corrected."""
    kind = row["kind"]
    if kind == "felt" and now - datetime.fromisoformat(row["at"]) > timedelta(days=1):
        t = local(row["at"])
        kind = f"felt, OLD: this was {t:%A} {t.day} {t:%B}, not how I am now"
    elif kind == "guess":
        kind = f"guess, {row['sure']} sure" if row["sure"] else "guess"
    elif kind == FROM_BEFORE:
        kind = "from before, poured in by my human from old summaries" + (f", about: {row['tag']}" if row["tag"] else "")
    elif kind == "said":
        kind = "said by my human, word for word"
    elif kind == "taught":
        kind = "taught to me by my human"
    elif kind == "promise":
        kind = "promise, open" if row["state"] == "current" else "promise"
    elif kind == CARD:
        kind = f"card: {row['card']}"
    elif kind == LOG:
        kind = f"log: {row['card']}, exactly as written"
    extras = [state_words(row)] if row["state"] != "current" else []
    if row["corrects"]:
        extras.append(f"corrects #{row['corrects']} because: {row['why']}")
    return kind + "".join(f" ({e})" for e in extras)


def show_line(row, now: datetime) -> str:
    words = f'"{row["words"]}"' if row["kind"] == "said" else row["words"]
    return f"#{row['id']} | {short_date(row['at'])} | {kind_words(row, now)} | {words}"


def split_pieces(text: str) -> list[str]:
    """Old summaries become lines: one per paragraph, and one per bullet."""
    pieces = []
    for block in re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n")):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        bullet = re.compile(r"^(?:[-*•–]|\d+[.)])\s+")
        if len(lines) > 1 and sum(bool(bullet.match(l)) for l in lines) >= len(lines) - 1:
            pieces += [bullet.sub("", l) for l in lines]
        elif lines:
            pieces.append(" ".join(lines))
    return [p for p in pieces if p]
