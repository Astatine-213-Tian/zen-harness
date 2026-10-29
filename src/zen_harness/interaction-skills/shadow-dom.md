# Shadow DOM

Reach elements inside web components: open roots via shadowRoot, closed roots by coordinates.

`click`, `fill_input`, `wait_for_element` and `upload_file` take a CSS selector for `document.querySelector`, which stops at shadow roots (`>>>` is not valid CSS). Signs you hit one: the element is visible on screenshots but the selector finds nothing, and its ancestor is a custom element (`<star-card>`, `<sl-button>`, ...).

## Open roots: a deep query

```python
DEEP = """function zhDeep(sel, root = document) {
  const hit = root.querySelector(sel); if (hit) return hit;
  for (const el of root.querySelectorAll('*'))
    if (el.shadowRoot) { const h = zhDeep(sel, el.shadowRoot); if (h) return h; }
  return null;
}
"""

box = js(DEEP + """const e = zhDeep('#star');
e.scrollIntoView({block: 'center'});
const r = e.getBoundingClientRect();
return {x: r.left + r.width / 2, y: r.top + r.height / 2}""")
click_at_xy(box["x"], box["y"])
```

Or walk the path when you know it: `js("document.querySelector('star-card').shadowRoot.querySelector('#q').placeholder")`.

(`DEEP` is a function declaration on purpose: a top-level `const` in `js()` stays declared in the page, so the second call would fail with "redeclaration". See `zen-harness notes js`.)

Typing into a shadow input: focus it in JS, then type real keys (framework listeners see normal input events):

```python
js(DEEP + "zhDeep('#q').focus()")
type_text("zen")
```

`wait_for_element` can't see inside either; poll the deep query:

```python
for _ in range(50):
    if js(DEEP + "!!zhDeep('#star')"):
        break
    wait(0.2)
```

## Closed roots

`host.shadowRoot` is `null`, so JS can't see inside. Click by position: the host's box, or a screenshot. Then check the effect on the page.

```python
r = js("const r = document.querySelector('#closed').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}")
click_at_xy(r["x"], r["y"])
```

## File inputs inside a shadow root

`upload_file` can't select them, but `js` returns DOM nodes as `{'node': ..., 'sharedId': ...}`, which `input.setFiles` accepts:

```python
el = js("document.querySelector('x-uploader').shadowRoot.querySelector('input[type=file]')")
bidi("input.setFiles", context=current_tab()["targetId"], element={"sharedId": el["sharedId"]},
     files=["/abs/path/report.csv"])
```

(Same limit on http(s) pages as `upload_file`: see `zen-harness notes uploads`.)
