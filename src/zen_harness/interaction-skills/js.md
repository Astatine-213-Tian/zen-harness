# js()

What js() returns, how scoping across calls works, and the errors that look mysterious.

## Return values

The value of the last expression comes back as plain Python: numbers, strings, lists, dicts, `None`. Dates become ISO strings, Maps become dicts, `window` becomes `{'type': 'window'}`. A DOM node becomes `{'node': 'input', 'sharedId': '...'}`: return the fields you need instead (`e.value`, `e.href`, `e.getBoundingClientRect()` numbers). The `sharedId` is useful for raw BiDi calls (`input.setFiles`, element screenshots).

```python
print(js("[...document.querySelectorAll('a')].slice(0, 5).map(a => ({text: a.innerText.trim(), href: a.href}))"))
```

## `return` and `await`

A snippet with a top-level `return` or `await` is retried inside an async function. Without a `return`, that function returns nothing:

```python
print(js("await Promise.resolve(5)"))          # None
print(js("return await Promise.resolve(5)"))   # 5
```

## Declarations are local to each call

Each `js()` call runs in its own block, so `const`, `let` and `class` don't leak into the page: running `js("const e = 1; e")` twice is fine, and the last statement's value comes back.

```python
print(js("const total = 6 * 7; total"))   # 42, again and again
```

Keep state you want across calls on `window` (`window.__zh_items = [...]`); it is lost when the page navigates.

## Errors

A JS exception raises `RuntimeError: JS error: <message>` in the snippet. `TypeError: ... is null` almost always means the selector matched nothing: check it with `js("!!document.querySelector('...')")`.

## Frames

`js(expr, target_id=iframe_target("part-of-frame-url"))` runs inside an iframe, including cross-origin ones (see `zen-harness notes iframes`).
