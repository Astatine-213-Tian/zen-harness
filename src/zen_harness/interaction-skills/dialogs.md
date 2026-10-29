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
- While a dialog is open, `click`/`type_text`/`press_key` on that tab hang for 30 s and then fail; `js(...)` and `page_info()` still answer. Check `page_info()` after any action that might open a dialog.

## beforeunload ("Leave page? Changes may not be saved")

Pages with unsaved input arm it. `goto_url` then hangs for 60 s (the prompt blocks the navigation). Leave with JS and answer the prompt:

```python
js("document.documentElement.dataset.zhOld = '1'; location.href = 'https://example.com/'")
wait(0.5)
if page_info().get("dialog", {}).get("type") == "beforeunload":
    handle_dialog(accept=True)   # leave; accept=False stays and keeps the draft
wait_for_element("html:not([data-zh-old])", timeout=15)   # the next page has arrived
```

`close_tab()` closes without asking. If the input is the user's own unsaved work, ask before discarding it.

## Dialogs while a page loads

An `alert()` during page load also makes `goto_url` hang for 60 s. After the timeout `page_info()` shows the dialog and `handle_dialog()` lets the page finish. To avoid the wait, navigate with `js("location.href = ...")` as above.

## Not native dialogs

Cookie banners, modals and in-page "Are you sure?" boxes are ordinary DOM: find the button and `click(...)` it. For consent banners prefer the most privacy-preserving choice (reject / necessary only).
