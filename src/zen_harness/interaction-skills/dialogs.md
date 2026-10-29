# Dialogs

alert / confirm / prompt / beforeunload: see them with page_info(), answer with handle_dialog().

The session leaves native dialogs open (nothing is auto-accepted). A `click` or `js` that opens one returns at once; the page is frozen until you answer it.

```python
click("#delete")                 # page calls confirm("Delete 3 files?")
info = page_info()
if "dialog" in info:
    print(info["dialog"])        # {'type': 'confirm', 'message': 'Delete 3 files?', 'defaultValue': None}
    handle_dialog(accept=True)   # OK; accept=False is Cancel
```

- `alert`: `handle_dialog()` closes it.
- `prompt`: `handle_dialog(text="Ada")` types the answer and presses OK; `defaultValue` shows the prefilled text.
- A `confirm` for something destructive or irreversible (delete, send, pay): ask the user before accepting it.
- While a dialog is open, `click`/`type_text`/`press_key` on that tab fail at once with "a … dialog is open"; `js(...)` and `page_info()` still answer. Check `page_info()` after any action that might open a dialog.

## beforeunload ("Leave page? Changes may not be saved")

Pages with unsaved input arm it. `goto_url` returns as soon as the prompt appears; answer it, then wait for the new page:

```python
goto_url("https://example.com/")
if page_info().get("dialog", {}).get("type") == "beforeunload":
    handle_dialog(accept=True)   # leave; accept=False stays and keeps the draft
wait_for_load()                  # the next page (or, if you stayed, the current one)
```

`close_tab()` closes without asking. If the input is the user's own unsaved work, ask before discarding it.

## Dialogs while a page loads

An `alert()` during page load makes `goto_url` return early with the dialog open: `page_info()` shows it, and `handle_dialog()` lets the page finish loading.

## Not native dialogs

Cookie banners, modals and in-page "Are you sure?" boxes are ordinary DOM: find the button and `click(...)` it. For consent banners prefer the most privacy-preserving choice (reject / necessary only).
