# Network

See what the page requested, wait for it to settle, and read the JSON behind the page.

## What happened

`drain_events()` returns everything since the last drain (all tabs): finished requests, console logs, loads, dialogs. Filter it:

```python
drain_events()                      # start clean
click("#load")
wait_for_network_idle()
for e in drain_events():
    if e["event"].startswith("network.") and e["context"] == current_tab()["targetId"]:
        print(e["method"], e["status"], e["url"], e["error"])
```

Requests show up once finished (`network.responseCompleted` / `network.fetchError`). Bodies and request ids are not included.

## Waiting

`wait_for_network_idle(timeout=10, idle_ms=500)` waits until this tab has nothing in flight and nothing new for `idle_ms`. Right after a click that fetches, it works. It can't know about requests that **haven't started yet**: a debounced search box, or a timer (slow in background tabs, see `zen-harness notes tabs`), lets it return at once while the results are still on their way. Wait for the result itself:

```python
fill_input("#search", "7")
wait_for_element("#hits:not(:empty)", timeout=10)
print(js("document.querySelector('#hits').textContent"))
```

## Reading the data

Often the cleanest source is the API the page itself calls. Find the URL in `drain_events()`, then call it from the page so cookies and auth go along:

```python
print(js("return await (await fetch('/api/items?page=2')).json()"))
```

To capture responses the page receives (POST results, one-time tokens), hook `fetch` and XHR before the action:

```python
HOOK = """if (!window.__zh_net) {
  window.__zh_net = [];
  const keep = (url, status, body) => __zh_net.push({url, status, body: String(body).slice(0, 5000)});
  const origFetch = window.fetch;
  window.fetch = async (...args) => {
    const r = await origFetch(...args);
    r.clone().text().then(b => keep(r.url, r.status, b));
    return r;
  };
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener('load', () => keep(this.responseURL, this.status, this.responseText));
    return origSend.apply(this, args);
  };
}"""
js(HOOK)
click("#xhr")
wait_for_element("#items li")
print(js("window.__zh_net"))
```

The hook dies with the page. For requests made while a page loads, install it as a preload script before navigating:

```python
pid = bidi("script.addPreloadScript", contexts=[current_tab()["targetId"]],
           functionDeclaration="() => {" + HOOK + "}")["script"]
goto_url("https://example.com/feed")
wait_for_network_idle()
print(js("window.__zh_net"))
bidi("script.removePreloadScript", script=pid)
```

Zen also supports BiDi `network.addDataCollector` + `network.getData` for response bodies, but those need request ids, which `drain_events()` doesn't expose yet.
