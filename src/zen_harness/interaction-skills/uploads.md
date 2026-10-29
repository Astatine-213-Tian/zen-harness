# Uploads

Set files on <input type=file> without opening the file picker; fallbacks for http(s) pages and drop zones.

## Never click the upload button

A click on "Choose file" (or on the input) opens the OS file picker in front of the user, which you can't operate (BiDi only reports `input.fileDialogOpened`). Set the files on the input directly; hidden inputs (`display: none`) and `multiple` inputs are fine:

```python
upload_file("#files", ["/abs/path/report.csv", "/abs/path/notes.txt"])   # one path or a list
print(js("[...document.querySelector('#files').files].map(f => f.name)"))
```

Paths must be absolute. Find the input with `js("[...document.querySelectorAll('input[type=file]')].map(e => e.id || e.name)")`.

## `InvalidStateError` on http(s) pages

With the default `automation_prefs = "skip"`, Zen won't create files inside web-page processes, so on http(s) pages `upload_file` fails with `unsupported operation: Failed to add file ... (InvalidStateError ...)`; only file:// pages work. (Firefox's automation prefs set `dom.file.createInChild = true`, which fixes it.) Without touching prefs, build the files in the page instead; fine for files up to a few MB:

```python
import base64, json, mimetypes
from pathlib import Path

def set_files(selector, paths):
    files = [{"name": Path(p).name, "type": mimetypes.guess_type(p)[0] or "application/octet-stream",
              "b64": base64.b64encode(Path(p).read_bytes()).decode()} for p in paths]
    return js(f"""const input = document.querySelector({json.dumps(selector)}), dt = new DataTransfer();
    for (const f of {json.dumps(files)})
      dt.items.add(new File([Uint8Array.from(atob(f.b64), c => c.charCodeAt(0))], f.name, {{type: f.type}}));
    input.files = dt.files;
    input.dispatchEvent(new Event('input', {{bubbles: true}}));
    input.dispatchEvent(new Event('change', {{bubbles: true}}));
    return [...input.files].map(f => f.name)""")

print(set_files("#files", ["/abs/path/report.csv"]))
```

## Drop zones without an input

Dispatch the drag events with a `DataTransfer` holding the file (imports as above):

```python
f = Path("/abs/path/report.csv")
data = {"name": f.name, "type": "text/csv", "b64": base64.b64encode(f.read_bytes()).decode()}
js(f"""const f = {json.dumps(data)}, dt = new DataTransfer();
dt.items.add(new File([Uint8Array.from(atob(f.b64), c => c.charCodeAt(0))], f.name, {{type: f.type}}));
const zone = document.querySelector('#drop');
for (const type of ['dragenter', 'dragover', 'drop'])
  zone.dispatchEvent(new DragEvent(type, {{bubbles: true, cancelable: true, dataTransfer: dt}}));
return true""")
```

Then confirm the page took it (a file name in a list, a progress bar). Inputs inside a shadow root: see `zen-harness notes shadow-dom`.
