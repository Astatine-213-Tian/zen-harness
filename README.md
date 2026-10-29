# zen-harness

Let a coding agent (Claude Code, Codex, …) drive your real **Zen** browser: your tabs, your logins, whichever profile you choose. Agents send short Python snippets; helpers are pre-imported; a background daemon keeps the browser session open (~70 ms per call once warm).

It follows the design of [browser-harness](https://github.com/browser-use/browser-harness) but is a separate, from-scratch package. Zen is Firefox-based and has no Chrome DevTools Protocol, so zen-harness speaks **WebDriver BiDi**.

```bash
zen-harness <<'PY'
new_tab("https://www.expedia.ca/Flights")
wait_for_load()
print(page_info())
PY
```

## Install

```bash
uv tool install --editable ~/Developer/zen-harness
```

To give Claude Code the skill:

```bash
mkdir -p ~/.claude/skills/zen-harness && zen-harness skill > ~/.claude/skills/zen-harness/SKILL.md
```

## How it connects

The daemon attaches to whatever Zen is listening for WebDriver BiDi on `port`, whichever profile that is. If nothing is listening:

| Situation | Setting | Options |
|---|---|---|
| Zen is not running | `if_not_running` | `launch` (default): start Zen with remote control on. `instruct`: print the command. |
| Zen is running without remote control | `if_not_listening` | `instruct` (default): print how to fix it. `relaunch`: quit Zen gracefully and reopen it with remote control on. |

The harness never decides these for you; set them to your preference. `zen-harness relaunch` does the restart on demand. Tabs come back through Zen's session restore, so keep "Open previous windows and tabs" on if you rely on that.

To start Zen yourself with remote control on:

```bash
/Applications/Zen.app/Contents/MacOS/zen --remote-debugging-port 9222
```

## Configuration

Precedence: `ZH_*` env vars > `~/.config/zen-harness/config.toml` > defaults.

```toml
# ~/.config/zen-harness/config.toml
port = 9222
profile = ""                  # name from profiles.ini, a directory, or "" for Zen's default
if_not_running = "launch"     # or "instruct"
if_not_listening = "instruct" # or "relaunch"
automation_prefs = "skip"     # or "apply"
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
- **Force-killing the daemon locks Zen.** Firefox keeps a BiDi session open after its client disappears and can't hand it to a new one. The daemon ends the session on errors, idle timeout and SIGTERM/SIGINT/SIGHUP; after a `kill -9`, run `zen-harness relaunch`.
- **Background tabs.** Agents work in background tabs. Clicks, typing and JS work there; wheel scrolling falls back to scrolling the element under the point.
- **Remote Control toggle.** Firefox is adding a built-in "Remote control for AI assistants" toolbar switch that turns this on without restarting (and without `navigator.webdriver`). Zen 1.23.4b ships its backend but not the button yet. zen-harness attaches to it unchanged once it appears.

## Develop

```bash
uv sync
uv run pytest        # runs snippets against a headless Zen on a throwaway profile
```

Design notes: [docs/DESIGN.md](docs/DESIGN.md).
