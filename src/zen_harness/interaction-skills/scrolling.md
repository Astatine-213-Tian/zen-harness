# Scrolling

Scroll pages and inner panes from a background tab; load infinite feeds.

## scroll(x, y, dy)

`scroll` scrolls whatever is under the point (viewport CSS pixels; positive `dy` goes down). Zen ignores wheel input in background tabs, so there the helper scrolls the nearest scrollable element under the point with JS instead. Point at an inner pane to scroll the pane, not the page:

```python
r = js("const r = document.querySelector('#pane').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}")
scroll(r["x"], r["y"], dy=400)
print(js("document.querySelector('#pane').scrollTop"), page_info()["sy"])   # 400 0
```

To reach a known element, skip scrolling maths: `js("document.querySelector('#target').scrollIntoView({block: 'center'})")` (`click` already does this).

## Infinite feeds

Feeds usually load the next page when a sentinel comes into view (`IntersectionObserver`). In a background tab that observer stops updating, so the feed stalls: on a fixture 40 of 100 rows, however you scroll.

1. Best: read the feed's JSON API directly (see `zen-harness notes network`); no scrolling at all.
2. Else scroll where the page runs at full speed (see "Background tabs are throttled" in `zen-harness notes tabs`): `new_window(url)` for a long session, or `with in_front():` around the loop. Tell the user. Scroll in rounds until the count stops growing; going back up first makes the observer fire again if it last saw the sentinel while the tab was hidden:

```python
with in_front():
    count = 0
    for _ in range(50):
        js("window.scrollTo(0, 0)"); wait(0.1)
        js("window.scrollTo(0, document.documentElement.scrollHeight)")
        wait(0.5)
        n = js("document.querySelectorAll('#feed li').length")
        if n == count:
            break
        count = n
print(count)
```

Virtualised lists (only visible rows exist in the DOM) need the data collected each round, not counted at the end.
