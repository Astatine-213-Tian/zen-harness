"""snapshot() inside iframes: same-origin, cross-origin (localhost vs 127.0.0.1), nested."""
import pytest

OUT = "document.querySelector('#out').textContent"


@pytest.fixture
def frames_page(at, site):
    zh = at("snapshot-frames.html")
    port = site.rsplit(":", 1)[1]
    return zh, f"http://127.0.0.1:{port}", f"http://localhost:{port}"


def test_lists_frame_controls_after_the_top_document(frames_page):
    zh, same, cross = frames_page
    assert zh("print(snapshot())").splitlines() == [
        '@e1 button "Top"',
        '@e2 button "After frames"',
        f"# frame f1 {same}/frame-inner.html",
        '@f1e1 textbox "Code"',
        '@f1e2 button "OK"',
        f"# frame f2 {cross}/frame-inner.html?cross=1",
        '@f2e1 textbox "Code"',
        '@f2e2 button "OK"',
        f"# frame f3 {cross}/frame-outer.html",
        '@f3e1 link "Outer link"',
        '@f3e2 button "Attach"',
        f"# frame f4 {cross}/frame-inner.html?nested=1",
        '@f4e1 textbox "Code"',
        '@f4e2 button "OK"',
    ]


def test_query_and_limit_span_frames(frames_page):
    zh, same, cross = frames_page
    assert zh("print(snapshot('ok'))").splitlines() == [
        f"# frame f1 {same}/frame-inner.html", '@f1e1 button "OK"',
        f"# frame f2 {cross}/frame-inner.html?cross=1", '@f2e1 button "OK"',
        f"# frame f3 {cross}/frame-inner.html?nested=1", '@f3e1 button "OK"',
    ]
    assert zh("print(snapshot(limit=3))").splitlines() == [
        '@e1 button "Top"', '@e2 button "After frames"',
        f"# frame f1 {same}/frame-inner.html", '@f1e1 textbox "Code"',
        "... 7 more; narrow with query= or within=",
    ]
    assert zh("print(snapshot(within='body > button'))") == '@e1 button "Top"'


@pytest.mark.parametrize("ref,frame", [("f1", "frame-inner.html"), ("f2", "cross=1"), ("f4", "nested=1")])
def test_frame_refs_work_with_click_and_fill_input(frames_page, ref, frame):
    zh, _, _ = frames_page
    out = zh(f"""
snapshot()
fill_input('@{ref}e1', 'old')
fill_input('@{ref}e1', '42')
click('@{ref}e2')
print(js({OUT!r}, target_id=iframe_target({frame!r})))
""")
    assert out == "ok:42"


def test_frame_refs_with_wait_dispatch_key_and_upload(frames_page, tmp_path):
    zh, _, _ = frames_page
    (tmp_path / "a.txt").write_text("x")
    out = zh(f"""
snapshot()
upload_file('@f3e2', {str(tmp_path / "a.txt")!r})
print(js("document.querySelector('#files').files[0].name + ' ' + document.title", target_id=iframe_target('outer')))""" + """
print(wait_for_element('@f2e1', timeout=2, visible=True), wait_for_element('@f2e9', timeout=0.3))
f = iframe_target('cross=1')
js("document.querySelector('#code').addEventListener('keydown', e => document.querySelector('#out').textContent = 'key:' + e.key)", target_id=f)
dispatch_key('@f2e1', 'Enter', 'keydown')
print(js("document.querySelector('#out').textContent", target_id=f))
""").splitlines()
    assert out == ["a.txt a.txt", "True False", "key:Enter"]


def test_new_snapshot_drops_old_frame_refs(frames_page):
    zh, _, _ = frames_page
    out = zh("""
snapshot()
snapshot('top')
print(wait_for_element('@f1e1', timeout=0.5))
f = iframe_target('cross=1')
print(js("document.querySelectorAll('[data-zh-ref]').length", target_id=f))
try:
    click('@f2e2')
except RuntimeError as e:
    print(e)
""").splitlines()
    assert out == ["False", "0", "no frame for '@f2e2'; take a new snapshot()"]


def test_page_without_frames_sets_no_frame_map(at):
    zh = at("forms.html")
    assert zh("snapshot(); print(js('window.__zhFrames'))") == "None"


def test_wait_for_load_after_a_frame_click_navigates_the_tab(zh, site):
    zh(f"new_tab({site + '/snapshot-frames.html'!r}); wait_for_load()")
    out = zh(f"""
f = iframe_target('frame-inner.html')
js("const a = document.createElement('a'); a.href = {site + '/slow.html?ms=600'!r}; a.target = '_top';"
   "a.textContent = 'Go top'; document.body.append(a)", target_id=f)
ref = snapshot('go top').splitlines()[-1].split()[0]
click(ref)
print(wait_for_load(), js('document.title'))
""")
    assert out == "True \U0001F916 Slow page"  # re-marked after the navigation
