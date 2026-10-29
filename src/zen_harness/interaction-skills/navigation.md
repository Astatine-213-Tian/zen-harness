# Navigation

Know when the next page is really there: after clicks that navigate, reloads, SPA route changes.

## goto_url waits; clicks don't

`goto_url(url)` returns once the new document is interactive. A click (or `js("location.href = ...")`) that navigates returns at once, and `wait_for_load()` right after it can see the **old** page, which is still `complete`. After `js("location.reload()")` on a fixture it returned in 2 ms with the old document 5 times out of 5, and the next `click` failed with `NS_ERROR_FAILURE`.

Mark the old document, then wait for a document without the mark:

```python
js("document.documentElement.dataset.zhOld = '1'")
click("#next")
wait_for_element("html:not([data-zh-old])", timeout=15)
wait_for_load()
print(page_info()["url"])
```

Simpler when you know what the next page shows: `wait_for_element("<selector only the next page has>")`.

## Reload

```python
bidi("browsingContext.reload", context=current_tab()["targetId"], wait="complete")
```

Reloading keeps form state (a ticked checkbox stays ticked); use `goto_url(...)` for a clean page.

## Single-page apps

`history.pushState` route changes fire no load at all; `page_info()["url"]` changes at once. Wait for the content: `wait_for_element(...)` or `wait_for_network_idle()` (see `zen-harness notes network`).

## Dialogs during navigation

If a page shows `alert()` while loading, or a `beforeunload` "Leave page?" prompt when you navigate away, `goto_url` blocks for 60 s and then raises `browsingContext.navigate got no answer`. Navigate with JS instead, then check for a dialog:

```python
js("document.documentElement.dataset.zhOld = '1'; location.href = 'https://example.com/'")
wait(1)
info = page_info()
if "dialog" in info:
    print(info["dialog"])           # {'type': 'beforeunload', 'message': ...}
    handle_dialog(accept=True)      # accept=False stays on the page
wait_for_element("html:not([data-zh-old])", timeout=15)
wait_for_load()
```

More in `zen-harness notes dialogs`.
