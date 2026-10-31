---
name: zen-harness
description: "Control the user's real Zen browser (tabs, logins, profile) from Python snippets over WebDriver BiDi. Use for web tasks that need interaction, the user's signed-in session, JS rendering, or a bot-protected page."
---

# zen-harness

Drives the user's own Zen browser: their tabs, cookies and logins. Send a Python snippet on stdin; the helpers below are pre-imported and a background daemon keeps the browser session open between calls (~70 ms per call once warm).

```bash
zen-harness <<'PY'
new_tab("https://github.com/notifications")
wait_for_load()
print(page_info())
PY
```

## When not to use it

If a plain HTTP request can read it (a public page, an API, docs), use `curl` or `http_get(url)` and leave the browser alone. Use the browser for interaction, the user's logged-in session, JS-rendered pages, or bot-protected pages.

## Helpers

- Tabs: `new_tab(url)` (opens in the background and controls it; use this for the first navigation), `goto_url(url, leave=False)`, `list_tabs()`, `current_tab()`, `switch_tab(tab)`, `in_front()`, `new_window(url)`, `activate_tab(tab)`, `close_tab(tab=None)`, `ensure_real_tab()`
- Read: `snapshot(query=None, within=None, limit=150, hrefs=False)` → one line per visible control, e.g. `@e3 button "Search"`, then each iframe's controls under a `# frame f1 <url>` line (`@f1e2`); `page_info()` → `{url, title, w, h, sx, sy, pw, ph}`, or `{dialog: ...}` while a dialog is open; `js(expr, target_id=None)`; `capture_screenshot(path=None, full=False, max_dim=None)`
- Act: `click(selector, leave=False)`, `click_at_xy(x, y)`, `fill_input(selector, text)`, `type_text(text)`, `press_key(key, modifiers=0)` (1=Alt 2=Ctrl 4=Cmd 8=Shift), `scroll(x, y, dy)`, `upload_file(selector, path)`, `dispatch_key(selector, key)`, `handle_dialog(accept=True, text=None)`. Every `selector` may be CSS (top document) or a snapshot ref like `"@e3"` or `"@f1e2"` (inside a frame).
- Wait: `wait_for_load()`, `wait_for_element(selector, timeout=10, visible=False)`, `wait_for_network_idle()`, `wait(seconds)`
- Other: `iframe_target(url_substr)` (pass to `js(..., target_id=...)`), `drain_events()` (console logs, finished requests, dialogs), `http_get(url)`, `bidi(method, **params)` (raw WebDriver BiDi)

`js()` returns the value of the last statement as plain Python. Each call runs in its own block, so `const`/`let` stay local; keep state on `window`. A top-level `return` or `await` works (with `await`, use `return` to get a value).

## Working on a page

- First navigation is `new_tab(url)`. It opens a background tab, so the user's visible tab stays put. Keep your effect on the user's machine minimal: never bring Zen, a tab or a window to the front on your own. Hidden tabs are throttled; if lazy loading, a feed or an animation stalls, first work without showing anything (read the data with `js()`/`fetch` or the site's API, page through URLs, `scroll()`). `in_front()` and `new_window(url)` are off unless the user set `foreground = "allow"`; if a page truly needs to be visible, ask the user (`zen-harness notes tabs`). Call `activate_tab(...)` only when the user asks to see a tab.
- The controlled tab's title starts with 🤖 so the user can see which tab you hold.
- After a navigation or a click that loads a page, call `wait_for_load()`; it waits for the new page, not the one you left. On single-page apps use `wait_for_element(...)`.
- Find controls with `snapshot()` first: a whole GitHub repo page is ~100 lines (~750 tokens). Narrow it with `snapshot("star")` or `snapshot(within="form")`, then act on the ref: `click("@e3")`, `fill_input("@e7", "Toronto")`. Refs last until the next `snapshot()` or navigation, so snapshot again after the page changes.
- For text and data (prices, lists, tables) use `js(...)` and print only what you need. Do not print whole pages.
- Use `click_at_xy` for canvas or odd widgets: get coordinates from `getBoundingClientRect()` in `js`, or from a screenshot. `snapshot()` includes iframes (any origin), and frame refs route clicks and keys to the frame; for other work in a frame use `iframe_target` + `js`. (BiDi's accessibility locator hangs in Zen; don't use it.)
- Dialogs: a click that opens alert/confirm/prompt returns at once; `page_info()` then shows `{dialog: ...}`. Answer it with `handle_dialog(...)`. `wait_for_load()`/`wait_for_element()` raise `DialogOpen` while one blocks the tab.
- Unsaved changes: Zen brings a tab to the front to ask "Leave page?", so `goto_url` and `click` on a link never let that prompt open. If the page says it has unsaved changes, they wait up to 10 s (`save_wait`) for it to save, then raise `UnsavedChanges`. Wait and retry, or pass `leave=True` to discard (ask the user first if it's their work). Navigate with these helpers, not `js("location.href=...")`, which can still prompt.
- Verify the result with a targeted `js(...)` or `page_info()` check before reporting success.
- Login walls, passwords, MFA, payment or consent screens: stop and ask the user.
- Never close or navigate the user's own tabs unless asked; work in tabs you opened.

## Stuck on a browser mechanic?

Run `zen-harness notes` for tested how-tos: tabs, navigation, dialogs, forms, iframes, shadow DOM, uploads, downloads, scrolling, network, screenshots, cookies, login walls. `zen-harness notes <topic>` prints one.

## Connection

The daemon attaches to Zen on the configured port (default 9222). If Zen is not reachable it follows the user's config:

- `if_not_running = "launch"` (default): starts Zen with remote control on.
- `if_not_listening = "instruct"` (default): Zen is running without remote control, so it prints the fix. `relaunch` restarts Zen automatically instead.

Follow the user's own instructions about which profile to use and whether relaunching is okay. Show the printed fix to the user rather than retrying in a loop. Other commands: `zen-harness doctor`, `zen-harness status`, `zen-harness stop` (ends the session so other tools can connect), `zen-harness relaunch`.

With `remote_mode = "runtime"` (opt-in) the harness turns remote control on inside the running Zen instead of restarting it. The user may see an "Allow remote control?" prompt in Zen the first time; tell them to click Allow. If it reports missing about:config settings, show the user that message; don't change their browser settings yourself.

Zen allows one remote-control session at a time. If another tool holds it, the error says so; stop the other tool or ask the user. If the session was left behind by a crashed client, `zen-harness stop --force` clears it without restarting Zen, but it ends *whatever* session is open, so ask the user before running it.

## Reusable workflows

Workspace: `~/.zen-harness` (or `$ZH_WORKSPACE`).

- `agent_helpers.py`: put task-specific helpers here; they load into every snippet.
- `domain-skills/<site>/*.md`: notes and snippets per site (e.g. `domain-skills/expedia/search-flights.md`). With `ZH_DOMAIN_SKILLS=1`, `goto_url` returns the matching files; read them before inventing an approach. After working out a non-obvious flow, save it there.
