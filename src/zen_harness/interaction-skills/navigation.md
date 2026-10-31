# Navigation

Know when the next page is really there: after clicks that navigate, reloads, SPA route changes.

## Waiting after a click

`goto_url(url)` returns once the new document is interactive. After a click, `press_key("Enter")` or `js("location.href = ...")` that navigates, call `wait_for_load()`. It waits for the **new** page: the daemon watches each tab's navigation events and gives an action 300 ms to start a navigation before treating the page as staying put. `wait_for_element(...)` works the same way, so it won't match an element on the page you're leaving.

```python
click("#next")
wait_for_load()
print(page_info()["url"])
```

## Reload

```python
bidi("browsingContext.reload", context=current_tab()["targetId"], wait="complete")
```

Reloading keeps form state (a ticked checkbox stays ticked); use `goto_url(...)` for a clean page.

## Single-page apps

`history.pushState` route changes fire no load at all; `page_info()["url"]` changes at once. Wait for the content: `wait_for_element(...)` or `wait_for_network_idle()` (see `zen-harness notes network`).

## Dialogs during navigation

If a page shows `alert()` while loading, the navigation returns with the dialog open, and `wait_for_load()` raises `DialogOpen` until it is answered:

```python
goto_url("https://example.com/")
info = page_info()
if "dialog" in info:
    print(info["dialog"])           # {'type': 'alert', 'message': ...}
    handle_dialog()
wait_for_load()
```

Leaving a page with unsaved changes never opens the "Leave page?" prompt from `goto_url`: it waits for the page to save, then raises `UnsavedChanges` (pass `leave=True` to discard).

More in `zen-harness notes dialogs`.
