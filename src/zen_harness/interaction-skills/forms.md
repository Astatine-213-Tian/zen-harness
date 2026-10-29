# Forms

Text inputs (React/Vue), native <select>, custom dropdowns, checkboxes, radios, rich-text editors.

Find the field first: `snapshot()` (where available) lists inputs with refs like `@e3`, or query labels and placeholders in `js`. The snippets below use CSS selectors.

## Text inputs

`fill_input(sel, text)` focuses, clears, types with real key events, then fires `input` and `change`. It works on React/Vue controlled inputs. `type_text(text)` types into whatever has focus (`"\n"` presses Enter).

Rich-text editors (`contenteditable`) work with `fill_input` too; it places the caret itself:

```python
fill_input("#editor", "Hello")
print(js("document.querySelector('#editor').innerText"))
```

Do **not** set `.value` from JS on a framework input: React's value tracker treats the next `input` event as "no change", so the page state keeps the old value while the box shows the new one. If you must use JS (e.g. a huge text), go through the native setter:

```python
js("""const e = document.querySelector('#city');
Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, 'Montreal');
e.dispatchEvent(new Event('input', {bubbles: true}));
return e.value""")
```

Use `HTMLTextAreaElement.prototype` for a `<textarea>`.

## Native `<select>`

The open list of a native select is browser UI, not page DOM: clicking it then pressing arrows did not change the value. Set the option by its visible text in JS and fire the events:

```python
print(js("""const s = document.querySelector('#seat');
const o = [...s.options].find(o => o.text.trim() === 'Aisle');
s.value = o.value;
s.dispatchEvent(new Event('input', {bubbles: true}));
s.dispatchEvent(new Event('change', {bubbles: true}));
return s.value"""))
```

## Custom dropdowns (role=combobox / listbox, div menus)

They are ordinary DOM: open, wait for the options, click the one you want by its text.

```python
click("#fruit")
wait_for_element("[role=option]", visible=True, timeout=5)
box = js("""const o = [...document.querySelectorAll('[role=option]')].find(e => e.textContent.trim() === 'Pear');
o.scrollIntoView({block: 'center'});
const r = o.getBoundingClientRect();
return {x: r.left + r.width / 2, y: r.top + r.height / 2}""")
click_at_xy(box["x"], box["y"])
```

Many close on blur, so don't run other clicks between opening and choosing. Searchable ones: `fill_input` the box, then wait for and click the option.

## Checkboxes and radios

`click("#agree")` toggles, so read the state rather than assuming it: `js("document.querySelector('#agree').checked")`. When the real input is hidden (`display: none`) behind a styled label, `click` on the input silently clicks the page's top-left corner instead; click its label:

```python
click("label[for=news]")
print(js("document.querySelector('#news').checked"))
```

## Verify

Read back what the form holds before submitting:

```python
print(js("Object.fromEntries(new FormData(document.querySelector('form')))"))
```

Submitting, paying or sending is the user's call: ask first.
