# Tabs

Work in background tabs you opened, foreground one only when it stalls, and catch tabs a click opens.

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

In a hidden tab Zen runs `requestAnimationFrame` about once a second, delays timers to about a second, and stops updating `IntersectionObserver` after its first callback. So a debounced search answers late, lazy images and infinite feeds stop loading, animations stall. On a fixture, `setInterval(..., 100)` fired twice in 3 s, and an infinite feed loaded 40 of 100 rows in a minute hidden but all 100 in 1.2 s once visible.

Wait on the result (`wait_for_element(...)`), not a fixed sleep. If the page really stalls, bring it to the front and tell the user, since it changes what they see:

```python
activate_tab(current_tab())
```

## Tabs opened by the page

Clicking a `target=_blank` link switches Zen to the new tab, and a `window.open` popup opens a window in front: either way the user's view jumps, while the harness keeps controlling the old tab. Open the URL yourself instead:

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

Closing the controlled tab leaves none controlled, and the next helper call quietly adopts the tab the user is looking at (`ensure_real_tab`). Call `new_tab(...)` or `switch_tab(...)` right after `close_tab()` so you never act on the user's own tab. `close_tab` does not wait for `beforeunload` prompts.
