import ast
import os
import signal
import subprocess
import time

from conftest import FIXTURE


def value(out):
    return ast.literal_eval(out)


def test_new_tab_marks_and_reports_page(page):
    info = value(page("print(page_info())"))
    assert info["url"] == FIXTURE
    assert info["title"] == "\U0001F434 Fixture"
    assert info["ph"] > info["h"]


def test_js_returns_plain_python(page):
    assert value(page("print(js('({a: [1, null, \"x\"], b: true})'))")) == {"a": [1, None, "x"], "b": True}
    assert page("print(js('return 6 * 7'))") == "42"
    assert page("print(js('await new Promise(r => setTimeout(r, 10)); return \"done\"'))") == "done"


def test_js_errors_raise(page):
    p = page("js('nope()')", check=False)
    assert p.returncode == 1 and "JS error" in p.stderr


def test_fill_input_and_click(page):
    out = page("fill_input('#name', 'Toronto'); click('#go'); print(js(\"document.getElementById('out').textContent\"))")
    assert out == "clicked:Toronto"


def test_fill_input_clears_existing_text(page):
    out = page("fill_input('#name', 'old'); fill_input('#name', 'new'); print(js(\"document.getElementById('name').value\"))")
    assert out == "new"


def test_type_text_and_press_key(page):
    out = page("click('#name'); type_text('YYZ'); press_key('Enter'); "
               "print(js(\"document.getElementById('keys').textContent\"))")
    assert out == "enter:YYZ"


def test_click_at_xy(page):
    out = page("""
box = js("(()=>{const r=document.getElementById('go').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()")
click_at_xy(box['x'], box['y'])
print(js("document.getElementById('out').textContent"))
""")
    assert out == "clicked:"


def test_scroll(page):
    assert value(page("scroll(100, 100, dy=500); wait(0.5); print(page_info()['sy'])")) > 0


def test_dialog_shows_in_page_info_and_can_be_accepted(page):
    out = page("""
click('#alert')
print(page_info())
handle_dialog(accept=True)
print(js('window.__confirmed'))
""").splitlines()
    assert value(out[0])["dialog"]["message"] == "Proceed?"
    assert out[1] == "True"


def test_dialog_opened_from_js_does_not_hang(page):
    out = page("""
print(js("document.getElementById('alert').click()"))
print(page_info()['dialog']['type'])
handle_dialog(accept=False)
print(js('window.__confirmed'))
""").splitlines()
    assert out == ["None", "confirm", "False"]


def test_upload_file(page, tmp_path):
    f = tmp_path / "ticket.txt"
    f.write_text("hi")
    out = page(f"upload_file('#file', {str(f)!r}); print(js(\"document.getElementById('file').files[0].name\"))")
    assert out == "ticket.txt"


def test_iframe_target(page):
    assert page("print(js(\"document.getElementById('inner').textContent\", target_id=iframe_target('about:srcdoc')))") \
        == "inside frame"


def test_screenshot(page, tmp_path):
    path = tmp_path / "shot.png"
    out = page(f"print(capture_screenshot({str(path)!r}, max_dim=400))")
    assert out == str(path)
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = (int(x) for x in subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                                            capture_output=True, text=True).stdout.split()[-3::2])
    assert max(w, h) <= 400


def test_tabs(page):
    tabs = value(page("print(list_tabs())"))
    cur = value(page("print(current_tab())"))
    assert cur["targetId"] in [t["targetId"] for t in tabs]
    page("t = new_tab('about:blank'); close_tab(t)")
    assert value(page("print(len(list_tabs()))")) == len(tabs)


def test_events_and_network_idle(page):
    events = value(page("print(drain_events())"))
    assert any(e["event"] == "log.entryAdded" and e["text"] == "fixture loaded" for e in events)
    assert page("print(wait_for_network_idle(timeout=5))") == "True"


def test_terminated_daemon_releases_the_session(page):
    pids = subprocess.run(["pgrep", "-f", "zen_harness.daemon"], capture_output=True, text=True).stdout.split()
    for p in pids:
        os.kill(int(p), signal.SIGTERM)
    time.sleep(1.5)
    assert page("print(js('1 + 1'))") == "2"
