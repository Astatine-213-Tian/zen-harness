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

Pages with unsaved input arm it. Zen always selects a tab to show this prompt, which would pull the user's view to your background tab, so the harness never lets it open for navigations it starts:

- `goto_url(url)` and `click()` on a link first ask the page (a synthetic `beforeunload` event, no prompt). If it says it has unsaved changes, they wait up to `save_wait` seconds (default 10) for it to save. Apps like Notion stop asking once their save lands. Then they raise `UnsavedChanges`.
- `leave=True` leaves anyway and discards the changes. Either way the real prompt is switched off for that navigation.

```python
try:
    goto_url("https://example.com/")
except UnsavedChanges:
    wait(5)                                    # let the app finish saving, then retry
    goto_url("https://example.com/", leave=True)   # or discard: only if it's your own throwaway input
wait_for_load()
```

Navigations the page starts itself (`js("location.href = ...")`, a form submit, a script redirect) can still open the prompt and bring the tab forward; `wait_for_load()` then raises `DialogOpen`, and you answer with `handle_dialog(accept=True)` (leave) or `accept=False` (stay). Prefer `goto_url` for navigating.

`close_tab()` closes without asking. If the input is the user's own unsaved work, ask before discarding it.

## Dialogs while a page loads

An `alert()` during page load makes `goto_url` return early with the dialog open: `page_info()` shows it, and `handle_dialog()` lets the page finish loading.

## Not native dialogs

Cookie banners, modals and in-page "Are you sure?" boxes are ordinary DOM: find the button and `click(...)` it. For consent banners prefer the most privacy-preserving choice (reject / necessary only).
