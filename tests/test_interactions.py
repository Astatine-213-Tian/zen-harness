"""Behaviour the interaction notes (src/zen_harness/interaction-skills) rely on."""
import ast
import subprocess
import sys

import pytest

from conftest import ROOT

NOTES = ROOT / "src/zen_harness/interaction-skills"
UPLOAD_FILE_URL = (ROOT / "tests/fixtures/upload.html").as_uri()

# Shared JS for open shadow roots, as in the shadow-dom note.
DEEP = """function zhDeep(sel, root = document) {
  const hit = root.querySelector(sel); if (hit) return hit;
  for (const el of root.querySelectorAll('*'))
    if (el.shadowRoot) { const h = zhDeep(sel, el.shadowRoot); if (h) return h; }
  return null;
}
"""

# Builds files in the page instead of input.setFiles, as in the uploads note.
SET_FILES = '''
import base64, json
from pathlib import Path
def set_files(selector, paths):
    files = [{"name": Path(p).name, "type": "text/csv", "b64": base64.b64encode(Path(p).read_bytes()).decode()}
             for p in paths]
    return js(f"""const input = document.querySelector({json.dumps(selector)}), dt = new DataTransfer();
    for (const f of {json.dumps(files)})
      dt.items.add(new File([Uint8Array.from(atob(f.b64), c => c.charCodeAt(0))], f.name, {{type: f.type}}));
    input.files = dt.files;
    input.dispatchEvent(new Event('change', {{bubbles: true}}));
    return [...input.files].map(f => f.name)""")
'''


def value(out):
    return ast.literal_eval(out)


def text(sel):
    return f"print(js(\"document.querySelector('{sel}').textContent\"))"


# --- the notes command ---

def cli(*args):
    return subprocess.run([sys.executable, "-m", "zen_harness.run", *args], capture_output=True, text=True)


def test_notes_lists_every_topic_with_a_summary():
    p = cli("notes")
    assert p.returncode == 0
    topics = sorted(f.stem for f in NOTES.glob("*.md"))
    listed = [line.split()[0] for line in p.stdout.splitlines() if line.startswith("  ")]
    assert listed == topics and len(topics) >= 10
    assert all(len(line.split(None, 1)) == 2 for line in p.stdout.splitlines() if line.startswith("  "))


def test_notes_prints_one_and_rejects_unknown():
    assert cli("notes", "dialogs").stdout == (NOTES / "dialogs.md").read_text()
    p = cli("notes", "nope")
    assert p.returncode == 2 and "dialogs" in p.stderr


def test_notes_are_short_and_titled():
    for f in NOTES.glob("*.md"):
        lines = f.read_text().splitlines()
        assert lines[0].startswith("# ") and not lines[1] and lines[2], f.name
        assert len(lines) <= 80, f.name


# --- js ---

def test_js_top_level_const_persists_but_return_and_blocks_do_not(at):
    zh = at("tabs.html")
    zh("js('const zhOnce = 1')")
    assert "redeclaration of const zhOnce" in zh("js('const zhOnce = 2')", check=False).stderr
    assert zh("print(js('const t = 6 * 7; return t')); print(js('const t = 6 * 7; return t'))") == "42\n42"
    assert zh("print(js('{ const t = 1; t }')); print(js('{ const t = 2; t }'))") == "1\n2"
    assert zh("print(js('await Promise.resolve(5)'))") == "None"


def test_js_returns_nodes_with_shared_id(at):
    node = value(at("forms.html")("print(js(\"document.querySelector('#city')\"))"))
    assert node["node"] == "input" and node["sharedId"]


# --- forms ---

def test_assigning_value_misses_react_state_but_fill_input_and_native_setter_work(at):
    zh = at("forms.html")
    zh("js(\"{const e = document.querySelector('#city'); e.value = 'Paris'; "
       "e.dispatchEvent(new Event('input', {bubbles: true}))}\")")
    assert zh(text("#state")) == ""
    zh("fill_input('#city', 'Toronto')")
    assert zh(text("#state")) == "state:Toronto"
    zh("""js(\"\"\"const e = document.querySelector('#city');
Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, 'Montreal');
e.dispatchEvent(new Event('input', {bubbles: true})); return 1\"\"\")""")
    assert zh(text("#state")) == "state:Montreal"


def test_native_select_by_visible_text(at):
    zh = at("forms.html")
    zh("""js(\"\"\"const s = document.querySelector('#seat');
s.value = [...s.options].find(o => o.text.trim() === 'Aisle').value;
s.dispatchEvent(new Event('change', {bubbles: true})); return 1\"\"\")""")
    assert zh(text("#seat-out")) == "seat:a"


def test_custom_dropdown_option_by_text(at):
    zh = at("forms.html")
    out = zh("""
click('#fruit')
assert wait_for_element('[role=option]', visible=True, timeout=5)
box = js(\"\"\"const o = [...document.querySelectorAll('[role=option]')].find(e => e.textContent.trim() === 'Pear');
const r = o.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}\"\"\")
click_at_xy(box['x'], box['y'])
""" + text("#fruit-out"))
    assert out == "fruit:Pear"


def test_hidden_checkbox_needs_its_label(at):
    zh = at("forms.html")
    assert zh("click('#news'); print(js(\"document.querySelector('#news').checked\"))") == "False"
    assert zh("click('label[for=news]'); print(js(\"document.querySelector('#news').checked\"))") == "True"


def test_contenteditable_needs_a_click_before_fill_input(at):
    zh = at("forms.html")
    read = "print(repr(js(\"document.querySelector('#editor').innerText\")))"
    assert zh("fill_input('#editor', 'one'); " + read) == "''"  # JS focus leaves no caret
    assert zh("click('#editor'); fill_input('#editor', 'one'); fill_input('#editor', 'two'); " + read) == "'two'"


# --- shadow DOM ---

def test_shadow_dom_click_type_and_closed_root(at):
    zh = at("shadow.html")
    assert "not found" in zh("click('#star')", check=False).stderr
    out = zh(f"DEEP = {DEEP!r}\n" + """
box = js(DEEP + "const e = zhDeep('#star'); const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}")
click_at_xy(box['x'], box['y'])
""" + text("#out") + """
js(DEEP + "zhDeep('#q').focus()")
type_text('zen')
""" + text("#out") + """
print(js("document.querySelector('#closed').shadowRoot"))
r = js("const r = document.querySelector('#closed').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}")
click_at_xy(r['x'], r['y'])
""" + text("#out"))
    assert out.splitlines() == ["starred", "q:zen", "None", "closed clicked"]


def test_shadow_file_input_via_shared_id(zh, tmp_path):
    f = tmp_path / "report.csv"
    f.write_text("a,b\n")
    zh(f"new_tab({UPLOAD_FILE_URL!r}); wait_for_load()")
    out = zh(f"""
el = js("document.querySelector('x-uploader').shadowRoot.querySelector('input[type=file]')")
bidi("input.setFiles", context=current_tab()["targetId"], element={{"sharedId": el["sharedId"]}}, files=[{str(f)!r}])
""" + text("#shadow-list"))
    assert out == "report.csv"


# --- dialogs and navigation ---

def test_prompt_answer_and_js_still_runs_while_open(at):
    zh = at("dialogs.html")
    out = zh("click('#prompt'); print(page_info()['dialog']); print(js('1 + 1')); handle_dialog(text='Ada'); "
             "print(js('window.__name'))").splitlines()
    assert value(out[0]) == {"type": "prompt", "message": "Your name?", "defaultValue": "guest"}
    assert out[1:] == ["2", "Ada"]


def test_beforeunload_via_js_navigation(at, site):
    zh = at("dialogs.html")
    zh("fill_input('#dirty', 'draft')")
    out = zh(f"""
js("document.documentElement.dataset.zhOld = '1'; location.href = '{site}/forms.html'")
wait(0.5)
print(page_info()['dialog']['type'])
handle_dialog(accept=True)
print(wait_for_element('html:not([data-zh-old])', timeout=15))
print(page_info()['url'])
""").splitlines()
    assert out == ["beforeunload", "True", f"{site}/forms.html"]


def test_wait_for_new_document_after_js_navigation(at):
    zh = at("forms.html")
    out = zh("""
js("window.__old = 1; document.documentElement.dataset.zhOld = '1'; location.reload()")
print(wait_for_element('html:not([data-zh-old])', timeout=15), wait_for_load())
print(js("window.__old"))
""")
    assert out.splitlines() == ["True True", "None"]


# --- tabs ---

def test_new_tab_is_hidden_and_blank_target_child_found_by_opener(at, site):
    zh = at("tabs.html")
    out = zh("""
print(js("document.visibilityState"))
me = current_tab()["targetId"]
click("#report")
wait(1)
kids = [c for c in bidi("browsingContext.getTree", maxDepth=0)["contexts"] if c.get("originalOpener") == me]
print(kids[-1]["url"])
close_tab(kids[-1]["context"])
print(current_tab()["targetId"] == me)
""").splitlines()
    assert out == ["hidden", f"{site}/frame-inner.html", "True"]


# --- iframes ---

def test_cross_origin_frame_js_and_input_through_frame_context(at):
    zh = at("frames.html")
    out = zh("""
wait(0.5)
frame = iframe_target('localhost')
print(js("document.getElementById('cross').contentDocument"))
print(js("location.origin", target_id=frame).startswith("http://localhost:"))
b = js("const r = document.querySelector('#code').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}", target_id=frame)
bidi("input.performActions", context=frame, actions=[
    {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": [
        {"type": "pointerMove", "x": round(b["x"]), "y": round(b["y"])},
        {"type": "pointerDown", "button": 0}, {"type": "pointerUp", "button": 0}]}])
bidi("input.performActions", context=frame, actions=[
    {"type": "key", "id": "keyboard", "actions": [{"type": "keyDown", "value": "4"}, {"type": "keyUp", "value": "4"}]}])
print(js("document.querySelector('#code').value", target_id=frame))
""").splitlines()
    assert out == ["None", "True", "4"]


# --- uploads ---

@pytest.mark.xfail(reason="automation_prefs=skip leaves dom.file.createInChild off: input.setFiles "
                          "fails with InvalidStateError on http(s) pages", strict=False)
def test_upload_file_on_http_page(at, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert at("upload.html")(f"upload_file('#files', {str(f)!r}); " + text("#list")) == "a.txt"


def test_upload_fallbacks_on_http_page(at, tmp_path):
    f = tmp_path / "report.csv"
    f.write_text("id,name\n1,Toronto\n")
    zh = at("upload.html")
    assert zh(SET_FILES + f"print(set_files('#files', [{str(f)!r}]))\n" + text("#list")) == "['report.csv']\nreport.csv"
    out = zh(SET_FILES + f"""
data = {{"name": "report.csv", "type": "text/csv", "b64": base64.b64encode(Path({str(f)!r}).read_bytes()).decode()}}
js(f\"\"\"const f = {{json.dumps(data)}}, dt = new DataTransfer();
dt.items.add(new File([Uint8Array.from(atob(f.b64), c => c.charCodeAt(0))], f.name, {{{{type: f.type}}}}));
const zone = document.querySelector('#drop');
for (const type of ['dragenter', 'dragover', 'drop'])
  zone.dispatchEvent(new DragEvent(type, {{{{bubbles: true, cancelable: true, dataTransfer: dt}}}}));
return true\"\"\")
wait(0.3)
""" + text("#dropped"))
    assert out == "report.csv:id,name\n1,Toronto"


def test_hidden_multiple_file_input_on_file_page(zh, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("a")
    b.write_text("b")
    zh(f"new_tab({UPLOAD_FILE_URL!r}); wait_for_load()")
    assert zh(f"upload_file('#files', [{str(a)!r}, {str(b)!r}]); " + text("#list")) == "a.txt,b.txt"


# --- downloads ---

def test_download_into_chosen_folder_then_reset(at, tmp_path):
    zh = at("downloads.html")
    out = zh(f"""
import os
folder = {str(tmp_path)!r}
bidi("browser.setDownloadBehavior", downloadBehavior={{"type": "allowed", "destinationFolder": folder}})
try:
    click("#slow")
    for _ in range(150):
        names = os.listdir(folder)
        if names and not any(n.endswith(".part") for n in names):
            break
        wait(0.2)
    click("#blob")
    for _ in range(50):
        if "notes.txt" in os.listdir(folder):
            break
        wait(0.2)
finally:
    bidi("browser.setDownloadBehavior", downloadBehavior=None)
print(sorted(os.listdir(folder)))
""")
    assert value(out) == ["archive.bin", "notes.txt"]
    assert (tmp_path / "archive.bin").stat().st_size == 10 * 65536
    assert (tmp_path / "notes.txt").read_text() == "hello from a blob\n"


def test_download_by_fetching_in_page(at):
    out = at("downloads.html")("""
import base64
b64 = js(\"\"\"const r = await fetch(document.querySelector('#csv').href);
const bytes = new Uint8Array(await r.arrayBuffer());
let s = '';
for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
return btoa(s)\"\"\")
print(repr(base64.b64decode(b64).decode()))
""")
    assert value(out) == "id,name\n1,Toronto\n"


# --- scrolling ---

def test_scroll_inner_pane_in_background_tab(at):
    out = at("scroll.html")("""
print(js("document.visibilityState"))
r = js("const r = document.querySelector('#pane').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}")
scroll(r['x'], r['y'], dy=400)
print(js("document.querySelector('#pane').scrollTop"), page_info()['sy'])
""")
    assert out.splitlines() == ["hidden", "400 0"]


# --- network ---

def test_debounced_request_wait_for_result_not_idle(at):
    zh = at("network.html")
    out = zh("fill_input('#search', '7'); print(wait_for_element('#hits:not(:empty)', timeout=10)); " + text("#hits"))
    assert out.splitlines() == ["True", "item 7.0, item 7.1, item 7.2"]


def test_fetch_and_xhr_hook_and_preload_script(at, site):
    zh = at("network.html")
    hook = """if (!window.__zh_net) {
  window.__zh_net = [];
  const keep = (url, status, body) => __zh_net.push({url, status, body: String(body).slice(0, 5000)});
  const origFetch = window.fetch;
  window.fetch = async (...args) => { const r = await origFetch(...args); r.clone().text().then(b => keep(r.url, r.status, b)); return r; };
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener('load', () => keep(this.responseURL, this.status, this.responseText));
    return origSend.apply(this, args);
  };
}"""
    out = zh(f"HOOK = {hook!r}\n" + f"""
js(HOOK)
click("#xhr"); wait_for_element("#items li")
click("#load"); wait_for_network_idle()
print([r["url"].split("?")[1] for r in js("window.__zh_net")])
pid = bidi("script.addPreloadScript", contexts=[current_tab()["targetId"]], functionDeclaration="() => {{" + HOOK + "}}")["script"]
goto_url("{site}/network.html?again")
wait_for_network_idle()
print([r["url"].split("?")[1] for r in js("window.__zh_net")])
bidi("script.removePreloadScript", script=pid)
""").splitlines()
    assert value(out[0]) == ["page=3", "page=2&ms=300"]
    assert value(out[1]) == ["page=1"]


# --- screenshots ---

def test_full_page_and_element_screenshots(at, tmp_path):
    out = at("scroll.html")(f"""
import base64, struct
size = lambda p: struct.unpack(">II", open(p, "rb").read()[16:24])
info = page_info()
print(size(capture_screenshot({str(tmp_path / 'full.png')!r}, full=True)) == (info['pw'], info['ph']))
el = js("document.querySelector('#pane')")
r = bidi("browsingContext.captureScreenshot", context=current_tab()["targetId"],
         clip={{"type": "element", "element": {{"sharedId": el["sharedId"]}}}})
open({str(tmp_path / 'pane.png')!r}, "wb").write(base64.b64decode(r["data"]))
print(size({str(tmp_path / 'pane.png')!r}))
""").splitlines()
    assert out == ["True", "(302, 152)"]


# --- cookies ---

def test_http_only_cookie_visible_to_bidi_not_to_page(at):
    zh = at("login")
    assert zh("print(js('document.cookie'))") == "theme=dark"
    out = zh("""
r = bidi("storage.getCookies", partition={"type": "context", "context": current_tab()["targetId"]})
print(sorted((c["name"], c["httpOnly"], c["value"]["value"]) for c in r["cookies"]))
""")
    assert value(out) == [("sid", True, "s3cr3t"), ("theme", False, "dark")]
