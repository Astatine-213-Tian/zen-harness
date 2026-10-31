# Tabs

Work in background tabs you opened, run stalled pages at full speed, and catch tabs a click opens.

## Basics

```python
mine = new_tab("https://example.com/")    # background tab, now controlled; the user's tab stays in front
wait_for_load()
other = new_tab("https://example.org/")   # helpers now act on this one
switch_tab(mine)                          # back to the first; Zen's visible tab does not change
print([t["url"] for t in list_tabs(include_internal=False)])
close_tab(other)
```

Tabs from `new_tab` report `document.visibilityState == "hidden"`. Clicks, typing, `js`, screenshots and uploads all work there.

## Background tabs are throttled

In a hidden tab Zen stops `requestAnimationFrame` (0 frames/s against 60), runs timers about once a second, and stops updating `IntersectionObserver`. So a debounced search answers late, lazy images and infinite feeds stop loading, animations stall. On a fixture an infinite feed had 40 of 100 rows after 5 s hidden, and all 100 within 1.3 s at full speed. No BiDi command or per-session setting turns this off.

Wait on the result (`wait_for_element(...)`), not a fixed sleep. If the page stalls, first get the data without showing anything: the site's JSON API or `fetch` via `js()` (`zen-harness notes network`), the next page's URL, or `scroll()`.

Only if the page truly has to be visible: both helpers below are **off by default** (`foreground = "never"`) and raise until the user sets `foreground = "allow"` in `~/.config/zen-harness/config.toml`. Ask the user first; then pick one and tell them:

- `with in_front():` shows your tab for the block, then the user's tab again. They see their window switch tabs, and Zen comes in front of the app they are using and stays there. If their Zen window was minimized or covered, no tab was showing, so yours stays in front. Keep the block short.
- `new_window(url)` opens the page in a Zen window of your own, at full speed from then on; the user's tabs never switch. It takes the size and place of their Zen window: behind it if Zen was the active app (a ~0.3 s flash), otherwise on top of it, behind the app they are using. It runs only while part of it is on screen and not covered by another app (Zen's own windows don't count), so a minimized, hidden or covered Zen throttles it like a tab. `close_tab()` closes it.

```python
with in_front():
    js("document.querySelector('#more').scrollIntoView()")
    wait_for_element("#row-40", timeout=5)
```

`activate_tab(tab)` brings a tab and Zen to the front and leaves them there; use it when the user asks to see the tab.

## Tabs opened by the page

`click()` on a link that opens a new tab (`target=_blank`) Cmd-clicks it, so the tab opens in the background and the user's view doesn't jump; the harness keeps controlling the old tab. A page that calls `window.open` from its own script still opens a window in front, and `click_at_xy` on such a link still switches tabs. When you know the URL, open it yourself instead:

```python
new_tab(js("document.querySelector('#report').href"))
wait_for_load()
```

When only the page knows the URL, find the new tab by its opener and take it over:

```python
me = current_tab()["targetId"]
click("#popup")
wait(1)
kids = [c["context"] for c in bidi("browsingContext.getTree", maxDepth=0)["contexts"]
        if c.get("originalOpener") == me]
switch_tab(kids[-1])
wait_for_load()
print(page_info()["url"])
close_tab(kids[-1])
switch_tab(me)
```

## After closing the controlled tab

Closing the controlled tab leaves none controlled, and helpers that need a tab raise "no tab is controlled" until you call `new_tab(...)` or `switch_tab(...)`. They never fall back to the tab the user is looking at; `ensure_real_tab()` takes it on purpose. A new session (after `zen-harness stop` or the idle timeout) also starts with none: tab ids change between sessions, so find your tab again with `list_tabs()` and `switch_tab(...)`, or open a new one. `close_tab` does not wait for `beforeunload` prompts.

## Several agents at once

Each agent that sets `ZH_AGENT=<name>` has its own controlled tab; `new_tab`, `switch_tab` and every helper use that agent's tab, and each controlled tab carries the 🤖 marker. Agents without `ZH_AGENT` share one controlled tab, so one agent's `new_tab()` would redirect the other's clicks.

```bash
ZH_AGENT=flights zen-harness <<'PY'
new_tab("https://www.expedia.com/"); wait_for_load()
PY
```
