# iframes

Run JS inside frames with iframe_target(); click and type in cross-origin frames through the frame's own context.

Each iframe is its own browsing context. `iframe_target(url_substr)` returns the first frame (nested frames included) whose URL contains the text; `js(..., target_id=frame)` runs there, same-origin or not.

```python
tree = bidi("browsingContext.getTree", root=current_tab()["targetId"])["contexts"][0]
print([c["url"] for c in tree.get("children") or []])     # what frames exist

frame = iframe_target("frame-inner")
print(js("document.querySelector('#out').textContent", target_id=frame))
```

From the parent page a cross-origin frame's `contentDocument` is `null`; use `target_id` instead. Frames load after the parent: if `iframe_target` returns `None`, wait and retry. `about:srcdoc` matches `<iframe srcdoc>` frames.

## Clicking and typing

`click(selector)`, `fill_input` and `wait_for_element` only look at the top document.

**Same-origin frame:** `click_at_xy` at the iframe's box (`getBoundingClientRect()` plus `clientLeft`/`clientTop`, from the parent) plus the element's box (from `js(..., target_id=frame)`). Then `type_text` reaches the focused element inside it.

**Cross-origin frame:** clicks at top-level coordinates do not reach it (verified in a headless background tab: no events fired), and `type_text` keys stay in the top document. Send input to the frame's own context, with coordinates inside the frame:

```python
frame = iframe_target("localhost")

def frame_click(selector):
    b = js(f"""const r = document.querySelector({selector!r}).getBoundingClientRect();
    return {{x: r.left + r.width / 2, y: r.top + r.height / 2}}""", target_id=frame)
    bidi("input.performActions", context=frame, actions=[{"type": "pointer", "id": "mouse",
         "parameters": {"pointerType": "mouse"}, "actions": [
         {"type": "pointerMove", "x": round(b["x"]), "y": round(b["y"])},
         {"type": "pointerDown", "button": 0}, {"type": "pointerUp", "button": 0}]}])

def frame_type(text):
    keys = [a for ch in text for a in ({"type": "keyDown", "value": ch}, {"type": "keyUp", "value": ch})]
    bidi("input.performActions", context=frame, actions=[{"type": "key", "id": "keyboard", "actions": keys}])

frame_click("#code"); frame_type("42")
frame_click("#ok")
print(js("document.querySelector('#out').textContent", target_id=frame))
```

This works for same-origin frames too. Scroll the element into view inside the frame first if it might be off-screen (`js("...scrollIntoView()", target_id=frame)`).

## Payment and login frames

Card fields (Stripe, Adyen) and third-party sign-in frames are cross-origin on purpose. Don't type card numbers or passwords: stop and ask the user (see `zen-harness notes login-walls`).
