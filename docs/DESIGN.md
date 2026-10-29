# zen-harness — design

Status: draft for review. No code yet.

## Goal

Let a coding agent (Claude Code, Codex) control the user's **real Zen browser**: their tabs, their logins, whichever profile Zen is running. Same working style as browser-harness: the agent sends a short Python snippet through a heredoc, helpers are pre-imported, a background process keeps the browser connection warm, and reusable per-site workflows live in a workspace folder.

```bash
zen-harness <<'PY'
new_tab("https://www.expedia.ca/Flights")
wait_for_load()
print(page_info())
PY
```

Example tasks: search Expedia flights from Toronto, star a GitHub repo, read a dashboard you are signed in to.

### Non-goals (v1)

- No policy about *which* profile to use. That is the user's preference (CLAUDE.md or config), not the harness's.
- No cloud browsers, session recordings, video export, telemetry or self-update (browser-harness has these; none are needed here).
- Not an MCP server. Mozilla's `firefox-devtools-mcp` already covers that; this tool exists for the low-token CLI style.
- No managing Zen workspaces, Essentials or split view.

## Facts this design rests on

Checked on the installed Zen 1.23.4b (Firefox core), unless marked.

| Fact | Source |
|---|---|
| Zen has no CDP. It speaks **WebDriver BiDi** over `ws://127.0.0.1:<port>/session`. | Live test with a headless throwaway profile |
| BiDi is fast: JS eval ~0.3 ms, click ~18 ms, screenshot ~12 ms. Opening a session costs ~310 ms. | Live test |
| The browser accepts **one WebDriver session at a time**. | Firefox Remote Agent; Mozilla MCP docs |
| Two ways to turn BiDi on: (1) launch with `--remote-debugging-port[=N]`; (2) **Remote Control**: a toolbar panel ("Remote control for AI assistants" → Turn on) that starts it inside an already-running browser, behind pref `remote.experimental.dynamicstart.enabled`. | Zen's bundled `RemoteAgent.sys.mjs`, `RemoteControlServers.sys.mjs`, `remoteControl.ftl` |
| Remote Control asks the user "Allow remote control?" on each new connection, with "remember until the browser exits". It shows a banner while a client is connected. | `ConnectionPrompt.sys.mjs`, `RemoteControlBanner.sys.mjs` |
| Remote Control starts with `isBrowserAutomation: false`. That *probably* means no `navigator.webdriver` and no automation prefs, so sites see a normal browser. **Unverified.** | `RemoteAgent.sys.mjs` |
| Remote Control listens on the default port **9222**. Chrome remote debugging often uses 9222 too. | `RemoteAgent.sys.mjs` (`DEFAULT_PORT`) |
| **Zen 1.23.4b ships the Remote Control backend but not the toolbar button**: only its CSS and strings are present, and nothing calls `RemoteControlServers.start()`. Until Zen ships the button, the working path is launching with `--remote-debugging-port`. The harness attaches to either source the same way, so it works unchanged once the button lands. | Zen's bundled `omni.ja` |
| Launch-flag mode is "browser automation" mode: on BiDi start Firefox applies ~120 **recommended prefs** to the profile (e.g. turns off Safe Browsing and crash session-restore) and restores them on shutdown. The pref `remote.prefs.recommended=false` skips this. Remote Control mode never applies them. | `WebDriverBiDi.sys.mjs`, `RecommendedPreferences.sys.mjs` |

## Modules

```
 agent snippet ──► CLI ──► Helpers ──(IPC)──► Session daemon ──(BiDi ws)──► Zen
                            │                    ▲
                            ▼                    │
                        Workspace           Connection (find / start Zen)
                                                 ▲
                                               Config
```

### 1. Helpers — the agent's interface (main leverage point)

What the agent learns. **Same names and meanings as browser-harness**, so existing habits, SKILL text and domain-skill notes carry over:

- Navigation and tabs: `goto_url`, `new_tab`, `list_tabs`, `current_tab`, `switch_tab`, `activate_tab`, `close_tab`, `ensure_real_tab`
- Reading: `page_info`, `js`, `capture_screenshot`
- Input: `click_at_xy`, `type_text`, `fill_input`, `press_key`, `dispatch_key`, `scroll`, `upload_file`
- Waiting: `wait`, `wait_for_load`, `wait_for_element`, `wait_for_network_idle`
- Other: `http_get`, `drain_events`, and `bidi(method, **params)` as the raw escape hatch (replaces `cdp()`).

Each helper hides BiDi detail the agent should never see: browsing-context ids, element `sharedId`s, pointer and key action sequences, realm handling, retrying `js` with a function wrapper when the snippet uses a top-level `return`, and file inputs (`input.setFiles`).

Dropped from browser-harness: `iframe_target` (BiDi treats iframes as child contexts; `js(..., frame=...)` covers it), plus the cloud, recording and video helpers.

Caller-visible side effect: the controlled tab gets a title marker (browser-harness uses 🐴) so you can see which tab the agent holds. Configurable, can be turned off.

### 2. Session daemon — owns the one BiDi session

A background process, started on first use, that owns the single BiDi session.

- Interface seen by Helpers: `call(method, params) -> result` and a few meta operations: `current_tab`, `set_tab`, `drain_events`, `pending_dialog`.
- Hidden inside: websocket and session setup, event subscriptions (console, network, dialogs, downloads) buffered for `drain_events` / `page_info`, a remembered current tab, reconnecting if Zen restarts.
- **Idle timeout** (default 30 min) ends the session. That releases the one-session slot for other tools (e.g. Mozilla's MCP) and clears Zen's "being controlled" banner. `zen-harness stop` releases it on demand.

### 3. Connection — find or start Zen

The deep part that replaces arc-cdp's role. Interface: `connect(config) -> ws_url`, or one of three named errors that each carry the exact fix:

1. **Listening** on the port → return the URL. This attaches to whatever Zen and profile are listening. The harness does not care which profile it is.
2. **Zen running, not listening** → what happens is set by `if_not_listening`:
   - `instruct` (default): error with the fix: *"Turn on Remote Control in Zen (toolbar → Remote control → Turn on), or run `zen-harness relaunch`."*
   - `relaunch`: quit Zen gracefully and restart it with the flag (same as `zen-harness relaunch`), then attach.
3. **Zen not running** → set by `if_not_running`:
   - `launch` (default): start Zen with `--remote-debugging-port=<port>` and the configured profile, wait until it listens, return the URL.
   - `instruct`: error with the command to start it yourself.

The package supports every option; picking one is the user's (or their agent instructions') call, not the harness's.

Also hidden here: telling a BiDi listener apart from Chrome's CDP on the same port (Chrome answers `/json/version`; Firefox does not), reading `profiles.ini`, and working out which profile a running Zen process uses.

Relaunch (from `zen-harness relaunch` or `if_not_listening = relaunch`) is the only path that quits Zen: graceful quit, then restart with the flag, so Zen's session restore brings the tabs back.

### 4. Config — in-process

Precedence: env vars > `~/.config/zen-harness/config.toml` > defaults.

| Key | Env | Default |
|---|---|---|
| `port` | `ZH_PORT` | `9222` (fixed by Remote Control) |
| `profile` | `ZH_PROFILE` | Zen's default profile from `profiles.ini`, i.e. what opening Zen from the Dock gives you |
| `zen_path` | `ZH_ZEN_PATH` | `/Applications/Zen.app/Contents/MacOS/zen` |
| `if_not_running` | `ZH_IF_NOT_RUNNING` | `launch` (or `instruct`) |
| `if_not_listening` | `ZH_IF_NOT_LISTENING` | `instruct` (or `relaunch`) |
| `automation_prefs` | `ZH_AUTOMATION_PREFS` | `skip`: when the harness launches a profile, it makes sure that profile's `user.js` sets `remote.prefs.recommended=false`, so everyday browsing keeps Safe Browsing etc. `apply` leaves Firefox's default behaviour. |
| `idle_timeout` | `ZH_IDLE_TIMEOUT` | `1800` s |
| `workspace` | `ZH_WORKSPACE` | `~/.zen-harness` |
| `tab_marker` | `ZH_TAB_MARKER` | `🐴` (empty disables) |

`profile` is only used when the harness has to launch Zen. Your "use my main profile" preference is just the default, plus a line in CLAUDE.md.

### 5. Workspace — reusable workflows

Plain files under `~/.zen-harness` (independent of any other tool):

- `agent_helpers.py`: extra helpers the agent may add; loaded after the core helpers.
- `domain-skills/<site>/*.md`: notes and snippets per site (e.g. `expedia/search-flights.md`). Shown by `goto_url` when `ZH_DOMAIN_SKILLS=1`, like browser-harness.

### 6. CLI

`zen-harness` (snippet on stdin), `doctor`, `status`, `stop`, `relaunch`, `skill` (prints SKILL.md), `--version`. A SKILL.md for Claude Code ships with the package.

## Design review (codebase-design lens)

- **Depth.** The agent-facing interface is ~25 small functions, about the same as browser-harness. Each hides a multi-step BiDi sequence. Deletion test: removing Helpers would push context ids, `sharedId`s and action sequences into every snippet, so the module earns its keep. Same for Connection: removing it would scatter profile, port and process detection across callers.
- **A separate launcher would be shallow.** An arc-cdp-style wrapper would only pass a URL through. Folding it into Connection keeps that knowledge in one place. This is the change you suggested.
- **Seams.** There is no port/adapter abstraction over the BiDi transport. Only one adapter exists in production, and a real local stand-in exists for tests: headless Zen with a throwaway profile (dependency category 2, local-substitutable). Tests run the real thing; no mock BiDi server. The IPC between snippet and daemon is an internal seam (Unix socket, JSON lines), not exposed.
- **Where snippets run.** In the CLI process, like browser-harness, not inside the daemon. A crashing or looping snippet cannot take down the session. Cost is ~50–100 ms Python startup per call, the same as today.
- **Interface facts callers must know** (part of the interface even if not in a signature): one session at a time; a first-connect "Allow" prompt in Remote Control mode (the harness waits up to 45 s and says why); port 9222 shared with Chrome debugging; the tab-title marker.
- **Test surface** is the Helpers interface: snippets run against headless Zen on local fixture pages (forms, iframes, dialogs, file input), asserting what the page shows. No tests on daemon internals.

## Decisions

1. **Zen running without remote enabled:** both behaviours are supported (`if_not_listening`); default prints instructions. Which one to use is the user's preference, set in config or agent instructions.
2. **Independence:** zen-harness is its own package. It mimics browser-harness's design and helper names but has no code, workspace or workflow dependency on it. Workspace is `~/.zen-harness`.
3. **Helper names:** follow browser-harness's naming for familiarity; implementation is written from scratch on BiDi.

## Found while building (v0.1)

- **Remote Control button:** not shipped in Zen 1.23.4b (see the facts table). Main-profile use today means launch-with-flag or `relaunch`.
- **`navigator.webdriver` is `true`** for the whole browser session in launch-flag mode (tested).
- **A BiDi session outlives its socket and can't be rejoined.** Sessions created on `/session` get no `/session/<id>` handler (it returns 404), and closing the socket does not end them. So the daemon ends its session on every catchable exit (errors, idle timeout, SIGTERM/SIGINT/SIGHUP). After `kill -9`, Zen stays locked until restart. A possible follow-up is to create the session through Marionette (`webSocketUrl: true`): Marionette deletes its session when its TCP connection drops. That costs requiring `--marionette` too.
- **Input or JS that opens a dialog blocks until the dialog closes.** The daemon answers such pending calls as soon as `userPromptOpened` arrives, so `page_info()` can show the dialog and `handle_dialog()` can answer it.
- **Wheel input is ignored in background tabs.** `scroll()` falls back to scrolling the nearest scrollable element under the point via JS.
- **The `accessibility` locator in `browsingContext.locateNodes` hangs** in Zen; not used.
