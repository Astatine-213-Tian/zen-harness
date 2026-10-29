# Uploads

Set files on <input type=file> without opening the file picker; fallbacks for http(s) pages and drop zones.

## Never click the upload button

A click on "Choose file" (or on the input) opens the OS file picker in front of the user, which you can't operate (BiDi only reports `input.fileDialogOpened`). Set the files on the input directly; hidden inputs (`display: none`) and `multiple` inputs are fine:

```python
upload_file("#files", ["/abs/path/report.csv", "/abs/path/notes.txt"])   # one path or a list
print(js("[...document.querySelector('#files').files].map(f => f.name)"))
```

Paths must be absolute. Find the input with `js("[...document.querySelectorAll('input[type=file]')].map(e => e.id || e.name)")`.

## http(s) pages

Zen only creates uploaded files from outside the page when `dom.file.createInChild` is on (Firefox's automation prefs set it; the harness's default `automation_prefs = "skip"` and runtime mode don't). `upload_file` notices the resulting `InvalidStateError` and builds the files inside the page instead (a `DataTransfer` of `File`s, then `input` and `change` events), so it works on any page. That copy travels through the page, so keep it to files of a few MB.

## Drop zones without an input

Dispatch the drag events with a `DataTransfer` holding the file:

```python
import base64, json
from pathlib import Path

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
