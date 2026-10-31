# Shadow DOM

Reach elements inside web components: open roots with plain selectors, closed roots by coordinates.

## Open roots

Every helper that takes a selector (`click`, `fill_input`, `wait_for_element`, `upload_file`, `dispatch_key`) looks in the page first, then inside open shadow roots (web components such as `<star-card>` or `<sl-button>`). Snapshot refs (`@e3`) do too. So write the selector for the element itself:

```python
click("#star")              # a button inside <star-card>'s shadow root
fill_input("#q", "zen")     # an input inside it
upload_file("x-uploader input[type=file]", "/abs/path/report.csv")  # no: a selector can't cross into a root
upload_file("input[type=file]:not(#files)", "/abs/path/report.csv")  # yes: matches the input inside the root
```

A selector matches within one tree, so it can't span a shadow boundary: `star-card #star` finds nothing. Use the inner part alone, or a ref from `snapshot()`. When the same selector matches outside and inside a root, the match outside wins.

For reads, walk the path in `js()`: `js("document.querySelector('star-card').shadowRoot.querySelector('#q').placeholder")`.

## Closed roots

`host.shadowRoot` is `null`, so neither JS nor the helpers can see inside. Click by position: the host's box, or a screenshot. Then check the effect on the page.

```python
r = js("const r = document.querySelector('#closed').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}")
click_at_xy(r["x"], r["y"])
```

(Uploads on http(s) pages have one more limit: see `zen-harness notes uploads`.)
