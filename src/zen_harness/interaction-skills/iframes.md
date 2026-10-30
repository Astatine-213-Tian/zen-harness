# iframes

snapshot() lists controls inside iframes with frame refs (@f1e2) that click/fill_input route to the frame; iframe_target() + js() for everything else.

Each iframe is its own browsing context. `iframe_target(url_substr)` returns the first frame (nested frames included) whose URL contains the text; `js(..., target_id=frame)` runs there, same-origin or not.

```python
tree = bidi("browsingContext.getTree", root=current_tab()["targetId"])["contexts"][0]
print([c["url"] for c in tree.get("children") or []])     # what frames exist

frame = iframe_target("frame-inner")
print(js("document.querySelector('#out').textContent", target_id=frame))
```

From the parent page a cross-origin frame's `contentDocument` is `null`; use `target_id` instead. Frames load after the parent: if `iframe_target` returns `None`, wait and retry. `about:srcdoc` matches `<iframe srcdoc>` frames.

## Clicking and typing

`snapshot()` lists visible iframes (same- or cross-origin, nested) after the top document, each under a header line, with refs that carry the frame number:

```
@e1 button "Top"
# frame f1 http://localhost:8771/frame-inner.html?cross=1
@f1e1 textbox "Code"
@f1e2 button "OK"
```

```python
snapshot()
fill_input("@f1e1", "42")
click("@f1e2")
print(js("document.querySelector('#out').textContent", target_id=iframe_target("cross=1")))
```

`click`, `fill_input`, `wait_for_element`, `dispatch_key` and `upload_file` take frame refs: the lookup runs in the frame's own context and pointer and key input is sent to that context with frame coordinates. `query=` and `limit=` count across frames; `within=` is a CSS selector in the top document and keeps only the frames inside it. Frames are numbered per snapshot (a `query=` can renumber them), so use refs from the latest one. Hidden or 0×0 frames are skipped. CSS selectors, `type_text`, `press_key` and `click_at_xy` still act on the top document: to type into a frame, use `fill_input` with a frame ref. Closed shadow roots stay invisible, in frames as everywhere. Input sent to a frame isn't tracked as a possible navigation of the tab, so if a frame click navigates the whole tab, wait for something on the new page with `wait_for_element(...)` rather than relying on `wait_for_load()` alone.

**Without a snapshot ref:** clicks at top-level coordinates do not reach a cross-origin frame (verified in a headless background tab: no events fired), and `type_text` keys stay in the top document. Send input to the frame's own context, with coordinates inside the frame:

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
