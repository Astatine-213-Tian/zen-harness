# Screenshots

Viewport, full page or one element; size them for the model; when to read the DOM instead.

```python
path = capture_screenshot()                       # viewport -> <workspace>/run/shot.png
path = capture_screenshot("/tmp/page.png", full=True)   # whole document, not just the viewport
```

Then open the PNG with your image tool. Screenshots work in background tabs; no need to activate.

## Prefer `js` for facts

Text, links, prices, form values and error messages are cheaper and exact through `js(...)`. Take a screenshot for layout questions, canvases/charts, images, or when you can't tell why a click "did nothing" (an overlay, a modal, a cookie banner covering the button).

## Size

Images are in device pixels: CSS size (`page_info()["w"]`, `["h"]`) times `devicePixelRatio` (`js("devicePixelRatio")`), which is 2 on a Retina display. Divide by it before passing screenshot coordinates to `click_at_xy`.

`max_dim` resizes with macOS `sips -Z` so the longest side equals `max_dim`. It **also enlarges** smaller images: a 1128×752 viewport with `max_dim=1800` comes back 1800×1200. Pass it only when the image is bigger:

```python
import struct
path = capture_screenshot("/tmp/page.png", full=True)
w, h = struct.unpack(">II", open(path, "rb").read()[16:24])   # PNG header
if max(w, h) > 1800:
    path = capture_screenshot("/tmp/page.png", full=True, max_dim=1800)
print(w, h, path)
```

## One element

`js` returns a node's `sharedId`, which BiDi can clip to:

```python
import base64
el = js("document.querySelector('#pane')")
r = bidi("browsingContext.captureScreenshot", context=current_tab()["targetId"],
         clip={"type": "element", "element": {"sharedId": el["sharedId"]}})
open("/tmp/pane.png", "wb").write(base64.b64decode(r["data"]))
```
