# Cookies and storage

Read cookies (HttpOnly too) with storage.getCookies, and localStorage/sessionStorage with js.

These are the user's real sessions. Read only what the task needs, never print session tokens in full, and never send them anywhere outside the browser.

## Cookies

`document.cookie` misses `HttpOnly` cookies (usually the session). BiDi sees all of them. Scope the query to the controlled tab's site, otherwise you get every cookie in the browser:

```python
r = bidi("storage.getCookies", partition={"type": "context", "context": current_tab()["targetId"]})
for c in r["cookies"]:
    print(c["name"], c["domain"], c["httpOnly"], c["value"]["value"][:4] + "...")
```

Or filter by name or domain: `bidi("storage.getCookies", filter={"name": "theme", "domain": "127.0.0.1"})`. Values come as `{"type": "string", "value": ...}`.

Set and delete (e.g. a language or consent preference the site reads):

```python
bidi("storage.setCookie", cookie={"name": "lang", "value": {"type": "string", "value": "en"},
                                  "domain": "127.0.0.1", "path": "/"})
print(js("document.cookie"))
bidi("storage.deleteCookies", filter={"name": "lang", "domain": "127.0.0.1"})
```

Deleting session cookies signs the user out: ask first.

To call a site's API with the user's session, use `fetch` inside the page (see `zen-harness notes network`) rather than copying cookies into `http_get`.

## localStorage and sessionStorage

Per origin, from the page:

```python
print(js("Object.fromEntries(Object.entries(localStorage))"))
print(js("({...sessionStorage})"))
js("localStorage.setItem('draft', JSON.stringify({a: 1}))")
```

For another origin, open a tab on it first. Iframes have their own storage: `js(..., target_id=iframe_target(...))`.
