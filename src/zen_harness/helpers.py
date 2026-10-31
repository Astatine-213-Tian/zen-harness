"""Helpers pre-imported into every zen-harness snippet.

Names follow browser-harness so the working style carries over; everything
underneath is WebDriver BiDi. Extra helpers can live in
<workspace>/agent_helpers.py.
"""
import base64
import gzip
import json
import math
import mimetypes
import os
import re
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from . import config, ipc
from .ipc import BrowserError, DialogOpen, HarnessError  # noqa: F401 (for snippets)

CFG = config.load()
INTERNAL = ("about:", "chrome:", "moz-extension:", "resource:", "view-source:")


def _send(req, timeout=60.0):
    if "meta" in req:
        req = {"agent": CFG.agent, **req}  # each agent has its own controlled tab
    return ipc.send(CFG, req, timeout=timeout)


# BiDi methods that can start a navigation; an agent's raw bidi() call to one is a navigation cause.
_MAY_NAVIGATE = {"input.performActions", "script.evaluate", "script.callFunction", "browsingContext.navigate",
                 "browsingContext.reload", "browsingContext.traverseHistory", "browsingContext.handleUserPrompt"}


def bidi(method, _timeout=30.0, **params):
    """Raw WebDriver BiDi. bidi('browsingContext.getTree'), bidi('script.evaluate', ...)."""
    return _bidi(method, _timeout, method in _MAY_NAVIGATE, **params)


def _bidi(method, _timeout=30.0, _navigates=False, **params):
    """_navigates=True marks an action that may start a navigation (a navigation cause), so
    waits watch for one; the harness's own reads leave it False."""
    return _send({"method": method, "params": params, "timeout": _timeout, "navigates": _navigates},
                 timeout=_timeout + 5).get("result", {})


def drain_events():
    """Console logs, finished requests, loads and dialogs since the last drain, all tabs."""
    return _send({"meta": "drain_events"})["events"]


def _ctx():
    ctx = _send({"meta": "current"})["context"]
    if ctx:
        return ctx
    # Never fall back to the tab the user is looking at: taking it over must be explicit.
    raise HarnessError("no tab is controlled: open one with new_tab(url), or take the tab the user "
                       "is looking at with ensure_real_tab()")


def _tab(ctx, url, title=""):
    return {"targetId": ctx, "target_id": ctx, "url": url, "title": title}


def _target_id(target):
    return (target.get("targetId") or target.get("target_id")) if isinstance(target, dict) else target


# --- JavaScript ---

_NUMBERS = {"NaN": math.nan, "-0": -0.0, "Infinity": math.inf, "-Infinity": -math.inf}


def _value(rv):
    """BiDi RemoteValue -> plain Python (like CDP's returnByValue)."""
    t, v = rv.get("type"), rv.get("value")
    if t in ("undefined", "null"):
        return None
    if t == "number":
        return _NUMBERS[v] if isinstance(v, str) else v
    if t == "bigint":
        return int(v)
    if t in ("array", "set", "nodelist", "htmlcollection"):
        return [_value(x) for x in v or []]
    if t in ("object", "map"):
        return {(k if isinstance(k, str) else str(_value(k))): _value(x) for k, x in v or []}
    if t == "regexp":
        return f"/{v['pattern']}/{v.get('flags', '')}"
    if t == "node":
        return {"node": (v or {}).get("localName") or (v or {}).get("nodeName"), "sharedId": rv.get("sharedId")}
    if t == "window":  # a frame's window: its context id works as js(..., target_id=...)
        return {"type": t, "context": (v or {}).get("context")}
    if t in ("string", "boolean", "date"):
        return v
    return {"type": t}


def _evaluate(expression, ctx, navigates=False, activate=True):
    """Run JS in ctx. navigates=True for an action that may navigate (js() from agents);
    the harness's own reads leave it False. activate=False: no user activation."""
    r = _bidi("script.evaluate", _navigates=navigates, expression=expression, target={"context": ctx},
              awaitPromise=True, resultOwnership="none", userActivation=activate,
             serializationOptions={"maxObjectDepth": 20, "maxDomDepth": 0})
    if r.get("type") == "exception":
        d = r.get("exceptionDetails", {})
        raise HarnessError(f"JS error: {d.get('text') or _value(d.get('exception', {}))}")
    return _value(r["result"])


def js(expression, target_id=None):
    """Run JS in the controlled tab (or an iframe from iframe_target()) and return the value
    of its last statement.

    The snippet runs in its own block, so `const`/`let`/`class` stay local to the call
    (share values between calls through `window.x`). Snippets with a top-level `return`
    or `await` are retried inside an async function; there, only `return` gives a value."""
    ctx = target_id or _ctx()
    try:
        return _evaluate(f"{{\n{expression}\n}}", ctx, navigates=True)
    except RuntimeError as e:
        if "return not in function" in str(e) or "await is only valid" in str(e):
            return _evaluate(f"(async () => {{\n{expression}\n}})()", ctx, navigates=True)
        raise


# Finds the first match for a CSS selector, looking inside open shadow roots too.
# --- finding elements ---

class NotFound(HarnessError):
    """No element matches the selector, or a snapshot ref is stale (take a new snapshot())."""


class NotDisplayed(HarnessError):
    """The element exists but has no box on the page to act on."""


@dataclass(frozen=True)
class _Element:
    """An element _on_element found: its context and BiDi handle, valid within one helper call."""
    ctx: str
    shared_id: str


# One finder for every helper. A selector is CSS or a snapshot ref (its data-zh-ref CSS); it
# matches in the document first, then inside open shadow roots (web components). The action
# runs in the same call, on the element found; its arguments travel as BiDi values, never
# pasted into the source.
_ON_ELEMENT_JS = """(target, displayed, ...args) => {
  let e = target;
  if (typeof target === 'string') {
    const deep = root => {
      let f = root.querySelector(target);
      if (f) return f;
      for (const h of root.querySelectorAll('*')) if (h.shadowRoot && (f = deep(h.shadowRoot))) return f;
      return null;
    };
    try { e = deep(document); } catch (err) { return ['badselector', String(err.message)]; }
  }
  if (!e) return ['notfound'];
  if (displayed) {
    const r = e.getBoundingClientRect();
    if ((!r.width && !r.height) || getComputedStyle(e).visibility === 'hidden') return ['hidden'];
  }
  return ['ok', e, (%s)(e, ...args)];
}"""

_REF = re.compile(r"@(f\d+)?e\d+")


def _local(v):
    """Python value -> BiDi argument (the reverse of _value)."""
    if isinstance(v, _Element):
        return {"sharedId": v.shared_id}
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "boolean", "value": v}
    if isinstance(v, (int, float)):
        return {"type": "number", "value": v}
    if isinstance(v, str):
        return {"type": "string", "value": v}
    if isinstance(v, (list, tuple)):
        return {"type": "array", "value": [_local(x) for x in v]}
    if isinstance(v, dict):
        return {"type": "object", "value": [[k, _local(x)] for k, x in v.items()]}
    raise TypeError(f"can't pass {type(v).__name__} to the page")


def _resolve(selector):
    """(context, what to find there). Frame refs like '@f1e3' resolve in their frame's context,
    recorded by the last snapshot(); everything else in the controlled tab."""
    ctx = _ctx()
    if not selector.startswith("@"):
        return ctx, selector
    m = _REF.fullmatch(selector)
    if not m:
        raise ValueError(f"{selector!r} is not a snapshot ref like '@e3' or '@f1e3'")
    if m[1]:
        ctx = _evaluate(f"window.__zhFrames?.{m[1]}", ctx)
        if not ctx:
            raise NotFound(f"no frame for {selector!r}; take a new snapshot()")
    return ctx, f'[data-zh-ref="{selector[1:]}"]'


def _find_and_run(target, fn, args, who, displayed, navigates):
    if isinstance(target, _Element):
        ctx, what, name = target.ctx, target, "the element"
    else:
        (ctx, what), name = _resolve(target), repr(target)
    hint = "; take a new snapshot()" if name.startswith("'@") else ""
    try:
        r = _bidi("script.callFunction", _navigates=navigates, functionDeclaration=_ON_ELEMENT_JS % fn,
                  target={"context": ctx}, arguments=[_local(what), _local(displayed), *map(_local, args)],
                  awaitPromise=True, resultOwnership="none", userActivation=navigates,
                  serializationOptions={"maxObjectDepth": 20, "maxDomDepth": 0})
    except BrowserError as e:
        if e.code in ("no such node", "no such frame"):  # its document or frame went away
            raise NotFound(f"{who}: element not found: {name}{hint}") from None
        raise
    if r.get("type") == "exception":
        d = r.get("exceptionDetails", {})
        raise HarnessError(f"{who}: JS error: {d.get('text') or _value(d.get('exception', {}))}")
    tag, *rest = _value(r["result"])
    if tag == "badselector":
        raise ValueError(f"{who}: invalid selector {name}: {rest[0]}")
    if tag == "notfound":
        raise NotFound(f"{who}: element not found: {name}{hint}")
    if tag == "hidden":
        raise NotDisplayed(f"{who}: element is not displayed: {name}")
    node, value = rest
    return _Element(ctx, node["sharedId"]), value


def _on_element(target, fn, *args, who, displayed=False, timeout=0.0, navigates=False):
    """Find `target` (CSS, a snapshot ref, or an _Element) and run the JS function `fn(el, ...args)`
    on it, in one call. Returns (element, fn's value). Raises NotFound or NotDisplayed (with
    displayed=True), ValueError for a bad selector. With timeout > 0 it keeps looking, on the new
    page if the last action navigated, until the element is there (and displayed)."""
    deadline = time.time() + timeout
    while True:
        if timeout > 0:
            _settle(_ctx(), False, max(0.0, deadline - time.time()))
        try:
            return _find_and_run(target, fn, args, who, displayed, navigates)
        except (NotFound, NotDisplayed, BrowserError):  # BrowserError: e.g. mid-navigation
            if time.time() >= deadline:
                raise
        time.sleep(0.1)


_SNAPSHOT_JS = r"""
((query, within, limit, hrefs, prefix) => {
  const ROLES = new Set(['button','link','checkbox','radio','tab','menuitem','menuitemcheckbox',
    'menuitemradio','option','switch','textbox','combobox','searchbox','slider','spinbutton','treeitem','listbox']);
  const INPUT = {checkbox:'checkbox', radio:'radio', button:'button', submit:'button', reset:'button',
    image:'button', file:'button', color:'button', search:'searchbox', number:'spinbutton', range:'slider'};
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const cut = (s, n) => s.length > n ? s.slice(0, n - 1) + '…' : s;
  const roleOf = e => {
    const r = (e.getAttribute('role') || '').split(' ')[0];
    if (ROLES.has(r)) return r;
    const t = e.tagName;
    if (t === 'A' && e.hasAttribute('href')) return 'link';
    if (t === 'BUTTON' || t === 'SUMMARY') return 'button';
    if (t === 'INPUT') { const ty = (e.type || 'text').toLowerCase(); return ty === 'hidden' ? null : (INPUT[ty] || 'textbox'); }
    if (t === 'SELECT') return e.multiple ? 'listbox' : 'combobox';
    if (t === 'TEXTAREA' || e.getAttribute('contenteditable') === 'true' || e.getAttribute('contenteditable') === '') return 'textbox';
    return null;
  };
  const nameOf = e => {
    const by = e.getAttribute('aria-labelledby');
    if (by) {
      const root = e.getRootNode().getElementById ? e.getRootNode() : document;
      const s = clean(by.split(/\s+/).map(id => root.getElementById(id)?.innerText || '').join(' '));
      if (s) return s;
    }
    if (clean(e.getAttribute('aria-label'))) return clean(e.getAttribute('aria-label'));
    if (e.labels && e.labels.length) { const s = clean([...e.labels].map(l => l.innerText).join(' ')); if (s) return s; }
    if (e.tagName === 'INPUT' && ['button', 'submit', 'reset'].includes(e.type)) return clean(e.value);
    if (!['INPUT', 'TEXTAREA', 'SELECT'].includes(e.tagName)) { const s = clean(e.innerText); if (s) return s; }
    return clean(e.getAttribute('placeholder') || e.getAttribute('title') || e.getAttribute('alt')
      || e.querySelector('img[alt]')?.alt || e.getAttribute('name'));
  };
  const shown = e => {
    const r = e.getBoundingClientRect();
    if (!r.width && !r.height) return false;
    const s = getComputedStyle(e);
    return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' && !e.closest('[aria-hidden="true"]');
  };
  const els = [];
  const walk = root => { for (const e of root.querySelectorAll('*')) { els.push(e); if (e.shadowRoot) walk(e.shadowRoot); } };
  walk(document);
  for (const e of els) if (e.hasAttribute('data-zh-ref')) e.removeAttribute('data-zh-ref');
  delete window.__zhFrames;
  const scope = within ? document.querySelector(within) : null;
  if (within && !scope) throw new Error('snapshot: nothing matches within=' + within);
  const q = (query || '').toLowerCase();
  const items = [], frames = [];
  let total = 0;
  for (const e of els) {
    if (scope && !scope.contains(e)) continue;
    if ((e.tagName === 'IFRAME' || e.tagName === 'FRAME') && e.contentWindow && shown(e)) frames.push(e.contentWindow);
    const role = roleOf(e);
    if (!role || !shown(e)) continue;
    const name = cut(nameOf(e), 80);
    const href = role === 'link' ? e.getAttribute('href') || '' : '';
    if (q && !(role + ' ' + name + (hrefs ? ' ' + href : '')).toLowerCase().includes(q)) continue;
    total++;
    if (items.length >= limit) continue;
    const ref = prefix + 'e' + (items.length + 1);
    e.setAttribute('data-zh-ref', ref);
    const extra = [];
    if (e.tagName === 'SELECT') extra.push('value="' + cut(clean(e.selectedOptions[0]?.text), 40) + '"');
    else if ('value' in e && ['textbox', 'searchbox', 'spinbutton', 'slider', 'combobox'].includes(role) && e.value)
      extra.push('value="' + (e.type === 'password' ? '•••' : cut(clean(e.value), 40)) + '"');
    if (e.checked || e.getAttribute('aria-checked') === 'true' || e.getAttribute('aria-pressed') === 'true') extra.push('checked');
    if (e.getAttribute('aria-expanded')) extra.push(e.getAttribute('aria-expanded') === 'true' ? 'expanded' : 'collapsed');
    if (e.getAttribute('aria-selected') === 'true') extra.push('selected');
    if (e.disabled || e.getAttribute('aria-disabled') === 'true') extra.push('disabled');
    if (hrefs && href) extra.push('-> ' + cut(href, 80));
    items.push([ref, role, name, extra.join(' ')]);
  }
  return {items, total, frames, url: location.href};
})
"""


def _snapshot_in(ctx, prefix, query, within, limit, hrefs):
    return _evaluate(f"{_SNAPSHOT_JS}({json.dumps(query)},{json.dumps(within)},{int(limit)},"
                     f"{json.dumps(bool(hrefs))},{json.dumps(prefix)})", ctx)


def _snapshot_line(ref, role, name, extra):
    return f'@{ref} {role} {json.dumps(name, ensure_ascii=False)}' + (f" {extra}" if extra else "")


def snapshot(query=None, within=None, limit=150, hrefs=False):
    """Compact list of the controlled tab's visible interactive elements, one per line:

        @e3 button "Star VibiumDev/vibium"
        @e7 textbox "Where from?" value="Toronto"
        # frame f1 https://js.stripe.com/v3/elements-inner-card.html
        @f1e1 textbox "Card number"

    Pass a ref like "@e3" or "@f1e1" to click / fill_input / wait_for_element /
    dispatch_key / upload_file. Refs last until the next snapshot or navigation.
    Open shadow roots and visible iframes (any origin, nested) are included; each
    frame with matches gets a "# frame fN <url>" line, then its elements.
    query: keep elements whose role or name (plus link href, with hrefs=True) contains this text.
    within: CSS selector in the top document; only it and the frames inside it are listed.
    limit: most elements to list, across all frames.
    hrefs: append link targets."""
    top = _ctx()
    r = _snapshot_in(top, "", query, within, limit, hrefs)
    lines = [_snapshot_line(*i) for i in r["items"]]
    listed, total, frames = len(lines), r["total"], {}
    todo = [w["context"] for w in r["frames"]]
    while todo:
        ctx, name = todo.pop(0), f"f{len(frames) + 1}"
        try:
            f = _snapshot_in(ctx, name, query, None, limit - listed, hrefs)
        except RuntimeError:
            continue  # the frame went away or won't run scripts
        todo[:0] = [w["context"] for w in f["frames"]]  # nested frames come right after their parent
        total += f["total"]
        if f["items"]:
            frames[name] = ctx
            listed += len(f["items"])
            url = f["url"] if len(f["url"]) <= 100 else f["url"][:99] + "…"
            lines += [f"# frame {name} {url}"] + [_snapshot_line(*i) for i in f["items"]]
    if frames:
        _evaluate(f"window.__zhFrames={json.dumps(frames)}", top)
    if total > listed:
        lines.append(f"... {total - listed} more; narrow with query= or within=")
    return "\n".join(lines) or "(no interactive elements" + (f" matching {query!r})" if query else ")")


# --- navigation and page ---

class UnsavedChanges(HarnessError):
    """The page would ask "leave page?" (a beforeunload handler) if navigated away from."""


# Zen always brings a tab to the front to show its "leave page?" prompt, so navigations the
# harness starts ask the page first, with a synthetic beforeunload event (no prompt), and then
# keep the real one from prompting.
_WANTS_TO_STAY_JS = """(()=>{
const e = document.createEvent('BeforeUnloadEvent');
e.initEvent('beforeunload', false, true);
dispatchEvent(e);
return e.defaultPrevented || !!e.returnValue;
})()"""
# Capture listeners on the window run before the page's own (non-capture) ones; only for a few
# seconds, in case the navigation doesn't unload the page (a single-page app's link).
_SKIP_PROMPT_JS = """{
window.__zhLeaveUntil = Date.now() + 5000;
if (!window.__zhLeave) {
  window.__zhLeave = e => { if (e.isTrusted && Date.now() < window.__zhLeaveUntil) e.stopImmediatePropagation(); };
  addEventListener('beforeunload', window.__zhLeave, true);
}
}"""


def _leave_page(ctx, leave=False, save_wait=10.0):
    """Get the page in `ctx` ready to be navigated away from without a "leave page?" prompt.

    A page that says it has unsaved changes gets `save_wait` seconds to save them (apps like
    Notion stop asking once saved); then UnsavedChanges, unless leave=True."""
    deadline = time.time() + save_wait
    while not leave:
        try:
            if not _evaluate(_WANTS_TO_STAY_JS, ctx, activate=False):
                break
        except RuntimeError:
            break  # no document to ask, e.g. an error page
        if time.time() > deadline:
            raise UnsavedChanges(
                "the page says it has unsaved changes (leaving would show a \"leave page?\" prompt, which "
                "brings the tab to the user's front); wait for it to save and retry, or pass leave=True "
                "to leave anyway and lose them")
        time.sleep(0.5)
    try:
        _evaluate(_SKIP_PROMPT_JS, ctx, activate=False)
    except RuntimeError:
        pass


def goto_url(url, leave=False, save_wait=10.0):
    """Navigate the controlled tab. If the page has unsaved changes (it would ask "leave
    page?"), waits up to `save_wait` s for them to save, then raises UnsavedChanges unless
    leave=True. The prompt itself never opens, so the user's view never jumps to this tab."""
    ctx = _ctx()
    _leave_page(ctx, leave, save_wait)
    r = bidi("browsingContext.navigate", context=ctx, url=url, wait="interactive", _timeout=60)
    out = {"url": r.get("url", url)}
    if os.environ.get("ZH_DOMAIN_SKILLS") == "1":
        site = (urlparse(url).hostname or "").removeprefix("www.").split(".")[0]
        d = CFG.workspace_path / "domain-skills" / site
        if d.is_dir():
            out["domain_skills"] = sorted(str(p) for p in d.rglob("*.md"))[:10]
    return out


def page_info():
    """{url, title, w, h, sx, sy, pw, ph}: viewport, scroll and page size.

    If a native dialog (alert/confirm/prompt/beforeunload) is open, returns
    {dialog: {type, message, defaultValue}} instead; answer it with handle_dialog()."""
    ctx = _ctx()
    dialog = _send({"meta": "dialog", "context": ctx}).get("dialog")
    if dialog:
        return {"dialog": dialog}
    return _evaluate("({url:location.href,title:document.title,w:innerWidth,h:innerHeight,sx:scrollX,"
                     "sy:scrollY,pw:document.documentElement.scrollWidth,"
                     "ph:document.documentElement.scrollHeight})", ctx)


def handle_dialog(accept=True, text=None):
    params = {"context": _ctx(), "accept": accept}
    if text is not None:
        params["userText"] = text
    bidi("browsingContext.handleUserPrompt", **params)


# --- input ---

_BUTTONS = {"left": 0, "middle": 1, "right": 2}
_KEYS = {
    "Enter": "", "Tab": "", "Backspace": "", "Escape": "", "Delete": "",
    "ArrowLeft": "", "ArrowUp": "", "ArrowRight": "", "ArrowDown": "",
    "Home": "", "End": "", "PageUp": "", "PageDown": "", " ": " ",
    "Shift": "", "Control": "", "Alt": "", "Meta": "",
}
_MODIFIERS = ((1, ""), (2, ""), (4, ""), (8, ""))  # Alt, Ctrl, Meta, Shift


def _perform(ctx, *sources):
    bidi("input.performActions", context=ctx, actions=list(sources))


def _click(ctx, x, y, button="left", clicks=1, background=False):
    """Click at (x, y) in `ctx`'s own viewport (a frame's context takes frame coordinates).
    background=True holds Cmd/Ctrl, so a link that opens a new tab opens it in the background."""
    b = _BUTTONS[button]
    acts = [{"type": "pointerMove", "x": round(x), "y": round(y), "origin": "viewport"}]
    for _ in range(clicks):
        acts += [{"type": "pointerDown", "button": b}, {"type": "pointerUp", "button": b}]
    sources = [{"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": acts}]
    if background:
        mod = "\ue03d" if sys.platform == "darwin" else "\ue009"  # Meta / Control
        sources.append({"type": "key", "id": "keyboard", "actions": [{"type": "keyDown", "value": mod}]
                        + [{"type": "pause"}] * (len(acts) - 1) + [{"type": "keyUp", "value": mod}]})
    _perform(ctx, *sources)


def click_at_xy(x, y, button="left", clicks=1):
    """Click at viewport coordinates (CSS pixels, as in page_info / screenshots at 1x)."""
    _click(_ctx(), x, y, button, clicks)


_CLICK_FN = """(e) => {
  e.scrollIntoView({block: 'center', inline: 'center'});
  const r = e.getBoundingClientRect();
  const a = e.closest('a[href],area[href]'), t = (a && a.target || '').toLowerCase();
  const newTab = !!t && !['_self', '_parent', '_top'].includes(t);
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, newTab,
          leaves: !!a && !newTab && !a.hasAttribute('download') && !/^(javascript|mailto|tel|sms):/i.test(a.href)
                  && a.href.split('#')[0] !== location.href.split('#')[0]};
}"""


def click(selector, timeout=0.0, leave=False, save_wait=10.0):
    """Scroll the first element matching `selector` into view and click its centre.

    A link that would open a new tab or window (target=_blank etc.) is Cmd/Ctrl-clicked,
    so the new tab opens in the background instead of switching the user's view; the
    harness keeps controlling the current tab (find the new one with list_tabs()).
    A link to another page is handled like goto_url: unsaved changes get `save_wait` s to
    save, then UnsavedChanges unless leave=True."""
    el, box = _on_element(selector, _CLICK_FN, who="click", displayed=True, timeout=timeout)
    if box["leaves"]:
        _leave_page(el.ctx, leave, save_wait)
    _click(el.ctx, box["x"], box["y"], background=box["newTab"])


def _key_actions(keys):
    acts = []
    for k in keys:
        acts += [{"type": "keyDown", "value": k}, {"type": "keyUp", "value": k}]
    return acts


def _keys(ctx, acts):
    _perform(ctx, {"type": "key", "id": "keyboard", "actions": acts})


def _text_actions(text):
    return _key_actions("" if ch == "\n" else ch for ch in text)


def _press_actions(key, modifiers=0):
    mods = [code for bit, code in _MODIFIERS if modifiers & bit]
    value = _KEYS.get(key, key)
    acts = [{"type": "keyDown", "value": m} for m in mods]
    acts += [{"type": "keyDown", "value": value}, {"type": "keyUp", "value": value}]
    return acts + [{"type": "keyUp", "value": m} for m in reversed(mods)]


def type_text(text):
    """Type into the focused element with real key events ("\\n" presses Enter)."""
    _keys(_ctx(), _text_actions(text))


def press_key(key, modifiers=0):
    """Press one key, e.g. "Enter", "Tab", "ArrowDown", "a".
    Modifiers bitfield: 1=Alt, 2=Ctrl, 4=Meta(Cmd), 8=Shift."""
    _keys(_ctx(), _press_actions(key, modifiers))


_FOCUS_FN = """(e) => {
  e.focus();
  if (e.isContentEditable) {  // put the caret at the end
    const r = document.createRange();
    r.selectNodeContents(e);
    r.collapse(false);
    getSelection().removeAllRanges();
    getSelection().addRange(r);
  }
}"""
_INPUT_CHANGE_FN = """(e) => {
  e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true}));
}"""
_KEY_EVENT_FN = """(e, type, key, code) => {
  e.focus();
  e.dispatchEvent(new KeyboardEvent(type, {key, code: key, keyCode: code, which: code, bubbles: true}));
}"""


def fill_input(selector, text, clear_first=True, timeout=0.0):
    """Fill a framework-managed input (React, Vue, ...): focus, clear, type with real
    key events, then fire input+change so the framework sees the new value."""
    el, _ = _on_element(selector, _FOCUS_FN, who="fill_input", timeout=timeout)
    if clear_first:
        _keys(el.ctx, _press_actions("a", 4 if sys.platform == "darwin" else 2))
        _keys(el.ctx, _press_actions("Backspace"))
    _keys(el.ctx, _text_actions(text))
    try:
        _on_element(el, _INPUT_CHANGE_FN, who="fill_input", navigates=True)
    except NotFound:
        pass  # the page replaced the input while it was typed into


def dispatch_key(selector, key="Enter", event="keypress"):
    """Dispatch a synthetic DOM KeyboardEvent on an element (for sites that ignore real keys)."""
    kc = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, " ": 32}.get(key, ord(key) if len(key) == 1 else 0)
    _on_element(selector, _KEY_EVENT_FN, event, key, kc, who="dispatch_key", navigates=True)


def scroll(x, y, dy=-300, dx=0):
    """Scroll whatever is under (x, y). Positive dy scrolls down."""
    ctx = _ctx()
    if _evaluate("document.visibilityState", ctx) == "visible":
        _perform(ctx, {"type": "wheel", "id": "wheel", "actions": [
            {"type": "scroll", "x": round(x), "y": round(y), "deltaX": dx, "deltaY": dy}]})
        return
    # Zen ignores wheel input in background tabs, so scroll the nearest scrollable element.
    _evaluate(f"""(()=>{{let e=document.elementFromPoint({x},{y});
      while(e&&e!==document.documentElement){{const s=getComputedStyle(e);
        if(/(auto|scroll)/.test(s.overflowY+s.overflowX)&&(e.scrollHeight>e.clientHeight||e.scrollWidth>e.clientWidth))break;
        e=e.parentElement;}}
      (e&&e!==document.documentElement?e:window).scrollBy({dx},{dy});}})()""", ctx)


_SET_FILES_FN = """(e, files) => {
  const dt = new DataTransfer();
  for (const [name, type, b64] of files)
    dt.items.add(new File([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], name, {type}));
  e.files = dt.files;
  e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true}));
}"""


def upload_file(selector, path):
    """Set files on an <input type=file>. `path` is an absolute path or a list of them."""
    el, _ = _on_element(selector, "(e) => null", who="upload_file")
    files = [path] if isinstance(path, str) else list(path)
    try:
        _bidi("input.setFiles", _navigates=True, context=el.ctx, element={"sharedId": el.shared_id}, files=files)
    except BrowserError as e:
        # Firefox can only add files from the parent process when dom.file.createInChild
        # is on (automation prefs set it); otherwise build the files inside the page.
        if "Failed to add file" not in str(e):
            raise
        payload = [[Path(f).name, mimetypes.guess_type(f)[0] or "application/octet-stream",
                    base64.b64encode(Path(f).read_bytes()).decode()] for f in files]
        _on_element(el, _SET_FILES_FN, payload, who="upload_file", navigates=True)


# --- visual ---

def capture_screenshot(path=None, full=False, max_dim=None):
    """Save a PNG of the viewport (or the whole page with full=True) and return its path.
    max_dim shrinks the image so its longest side fits, e.g. 1800 for image-aware LLMs."""
    path = str(path or CFG.run_dir / "shot.png")
    r = bidi("browsingContext.captureScreenshot", context=_ctx(),
             origin="document" if full else "viewport", _timeout=60)
    data = base64.b64decode(r["data"])
    Path(path).write_bytes(data)
    if max_dim and max(struct.unpack(">II", data[16:24])) > max_dim:  # PNG width, height
        subprocess.run(["sips", "-Z", str(max_dim), path], capture_output=True, check=True)
    return path


# --- tabs ---

def _top_contexts():
    return bidi("browsingContext.getTree", maxDepth=0)["contexts"]


def list_tabs(include_internal=True):
    tabs = [c for c in _top_contexts() if include_internal or not c["url"].startswith(INTERNAL)]
    titles = _send({"meta": "titles", "contexts": [c["context"] for c in tabs]})["titles"]
    return [_tab(c["context"], c["url"], titles.get(c["context"], "")) for c in tabs]


def current_tab():
    ctx = _ctx()
    for c in _top_contexts():
        if c["context"] == ctx:
            return _tab(ctx, c["url"], _send({"meta": "titles", "contexts": [ctx]})["titles"][ctx])
    raise HarnessError("the controlled tab is gone; call ensure_real_tab() or new_tab()")


def activate_tab(target):
    """Bring a tab to the front in Zen, and Zen in front of other apps. Leaves it there;
    prefer `with in_front():`, which puts the user's tab back afterwards."""
    ctx = _target_id(target)
    bidi("browsingContext.activate", context=ctx)
    return ctx


def _visible(ctx):
    """True if the tab is the one shown in a window that is on screen."""
    try:
        r = _bidi("script.evaluate", 1.0, expression="document.visibilityState", awaitPromise=False,
                  target={"context": ctx})
    except Exception:
        return False
    return r.get("result", {}).get("value") == "visible"


def _require_foreground(name):
    if CFG.foreground != "allow":
        raise HarnessError(
            f"{name} shows a tab or window to the user, which is off (foreground = \"never\"). "
            "Work in the background instead (read data with js()/fetch, page through URLs, scroll()); "
            "if the page truly needs to be visible, ask the user to set foreground = \"allow\" in "
            "~/.config/zen-harness/config.toml (or ZH_FOREGROUND=allow).")


@contextmanager
def in_front(target=None):
    """Show the controlled tab (or `target`) for the duration of the block, then show the
    user's tab again. Hidden tabs barely run (animation frames stop, timers fire about once
    a second, IntersectionObserver stalls), so use this for lazy loading, infinite feeds
    and animations, and keep the block short:

        with in_front():
            js("window.scrollTo(0, document.body.scrollHeight)"); wait(1)

    The user sees their Zen window switch to this tab, and Zen comes in front of the app
    they are using; afterwards their tab is back, but Zen stays the active app. If their
    window was minimized or covered, no tab was showing, so this tab stays.

    Off unless the user's config has `foreground = "allow"`."""
    _require_foreground("in_front()")
    ctx = _target_id(target) or _ctx()
    tree = _top_contexts()
    win = next((c.get("clientWindow") for c in tree if c["context"] == ctx), None)
    if _visible(ctx):
        yield ctx
        return
    prev = next((c["context"] for c in tree if c["context"] != ctx and c.get("clientWindow") == win
                 and _visible(c["context"])), None)
    activate_tab(ctx)
    try:
        yield ctx
    finally:
        if prev and any(c["context"] == prev for c in _top_contexts()):
            bidi("browsingContext.activate", context=prev)


def switch_tab(target, activate=False):
    """Make `target` the tab helpers act on, without changing Zen's visible tab by default.
    The tab-title marker moves with it so the user can see which tab is controlled."""
    ctx = _send({"meta": "set_current", "context": _target_id(target)})["context"]
    if activate:
        activate_tab(ctx)
    return ctx


def _create_tab():
    """A new background tab at the end of a normal Zen window. Zen puts new tabs in the
    newest window, which may be a popup such as new_window()'s, so with several windows
    open, place it after the last tab of the first window that isn't a popup."""
    params = {"type": "tab", "background": True}
    if len(bidi("browser.getClientWindows")["clientWindows"]) > 1:
        windows = {}
        for c in _top_contexts():
            windows.setdefault(c.get("clientWindow"), []).append(c["context"])
        for ctxs in windows.values():
            try:  # a popup's own page reports no toolbar; check one page per window
                popup = _bidi("script.evaluate", 1.0, expression="!window.toolbar.visible", awaitPromise=False,
                              target={"context": ctxs[0]})["result"].get("value")
            except Exception:
                popup = False
            if not popup:
                params["referenceContext"] = ctxs[-1]
                break
    return bidi("browsingContext.create", **params)["context"]


def new_tab(url="about:blank"):
    """Open a background tab, control it, and load `url`. Reuses the controlled tab if it is blank."""
    cur = _send({"meta": "current"})["context"]
    if cur and url != "about:blank":
        tree = {c["context"]: c["url"] for c in _top_contexts()}
        if tree.get(cur) in ("about:blank", "about:newtab", "about:home"):
            goto_url(url)
            return cur
    ctx = _create_tab()
    switch_tab(ctx)
    if url != "about:blank":
        goto_url(url)
    return ctx


_POPUP_JS = """((url, features) => {
  const b = document.createElement('button');
  b.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;opacity:0;z-index:2147483647';
  b.addEventListener('click', e => { e.stopImmediatePropagation(); b.remove(); window.open(url, '_blank', features); });
  document.documentElement.append(b);
})"""


def new_window(url="about:blank"):
    """Open a Zen window of the agent's own, control its page, and load `url`.

    Unlike a background tab, this page runs at full speed (animation frames, timers,
    IntersectionObserver, lazy loading) whenever any part of the window is on screen and
    not covered by another app's window; Zen's own windows don't count as covering. The
    user's tabs are never switched. What the user sees: a window opens over their Zen
    window, same size and place. If Zen was the active app, their window is put back in
    front so this one waits behind it; otherwise it stays on top of their Zen window,
    behind the app they are using. close_tab() closes it.

    Off unless the user's config has `foreground = "allow"`."""
    _require_foreground("new_window()")
    windows = bidi("browser.getClientWindows")["clientWindows"]
    home = next((w for w in windows if w["active"]), None) or next(
        (w for w in windows if w["state"] != "minimized"), windows[0])
    before = {c["context"] for c in _top_contexts()}
    # Pages may open windows only from a click, so click a throwaway opener tab.
    opener = _create_tab()
    try:
        _evaluate(f"{_POPUP_JS}('about:blank', 'popup,noopener,width={home['width']},height={home['height']}')", opener)
        _perform(opener, {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": [
            {"type": "pointerMove", "x": 5, "y": 5}, {"type": "pointerDown", "button": 0},
            {"type": "pointerUp", "button": 0}]})
        deadline = time.time() + 10
        while not (new := [c for c in _top_contexts() if c["context"] not in before | {opener}]):
            if time.time() > deadline:
                raise HarnessError("new_window: Zen did not open the window")
            time.sleep(0.05)
    finally:
        bidi("browsingContext.close", context=opener)
    ctx, win = new[0]["context"], new[0].get("clientWindow")
    bidi("browser.setClientWindowState", clientWindow=win, state="normal", x=home["x"], y=home["y"],
         width=home["width"], height=home["height"])
    if home["active"]:  # Zen was the active app: give the user's window its focus back
        shown = next((c["context"] for c in _top_contexts()
                      if c.get("clientWindow") == home["clientWindow"] and _visible(c["context"])), None)
        if shown:
            bidi("browsingContext.activate", context=shown)
    switch_tab(ctx)
    if url != "about:blank":
        goto_url(url)
    return ctx


def close_tab(target=None):
    ctx = _target_id(target) or _ctx()
    bidi("browsingContext.close", context=ctx)


def ensure_real_tab():
    """Control a real web tab: keep the current one if it is fine, else pick the visible one."""
    cur = _send({"meta": "current"})["context"]
    tabs = [c for c in _top_contexts() if not c["url"].startswith(INTERNAL)]
    for c in tabs:
        if c["context"] == cur:
            return _tab(cur, c["url"])
    for c in tabs:
        if _visible(c["context"]):
            switch_tab(c["context"])
            return _tab(c["context"], c["url"])
    if tabs:
        switch_tab(tabs[0]["context"])
        return _tab(tabs[0]["context"], tabs[0]["url"])
    return None


def iframe_target(url_substr):
    """Context id of the first iframe in the controlled tab whose URL contains `url_substr`.
    Pass it to js(..., target_id=...)."""
    stack = list(bidi("browsingContext.getTree", root=_ctx())["contexts"][0].get("children") or [])
    while stack:
        c = stack.pop(0)
        if url_substr in c.get("url", ""):
            return c["context"]
        stack.extend(c.get("children") or [])
    return None


# --- waiting ---

def wait(seconds=1.0):
    time.sleep(seconds)


def _settle(ctx, need_load, timeout):
    """Wait in the daemon until the tab is settled (GLOSSARY.md). True if settled, False on
    timeout; DialogOpen if a dialog blocks the tab."""
    return _send({"meta": "settle", "context": ctx, "need_load": need_load, "timeout": max(0.0, timeout)},
                 timeout=timeout + 15)["settled"]


def wait_for_load(timeout=15.0):
    """Wait until the controlled tab has finished loading. After a click or js() that
    navigates, this waits for the new page rather than returning on the old one.
    Raises DialogOpen at once if a dialog (e.g. "leave page?") blocks the tab."""
    ctx = _ctx()
    return _settle(ctx, True, timeout)


def wait_for_element(selector, timeout=10.0, visible=False):
    """Wait until an element matches `selector` (CSS or a snapshot ref; displayed too if
    visible=True). True if found. Like wait_for_load, it looks at the new page when the last
    action navigated. A malformed selector raises ValueError at once."""
    try:
        _on_element(selector, "(e) => null", who="wait_for_element", displayed=visible, timeout=timeout)
        return True
    except (NotFound, NotDisplayed, BrowserError):
        return False


def wait_for_network_idle(timeout=10.0, idle_ms=500):
    """Wait until the controlled tab has no requests in flight and none for idle_ms."""
    ctx = _ctx()
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = _send({"meta": "network", "context": ctx})
        if s["inflight"] == 0 and s["idle_ms"] >= idle_ms:
            return True
        time.sleep(0.1)
    return False


# --- no browser ---

def http_get(url, headers=None, timeout=20.0):
    """Plain HTTP GET without the browser, for public pages and APIs."""
    h = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    import urllib.request  # loaded only here: most snippets never call it
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
