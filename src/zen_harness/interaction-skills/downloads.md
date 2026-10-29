# Downloads

Get a file the page offers: fetch it yourself, or let Zen download it into a folder you choose.

## 1. Fetch it (no browser settings touched)

If the link has a real `href`, fetch it from inside the page, so the user's cookies go along, and save the bytes:

```python
import base64, json, tempfile
from pathlib import Path

href = js("document.querySelector('#csv').href")
b64 = js(f"""const r = await fetch({json.dumps(href)});
const bytes = new Uint8Array(await r.arrayBuffer());
let s = '';
for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
return btoa(s)""")
out = Path(tempfile.mkdtemp()) / "report.csv"
out.write_bytes(base64.b64decode(b64))
print(out, out.stat().st_size)
```

Public files need no browser at all: `http_get(url)` (text) or `curl -o`.

## 2. Let Zen download it

For blob links, POST forms, or JS-generated files. WebDriver BiDi in Zen 1.23.4b supports `browser.setDownloadBehavior` and the `downloadWillBegin` / `downloadEnd` events. Point downloads at a fresh empty folder, click, wait until no `.part` file remains, then **reset** the behaviour: it applies to the whole browser, the user's own downloads included, until reset or until the session ends.

```python
import os, tempfile

folder = tempfile.mkdtemp(prefix="zh-dl-")
bidi("browser.setDownloadBehavior", downloadBehavior={"type": "allowed", "destinationFolder": folder})
try:
    click("#slow")
    for _ in range(300):                      # up to 60 s
        names = os.listdir(folder)
        if names and not any(n.endswith(".part") for n in names):
            break
        wait(0.2)
finally:
    bidi("browser.setDownloadBehavior", downloadBehavior=None)
print([os.path.join(folder, n) for n in os.listdir(folder)])
```

While it downloads, the folder holds an empty `archive.bin` plus `archive.<random>.bin.part`. Zen renames instead of overwriting (`report(1).csv`), which is why a fresh folder per download helps. `{"type": "denied"}` blocks downloads.

## Events

The daemon doesn't subscribe to download events by default. After `bidi("session.subscribe", events=["browsingContext.downloadWillBegin", "browsingContext.downloadEnd"])` (once per session), `drain_events()` lists them, but only with their `url`: the file name, status (`complete` / `canceled`) and path are dropped, so check the folder for those.
