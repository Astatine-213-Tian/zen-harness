"""Helpers pre-imported into every zen-harness snippet.

Names follow browser-harness so the working style carries over; everything
underneath is WebDriver BiDi. Extra helpers can live in
<workspace>/agent_helpers.py.
"""
import base64
import gzip
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import config, ipc

CFG = config.load()
INTERNAL = ("about:", "chrome:", "moz-extension:", "resource:", "view-source:")


def _send(req, timeout=60.0):
    return ipc.send(CFG, req, timeout=timeout)


def bidi(method, _timeout=30.0, **params):
    """Raw WebDriver BiDi. bidi('browsingContext.getTree'), bidi('script.evaluate', ...)."""
    return _send({"method": method, "params": params, "timeout": _timeout},
                 timeout=_timeout + 5).get("result", {})


def drain_events():
    """Console logs, finished requests, loads and dialogs since the last drain, all tabs."""
    return _send({"meta": "drain_events"})["events"]


def _ctx():
    ctx = _send({"meta": "current"})["context"]
    if ctx:
        return ctx
    tab = ensure_real_tab()
    if not tab:
        raise RuntimeError("no tab to control; call new_tab(url) first")
    return tab["targetId"]


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
    if t in ("string", "boolean", "date"):
        return v
    return {"type": t}


def _evaluate(expression, ctx):
    r = bidi("script.evaluate", expression=expression, target={"context": ctx}, awaitPromise=True,
             resultOwnership="none", userActivation=True,
             serializationOptions={"maxObjectDepth": 20, "maxDomDepth": 0})
    if r.get("type") == "exception":
        d = r.get("exceptionDetails", {})
        raise RuntimeError(f"JS error: {d.get('text') or _value(d.get('exception', {}))}")
    return _value(r["result"])


def js(expression, target_id=None):
    """Run JS in the controlled tab (or an iframe from iframe_target()) and return the value.

    Plain expressions work as-is; snippets with a top-level `return` or `await`
    are retried inside an async function."""
    ctx = target_id or _ctx()
    try:
        return _evaluate(expression, ctx)
    except RuntimeError as e:
        if "return not in function" in str(e) or "await is only valid" in str(e):
            return _evaluate(f"(async () => {{\n{expression}\n}})()", ctx)
        raise


# Finds the first match for a CSS selector, looking inside open shadow roots too.
_DEEP = ("((s)=>{const f=r=>{let e=r.querySelector(s);if(e)return e;"
         "for(const h of r.querySelectorAll('*'))if(h.shadowRoot&&(e=f(h.shadowRoot)))return e;"
         "return null};return f(document)})")


def _ref_css(selector):
    """'@e3' -> the CSS for that snapshot ref; anything else is already CSS."""
    return f'[data-zh-ref="{selector[1:]}"]' if selector.startswith("@") else selector


def _q(selector):
    """JS expression for the element matching a CSS selector or a snapshot ref like '@e3'."""
    if selector.startswith("@"):
        return f"{_DEEP}({json.dumps(_ref_css(selector))})"
    return f"document.querySelector({json.dumps(selector)})"


_SNAPSHOT_JS = r"""
((query, within, limit, hrefs) => {
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
  const scope = within ? document.querySelector(within) : null;
  if (within && !scope) throw new Error('snapshot: nothing matches within=' + within);
  const q = (query || '').toLowerCase();
  const items = [];
  let total = 0;
  for (const e of els) {
    if (scope && !scope.contains(e)) continue;
    const role = roleOf(e);
    if (!role || !shown(e)) continue;
    const name = cut(nameOf(e), 80);
    const href = role === 'link' ? e.getAttribute('href') || '' : '';
    if (q && !(role + ' ' + name + (hrefs ? ' ' + href : '')).toLowerCase().includes(q)) continue;
    total++;
    if (items.length >= limit) continue;
    const ref = 'e' + (items.length + 1);
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
  return {items, total};
})
"""


def snapshot(query=None, within=None, limit=150, hrefs=False):
    """Compact list of the controlled tab's visible interactive elements, one per line:

        @e3 button "Star VibiumDev/vibium"
        @e7 textbox "Where from?" value="Toronto"

    Pass a ref like "@e3" to click / fill_input / wait_for_element / dispatch_key /
    upload_file. Refs last until the next snapshot or navigation.
    query: keep elements whose role or name (plus link href, with hrefs=True) contains this text.
    within: CSS selector to limit the snapshot to one part of the page.
    hrefs: append link targets. Open shadow roots are included; iframes are not."""
    r = js(f"{_SNAPSHOT_JS}({json.dumps(query)},{json.dumps(within)},{int(limit)},{json.dumps(bool(hrefs))})")
    lines = [f'@{ref} {role} {json.dumps(name, ensure_ascii=False)}' + (f" {extra}" if extra else "")
             for ref, role, name, extra in r["items"]]
    if r["total"] > len(lines):
        lines.append(f"... {r['total'] - len(lines)} more; narrow with query= or within=")
    return "\n".join(lines) or "(no interactive elements" + (f" matching {query!r})" if query else ")")


# --- navigation and page ---

def goto_url(url):
    ctx = _ctx()
    r = bidi("browsingContext.navigate", context=ctx, url=url, wait="interactive", _timeout=60)
    _mark(ctx)
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


def click_at_xy(x, y, button="left", clicks=1):
    """Click at viewport coordinates (CSS pixels, as in page_info / screenshots at 1x)."""
    b = _BUTTONS[button]
    acts = [{"type": "pointerMove", "x": round(x), "y": round(y), "origin": "viewport"}]
    for _ in range(clicks):
        acts += [{"type": "pointerDown", "button": b}, {"type": "pointerUp", "button": b}]
    _perform(_ctx(), {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"},
                      "actions": acts})


def click(selector, timeout=0.0):
    """Scroll the first element matching `selector` into view and click its centre."""
    if timeout > 0 and not wait_for_element(selector, timeout=timeout):
        raise RuntimeError(f"click: element not found: {selector!r}")
    box = js(f"(()=>{{const e={_q(selector)};if(!e)return null;"
             "e.scrollIntoView({block:'center',inline:'center'});const r=e.getBoundingClientRect();"
             "return {x:r.left+r.width/2,y:r.top+r.height/2};})()")
    if not box:
        raise RuntimeError(f"click: element not found: {selector!r}")
    click_at_xy(box["x"], box["y"])


def _key_actions(keys):
    acts = []
    for k in keys:
        acts += [{"type": "keyDown", "value": k}, {"type": "keyUp", "value": k}]
    return acts


def type_text(text):
    """Type into the focused element with real key events ("\\n" presses Enter)."""
    _perform(_ctx(), {"type": "key", "id": "keyboard",
                      "actions": _key_actions("" if ch == "\n" else ch for ch in text)})


def press_key(key, modifiers=0):
    """Press one key, e.g. "Enter", "Tab", "ArrowDown", "a".
    Modifiers bitfield: 1=Alt, 2=Ctrl, 4=Meta(Cmd), 8=Shift."""
    mods = [code for bit, code in _MODIFIERS if modifiers & bit]
    value = _KEYS.get(key, key)
    acts = [{"type": "keyDown", "value": m} for m in mods]
    acts += [{"type": "keyDown", "value": value}, {"type": "keyUp", "value": value}]
    acts += [{"type": "keyUp", "value": m} for m in reversed(mods)]
    _perform(_ctx(), {"type": "key", "id": "keyboard", "actions": acts})


def fill_input(selector, text, clear_first=True, timeout=0.0):
    """Fill a framework-managed input (React, Vue, ...): focus, clear, type with real
    key events, then fire input+change so the framework sees the new value."""
    if timeout > 0 and not wait_for_element(selector, timeout=timeout):
        raise RuntimeError(f"fill_input: element not found: {selector!r}")
    if not js(f"(()=>{{const e={_q(selector)};"
              "if(!e)return false;e.focus();return true;})()"):
        raise RuntimeError(f"fill_input: element not found: {selector!r}")
    if clear_first:
        press_key("a", 4 if sys.platform == "darwin" else 2)
        press_key("Backspace")
    type_text(text)
    js(f"(()=>{{const e={_q(selector)};if(!e)return;"
       "e.dispatchEvent(new Event('input',{bubbles:true}));"
       "e.dispatchEvent(new Event('change',{bubbles:true}));})()")


def dispatch_key(selector, key="Enter", event="keypress"):
    """Dispatch a synthetic DOM KeyboardEvent on an element (for sites that ignore real keys)."""
    kc = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, " ": 32}.get(key, ord(key) if len(key) == 1 else 0)
    js(f"(()=>{{const e={_q(selector)};if(e){{e.focus();"
       f"e.dispatchEvent(new KeyboardEvent({json.dumps(event)},{{key:{json.dumps(key)},"
       f"code:{json.dumps(key)},keyCode:{kc},which:{kc},bubbles:true}}));}}}})()")


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


def upload_file(selector, path):
    """Set files on an <input type=file>. `path` is an absolute path or a list of them."""
    ctx = _ctx()
    nodes = bidi("browsingContext.locateNodes", context=ctx,
                 locator={"type": "css", "value": _ref_css(selector)}, maxNodeCount=1)["nodes"]
    if not nodes:
        raise RuntimeError(f"upload_file: no element for {selector!r}")
    bidi("input.setFiles", context=ctx, element={"sharedId": nodes[0]["sharedId"]},
         files=[path] if isinstance(path, str) else list(path))


# --- visual ---

def capture_screenshot(path=None, full=False, max_dim=None):
    """Save a PNG of the viewport (or the whole page with full=True) and return its path.
    max_dim shrinks the image so its longest side fits, e.g. 1800 for image-aware LLMs."""
    path = str(path or CFG.run_dir / "shot.png")
    r = bidi("browsingContext.captureScreenshot", context=_ctx(),
             origin="document" if full else "viewport", _timeout=60)
    Path(path).write_bytes(base64.b64decode(r["data"]))
    if max_dim:
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
    raise RuntimeError("the controlled tab is gone; call ensure_real_tab() or new_tab()")


def _mark(ctx):
    if CFG.tab_marker:
        m = json.dumps(CFG.tab_marker + " ")
        try:
            _evaluate(f"if(!document.title.startsWith({m}))document.title={m}+document.title", ctx)
        except Exception:
            pass


def _unmark(ctx):
    if CFG.tab_marker and ctx:
        m = json.dumps(CFG.tab_marker + " ")
        try:
            _evaluate(f"if(document.title.startsWith({m}))document.title=document.title.slice({m}.length)", ctx)
        except Exception:
            pass


def activate_tab(target):
    """Bring a tab to the front in Zen. Only when the user asks or a page stalls in the background."""
    ctx = _target_id(target)
    bidi("browsingContext.activate", context=ctx)
    return ctx


def switch_tab(target, activate=False):
    """Make `target` the tab helpers act on, without changing Zen's visible tab by default.
    The tab-title marker moves with it so the user can see which tab is controlled."""
    ctx = _target_id(target)
    old = _send({"meta": "current"})["context"]
    if old and old != ctx:
        _unmark(old)
    _send({"meta": "set_current", "context": ctx})
    _mark(ctx)
    if activate:
        activate_tab(ctx)
    return ctx


def new_tab(url="about:blank"):
    """Open a background tab, control it, and load `url`. Reuses the controlled tab if it is blank."""
    cur = _send({"meta": "current"})["context"]
    if cur and url != "about:blank":
        tree = {c["context"]: c["url"] for c in _top_contexts()}
        if tree.get(cur) in ("about:blank", "about:newtab", "about:home"):
            goto_url(url)
            return cur
    ctx = bidi("browsingContext.create", type="tab", background=True)["context"]
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
        try:
            r = bidi("script.evaluate", expression="document.visibilityState", awaitPromise=False,
                     target={"context": c["context"]}, _timeout=1.0)
        except Exception:
            continue
        if r.get("result", {}).get("value") == "visible":
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


def wait_for_load(timeout=15.0):
    """Poll document.readyState == 'complete' or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if js("document.readyState") == "complete":
                return True
        except RuntimeError:
            pass  # mid-navigation
        time.sleep(0.2)
    return False


def wait_for_element(selector, timeout=10.0, visible=False):
    """Poll until querySelector(selector) exists (and is visible if asked). True if found."""
    check = (f"(()=>{{const e={_q(selector)};if(!e)return false;"
             + ("const r=e.getBoundingClientRect();const s=getComputedStyle(e);"
                "return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';"
                if visible else "return true;") + "})()")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if js(check):
                return True
        except RuntimeError:
            pass
        time.sleep(0.2)
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
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
