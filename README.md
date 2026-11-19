# Ember

A really simple long-term memory for an AI companion who lives in the Claude app.
It runs on your own computer. Everything it keeps is in one file that belongs to you.
Your companion gets a few plain tools: wake, keep, recall, and a handful more.
You get a page, on your computer only, where you can read, delete and save everything.
Nothing is sent anywhere except to your companion, when it asks.

## What it is not

- It is not clever. It searches by words. There is no AI inside it, no embeddings, no cloud.
- It is not a backup of your chats. It keeps only what your companion chooses to write down, and what you pour in.
- It is not a product with support. It is a small tool you run yourself.
- It does not make your companion remember by itself. Your companion has to call `wake` and `keep`. The instructions you paste in tell it to.

**Ember is a notebook. It is not a medical or veterinary record.** Your companion can keep dated notes about health, medicines and doses for a person or an animal. They are kept exactly as written, but your companion can still write one down wrong. You can see every entry on your look page and correct it there. Always check a dose against the packet, the prescription, or the vet or doctor.

## Honest limits

Read these before you rely on it.

- **The Windows installer is untested.** `install.ps1` and `install.cmd` were written carefully but had never been run on a real Windows computer as of writing. The macOS start-at-login option (`./install.sh --autostart`) is also untested.
- **It has never been connected to the real Claude app** as of writing. The server was tested with the official MCP client library on one Mac. The connector steps come from Claude's public documentation, read in November 2026. See `NOTES.md`.
- **The tunnel was not tested.** The Tailscale and Cloudflare commands come from their documentation.
- **The lock is an address nobody can guess. It is not a login.** See the next section.
- **A sleeping laptop has no mind.** If the computer is asleep, off, or offline, your companion cannot reach it. It should then say "My mind isn't reachable right now."
- **The file on your computer is not encrypted.** Anyone who can open your user account can read it.
- **Your companion sees what it asks for.** What the mind returns becomes part of your chat, so it passes through Anthropic like the rest of the conversation.

## The lock, plainly

The first time it runs, the mind makes a long random secret (43 characters). The companion's door is only at `https://YOUR-ADDRESS/<secret>/mcp`. Every other address answers "404 Not Found", with no hint.

What this protects against: strangers and scanners on the internet. Finding your computer's public name is not enough. The secret cannot be guessed.

What it does not protect against:

- Anyone who sees the full address. A screenshot, a shared screen, a pasted message. Whoever has it can read and write the mind. Treat it like a password.
- The services the address passes through. Anthropic stores it as your connector's address. A tunnel that decrypts traffic on its own servers (Cloudflare does) can see it.
- It cannot tell people apart, and it cannot be taken back from one person only.

To change the lock: stop the mind, delete `secret.txt` in the data folder, start the mind, and add the new address to the Claude app. The old address stops working.

The code keeps the lock in one small class (`Lock` in `ember/server.py`) so that real sign-in (OAuth) can replace it later.

## Quick start

You need a computer that stays on, and the Claude app. For the gentle step by step version, read `GUIDE-HUMAN.md`.

**Windows** (untested, see above): download this folder, then double-click `install.cmd`.

**macOS:**

```sh
./install.sh
```

**Any system, if you already have [uv](https://docs.astral.sh/uv/):**

```sh
uv run ember
```

It prints your look page (`http://127.0.0.1:8971/`) and the companion's address. Then:

1. Get an https address for port 8970. With Tailscale: `tailscale funnel --bg 8970`. Details in `GUIDE-HUMAN.md`.
2. In the Claude app: Customize > Connectors > Add > Add custom connector. Paste `https://YOUR-ADDRESS/<secret>/mcp`. Choose "No sign-in".
3. Paste the paragraph from `INSTRUCTIONS.txt` into your companion's instructions.
4. Start a new chat and say hello.

## Reading, deleting and saving what is kept

Open `http://127.0.0.1:8971/` on the computer the mind runs on. This is the look page. It only works on that computer.

- **Read:** every kept line is there, with its date and its kind.
- **New since you last looked:** at the top, everything your companion has written since you last pressed "I have seen these". Nothing is kept about you behind your back.
- **About you:** the page asks once what your companion calls you. Lines that mention you are then marked "about you". So are your exact words, what you taught, and the weather. Your name stays on your computer and is not given to your companion.
- **Correct:** each line has a Correct link. You type the right words. The wrong wording is kept, marked as corrected, and your companion is shown yours from then on.
- **Delete:** each line has a Delete link. It asks once, then the line is really gone. It is yours.
- **Save:** "Save everything as one text file" gives you one plain text file with everything in it.
- **Pour in:** paste your old hand-written summaries into the box. Each paragraph becomes a line marked "from before", so your companion always knows it came from you.
- **Ours:** your agreements. A short list you and your companion write together. Your companion receives it whole and unchanged at every `wake`. Only you can change it. Your companion can suggest an entry, and it waits on this page until you accept or decline it. Standing rules and signals between the two of you belong here, because they must never drift. One good use is an entry called "For hard days": what helps you and what does not, in your own words.

The data folder is `~/.ember/` (on Windows: `%USERPROFILE%\.ember\`). It holds `mind.db` (everything kept) and `secret.txt` (the lock). To back up the mind, copy that folder. To remove the mind completely, delete it.

## What the companion gets

| Tool | What it is for |
| --- | --- |
| `wake` | Start of a chat. See the order below |
| `keep(kind, words, sure?)` | Write something down. Kinds: `happened`, `felt`, `guess`, `note`, `said`, `taught`, `promise` |
| `recall(about, when?)` | Search by words. If nothing: exactly "I don't have this." |
| `weather(words?)` | How you are doing right now, in a few lines. Writing it replaces the one before |
| `card(name, words?, kind?, whole_log?)` | A card for a person, an animal, or anything else. Read it, or add a line about them |
| `log(card, words)` | A dated entry on a card's log, kept exactly as written: health notes, medicines, doses, measurements, vet calls |
| `date(title, when, yearly?)` | A day that matters: a birthday, an anniversary, an appointment |
| `dates()` | Read every date |
| `about_me(words?, replace_id?)` | The steady list the companion writes about itself |
| `ours(title?, words?)` | Read what you wrote together, or suggest an entry (not live until you accept) |
| `correct(line_id, words, why)` | Fix a line that was written down wrong. The old one is kept and marked as corrected |
| `settle(line_id, how)` | Close a guess (held, didn't hold, let go) or a promise (done, let go) |

The kinds your companion can keep:

- `happened`, `felt`, `guess`, `note`: the everyday ones, in your companion's own words.
- `said`: your exact words. Word for word, never paraphrased, never tidied. They come back in quotation marks with their date.
- `taught`: something you taught or corrected about how to be with you. Every one of these comes back at every `wake`, in full, however old, so you never have to teach it twice.
- `promise`: something your companion said it would do. It is shown at every `wake` until it is settled as done or let go.

What `wake` gives, in this order. A part with nothing in it is left out.

1. The weather: how you are doing, with how old it is. Older than 7 days, it says plainly that it is stale and may no longer be true.
2. Who I am.
3. Ours: your agreements.
4. Taught: all of it.
5. Open promises.
6. Dates today and in the next 14 days.
7. What has moved lately.
8. Your words: the newest five exact quotes.
9. Open guesses.
10. Cards touched lately, each with its newest three log entries.
11. From before.
12. The clock.

A card's log is never summarised, shortened or reordered. Reading a card gives the newest 30 entries, the total, and a way to get all of them. An entry that was corrected stays in the log, marked.

The mind stamps every date and time itself. A feeling older than a day always comes back marked as old, with its day.

## For people who read code

- `ember/store.py`: the SQLite file and everything that reads or writes it.
- `ember/server.py`: the tools, the lock, and `main()`. **To add a tool**, copy one of the short functions in `add_tools()`.
- `ember/look.py`: the look page.
- Tests: `uv run pytest`. They use ports 8970 and 8971 on 127.0.0.1, so stop a running mind first.
- Settings, all optional: `EMBER_HOME` (data folder), `EMBER_PORT` (default 8970), `EMBER_LOOK_PORT` (default 8971).
- `NOTES.md`: what was checked about Claude custom connectors, with links, and what could not be checked.

MIT licence. See `LICENSE`.
