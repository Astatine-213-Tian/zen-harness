# zen-harness: let AI agents use your Zen browser

**Give Claude Code, Codex or any coding agent hands in the [Zen browser](https://zen-browser.app) you already use: open tabs, click, type, fill forms and read pages, while you stay signed in to everything.**

No separate test browser, no re-logging in, no API keys for each site. The agent runs short Python snippets against your real Zen (Firefox-based), in background tabs, and leaves your own tabs alone. It is fast (~70 ms per call) and cheap on tokens: a whole GitHub page comes back as about 100 lines.

If you know [browser-harness](https://github.com/browser-use/browser-harness): this is **browser-harness for Zen and Firefox**. Same working style and helper names, rebuilt from scratch on WebDriver BiDi, because Firefox-based browsers don't speak Chrome's DevTools Protocol.

```bash
zen-harness <<'PY'
new_tab("https://github.com/VibiumDev/vibium")
wait_for_load()
print(snapshot("star"))      # @e1 button "Star VibiumDev/vibium"
click("@e1")                 # starred, with your own GitHub login
PY
```

## What you can use it for

- "Search Expedia for flights from Toronto to Tokyo next month and list the three cheapest."
- "Star the repos in this list on GitHub."
- "Open my dashboard and tell me which jobs failed overnight."
- Testing your own web app in the browser where you're already logged in.

## Install

**Easiest: let your agent do it.** Paste this into Claude Code, Codex or any coding agent:

```text
Set up zen-harness for me: follow https://raw.githubusercontent.com/Astatine-213-Tian/zen-harness/main/install.md
```

The agent checks your machine, installs the CLI and its skill, asks you two preferences (which Zen profile, and whether it may restart Zen on its own), saves them to its instructions, and runs a read-only test. The steps are in [install.md](install.md) if you want to read them first.

**By hand.** Requires macOS, [Zen](https://zen-browser.app), Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/Astatine-213-Tian/zen-harness
mkdir -p ~/.claude/skills/zen-harness && zen-harness skill > ~/.claude/skills/zen-harness/SKILL.md
zen-harness doctor
```

Then ask your agent for a browser task. The first call connects to Zen (see [How it connects](#how-it-connects)).

## How it connects

The daemon attaches to whatever Zen is listening for WebDriver BiDi on `port`, whichever profile that is. If nothing is listening:

| Situation | Setting | Options |
|---|---|---|
| Zen is not running | `if_not_running` | `launch` (default): start Zen with remote control on. `instruct`: print the command. |
| Zen is running without remote control | `if_not_listening` | `instruct` (default): print how to fix it. `relaunch`: quit Zen gracefully and reopen it with remote control on. |

The harness never decides these for you; set them to your preference. `zen-harness relaunch` does the restart on demand. Tabs come back through Zen's session restore, so keep "Open previous windows and tabs" on if you rely on that.

To start Zen yourself with remote control on, run `zen-harness doctor`: it prints the exact command for your profile. That command includes `--marionette`, which lets the harness clean up its session even if it is force-killed. A Zen started with only `--remote-debugging-port` works too, without that protection.

## Configuration

Precedence: `ZH_*` env vars > `~/.config/zen-harness/config.toml` > defaults.

```toml
# ~/.config/zen-harness/config.toml
port = 9222
profile = ""                  # name from profiles.ini, a directory, or "" for Zen's default
if_not_running = "launch"     # or "instruct"
if_not_listening = "instruct" # or "relaunch"
automation_prefs = "skip"     # or "apply"
marionette_port = 0           # Marionette port when the harness starts Zen; 0 = any free port
headless = false
idle_timeout = 1800           # seconds without calls before the session is released; 0 = never
workspace = "~/.zen-harness"
tab_marker = "🐴"             # prefix on the controlled tab's title; "" to disable
```

`profile` and `automation_prefs` only matter when the harness starts Zen.

## Commands

| Command | What it does |
|---|---|
| `zen-harness <<'PY' … PY` | run a snippet |
| `zen-harness doctor` | config, Zen processes and profiles, port and session state |
| `zen-harness status` | is a session open, which tab is controlled |
| `zen-harness stop` | end the session (frees Zen for other tools) |
| `zen-harness relaunch` | quit Zen and reopen it with remote control on |
| `zen-harness skill` | print the agent skill |

## Things to know

- **One session at a time.** Zen accepts a single remote-control client. While zen-harness holds it, other tools (e.g. Mozilla's `firefox-devtools-mcp`) can't connect; `zen-harness stop` or the idle timeout releases it.
- **Sites can tell.** When Zen is started with `--remote-debugging-port`, `navigator.webdriver` is `true` for every page in that browser session. Some bot-protected sites react to that. Restart Zen normally to browse without it.
- **Automation prefs.** In that mode Firefox also applies ~120 "recommended" automation prefs (e.g. turns off Safe Browsing) while it runs. With `automation_prefs = "skip"` (default), the harness adds `user_pref("remote.prefs.recommended", false);` to the profile's `user.js` when it launches the profile, so your everyday settings stay.
- **Force-killing the daemon.** When the harness starts Zen it adds `--marionette` and opens the session through Marionette, which Zen ends as soon as the daemon's connection drops, even after `kill -9`. If Zen was started with only `--remote-debugging-port`, the harness falls back to a plain BiDi session, which Zen keeps after its client disappears: the daemon still ends it on errors, idle timeout and SIGTERM/SIGINT/SIGHUP, but after a `kill -9` run `zen-harness relaunch`. `zen-harness doctor` shows which kind is in use.
- **Background tabs.** Agents work in background tabs. Clicks, typing and JS work there; wheel scrolling falls back to scrolling the element under the point.
- **Remote Control toggle.** Firefox is adding a built-in "Remote control for AI assistants" toolbar switch that turns this on without restarting (and without `navigator.webdriver`). Zen 1.23.4b ships its backend but not the button yet. zen-harness attaches to it unchanged once it appears.

## zen-harness vs browser-harness

| | browser-harness | zen-harness |
|---|---|---|
| Browser | Chrome, Chromium-based | Zen (Firefox-based) |
| Protocol | Chrome DevTools Protocol | WebDriver BiDi |
| How agents use it | Python snippets, helpers pre-imported | Same, with the same helper names |
| Finding elements | Accessibility tree | `snapshot()`: compact list of controls with `@e3` refs |
| Per call (warm) | ~100–130 ms | ~70 ms |
| Cloud browsers, recordings | Yes | No (local only, by design) |

## FAQ

**Can browser-harness, agent-browser, Playwright MCP or Chrome DevTools MCP control Zen?** Not your running Zen. browser-harness, agent-browser and Chrome DevTools MCP need Chrome's DevTools Protocol, which Firefox removed; Playwright drives its own bundled Firefox build, not your browser and logins. Mozilla's `firefox-devtools-mcp` can attach to Firefox, but as an MCP server (tool definitions every turn, page snapshots in context). zen-harness keeps the low-token "agent writes a short script" style.

**Does it work with regular Firefox?** It is built and tested for Zen. Firefox speaks the same protocol, so pointing `zen_path` and `zen_data_dir` at Firefox should work, but that is untested.

**Is it safe to point at my real browser?** The agent can do anything you can do in that browser, so use it with agents and tasks you trust. It works in tabs it opens, marks the tab it controls with 🐴, and the bundled skill tells agents to stop at passwords, payments and MFA.

**Windows or Linux?** Not yet; process and profile handling is macOS-only today.

## Develop

```bash
uv sync
uv run pytest        # runs snippets against a headless Zen on a throwaway profile
```

Design notes: [docs/DESIGN.md](docs/DESIGN.md).
