# Notes: what was checked, and what was not

Written in November 2026. Everything under "Checked" was read on the linked public page on the day of writing. Pages change. If the Claude app looks different from this, trust the app and the linked pages over this file.

## Checked: Claude custom connectors

**Transport.** Use Streamable HTTP. The older HTTP+SSE transport still works but is being retired.
"Use Streamable HTTP, which the MCP specification defines for remote servers. Claude also supports the legacy HTTP+SSE transport, which is being deprecated in favor of Streamable HTTP."
https://claude.com/docs/connectors/building/index.md

A URL that ends in `/sse` makes the app pick the old SSE transport. This server's address ends in `/mcp`, so that does not apply.
https://claude.com/docs/connectors/custom/add-unlisted.md

**A server with no OAuth is accepted.** The authentication table lists type `none`: "No authentication (authless server)", "Supported by default". In the Add custom connector dialog the matching choice is "No sign-in: anyone with access to the server URL can use the connector."
https://claude.com/docs/connectors/building/authentication.md
https://claude.com/docs/connectors/custom/add-unlisted.md

**The address may have a path.** "Add your connector's remote MCP server URL exactly as the provider documents it, including any path." The example given is `https://mcp.example.com/mcp`. No rule against a longer path was found.
https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
https://claude.com/docs/connectors/custom/add-unlisted.md

**The server must be on the public internet, on port 443, over HTTPS, with an IPv4 address.** "Claude connects to your remote MCP server from Anthropic's cloud infrastructure, rather than from your local device." "Your server must also be reachable on the standard HTTPS port (443)." The troubleshooting page adds that the host name must resolve only to public addresses, and "Connectors are IPv4-only". Addresses in `100.64.0.0/10` are refused. This is why a tunnel is needed, and why the plain Tailscale network address (without Funnel) will not work.
https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
https://claude.com/docs/connectors/building/troubleshooting.md

**Anthropic's requests come from `160.79.104.0/21`.**
https://claude.com/docs/connectors/building/authentication.md (Network reference)

**The steps in the app** (Free, Pro, Max, Ultra): Customize > Connectors; Add, then Add custom connector; enter a name and the server URL, then Continue; choose authentication settings; Add; "If the connector shows Connect, click it and sign in."
https://claude.com/docs/connectors/custom/add-unlisted.md

Note: an older wording of these steps was "Settings > Connectors > Add custom connector" and "Complete OAuth or account sign-in if prompted". The pages read today say "Customize > Connectors" and do not contain that sentence. The guides in this repo give the current wording and mention the older one.

**Plans.** Custom connectors are available on Free, Pro, Max, Ultra, Team and Enterprise. "Free users are limited to one custom connector." On Team and Enterprise only an Owner can add one.
https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

**Where it works.** "Claude connects to your server from claude.ai, Claude Desktop, Claude mobile, Cowork, and Claude Code, and the same connector infrastructure backs all of them."
https://claude.com/docs/connectors/building/index.md

**Each chat can switch connectors on or off.** The + button in the chat, then Connectors.
https://claude.com/docs/connectors/custom/add-unlisted.md

**Limits.** A tool result may be about 150,000 characters at most. A tool call may take 240 seconds at most. This server stays far below both.
https://claude.com/docs/connectors/building/index.md

**Host name checks break tunnels.** The testing page warns that a server which only accepts `localhost` in the `Host` header answers a tunnelled request with an error. The Python MCP SDK has the same protection and switches it on by default for a server on 127.0.0.1. This server switches it off, because requests arrive under the tunnel's name. A test sends a request with a foreign `Host` and an `Origin` of `https://claude.ai` and checks it is answered.
https://claude.com/docs/connectors/building/testing.md

**Secrets in addresses are discouraged by Claude's own documentation.** About fixed keys it says: "Never accept it in the URL: don't read tokens from query parameters ... URLs end up in server logs, proxies, and browser history". That text is about query parameters, but a secret in the path has the same weakness. The better fixed-key method, "Request headers", is "in beta and available to a limited set of organizations", so it cannot be relied on. That is why v1 uses the path, and why the README is blunt about it. This server keeps the path out of its own log (the access log is off).
https://claude.com/docs/connectors/building/authentication.md

## Checked: tunnels

**Tailscale Funnel.** `tailscale funnel 3000` style commands; needs Tailscale 1.38.3 or later, MagicDNS and HTTPS certificates ("The CLI enables these when you enable Funnel"); public ports 443, 8443, 10000; "available for all plans"; described as beta. With `--bg` "it runs persistently in the background until you turn it off" and resumes after a reboot. `tailscale funnel status` shows it. `tailscale funnel reset` clears it. The address looks like `https://machine-name.tailnet-name.ts.net`.
https://tailscale.com/kb/1223/funnel
https://tailscale.com/kb/1311/tailscale-funnel

**Cloudflare quick tunnel.** `cloudflared tunnel --url http://localhost:8080`; no account needed; "The hostname changes each time you create a Quick Tunnel"; "Quick Tunnels do not support Server-Sent Events (SSE)"; at most 200 requests in flight.
https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/

Because of the SSE limit, this server answers with plain JSON (`json_response=True`) and keeps no session (`stateless_http=True`). That choice also means nothing breaks when the mind restarts or the laptop wakes up.

## Checked: Windows sleep

"Settings > System > Power & battery > Screen, sleep, & hibernate timeouts", option "When plugged in, make my device sleep after".
https://support.microsoft.com/en-us/windows/power-settings-in-windows-11-0d6a2b6b-2e87-4611-9980-ac9ea2175734

## Not checked. Do not take these as facts.

- **The real Claude app has never been connected to this server.** Not on the web, desktop or mobile. Everything above is from documentation.
- **Whether the app's "Detected" setting picks "No sign-in" by itself for this server.** The server answers 404 to the OAuth discovery addresses and answers MCP requests without asking for sign-in, which is what an authless server should do. There are public bug reports of authless servers still being sent into OAuth registration (https://github.com/anthropics/claude-ai-mcp/issues/402, /457, /697). Their current state was not checked. If it happens, choose "No sign-in" by hand.
- **Whether a connector can be added from the mobile app**, or only used there after being added on the web or desktop. The pages say connectors work on mobile. They do not say where they can be added.
- **Tailscale Funnel with Claude.** Not run. Not checked: that a Funnel host name passes Claude's "public IPv4 only" check, that Funnel passes requests through unchanged, or that the first-time approval steps look the way the guide describes. Claude's own pages name Cloudflare Tunnel and ngrok as tunnels, not Tailscale.
- **Cloudflare Tunnel with this server.** Not run.
- **`install.ps1` and `install.cmd`.** Never run on Windows. In particular not checked: that a Scheduled Task with a logon trigger can be created without administrator rights (the script falls back to a Startup shortcut if it cannot), that the hidden window really stays hidden, and that a folder path with an apostrophe in it works (it probably does not).
- **`./install.sh --autostart`** (the macOS login item). Written, not run.
- **The lid setting on Windows.** The sleep timeout path above was checked. The lid path in the guide ("Lid, power & sleep button controls" on newer Windows 11, or Control Panel > Power Options > "Choose what closing the lid does") is from general knowledge and was not found on a Microsoft page today. Some laptops sleep on lid close no matter what. Not checked on any real laptop.
- **Python 3.11 and 3.13+.** The project asks for 3.11 or newer and `.python-version` picks 3.12, which is what the tests ran on.

## Design notes

- **Adding OAuth later.** The `Lock` class in `ember/server.py` is the only place that decides who gets in. FastMCP already accepts `auth=` and `token_verifier=`. Claude needs a `401` with a `WWW-Authenticate` header pointing at protected resource metadata, DCR or CIMD, PKCE S256, and the callback `https://claude.ai/api/mcp/auth_callback` (see the authentication page above). None of that is built.
- **Times.** Stored in UTC. Shown in the computer's local time zone.
- **Search.** FTS5 when SQLite has it, else LIKE. Small words ("the", "and") are dropped. All words must match first. If nothing, any word may match, and the answer says so.
- **Deleting a correction** makes the line it corrected current again, so no line is left marked "corrected" with nothing correcting it.
- **Exact words.** Lines of kind `said` and `log` are stored without trimming or any other change. Every other kind has spaces trimmed from the two ends and nothing else. A line longer than 4000 characters is refused whole. It is never cut.
- **Weather** is a line of kind `weather`. Writing a new one marks the one before as `replaced`. Its age is counted from the moment it was written. It is stale when that is more than 7 times 24 hours ago.
- **Dates** use the computer's local calendar day. A yearly 29 February falls on 28 February in years without one. `03-04` is read as month then day.
- **Cards.** A log entry needs a card that is already there. A misspelt name is refused and never starts a second card, so a log cannot be split by a typing slip.
- **The human's name** (for the "about you" mark) and the time they last looked are in a `settings` table in `mind.db`. No tool reads them, so the companion is never given them.
- **A correction made on the look page** uses the same path as the companion's `correct`, with the reason "corrected by my human on their own page".

## Tailscale Funnel and Claude: first-hand

Added after the notes above. In December 2025 one of the authors ran MCP servers on a home computer (presence, messages, memory) behind Tailscale Funnel, and they were reachable from claude.ai. That was their everyday setup at the time. So the main route in the guide is known to work from use, even though Claude's own pages only name other tunnel services. Not re-tested since, and not yet tested with this server.
