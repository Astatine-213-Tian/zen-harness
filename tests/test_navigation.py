"""wait_for_load / wait_for_element after actions that navigate (#1), js() scoping (#2), and
leaving pages with unsaved changes without a prompt that would show the tab (#10, #11)."""
import time


def test_wait_for_load_after_click_waits_for_the_new_page(at, site):
    zh = at("tabs.html")
    zh(f"js(\"document.getElementById('next').href = {site + '/slow.html?ms=800'!r}\")")
    out = zh("click('#next'); print(wait_for_load(), js('document.title'))")
    assert out == "True \U0001F916 Slow page"  # re-marked after the navigation


def test_wait_for_load_after_js_navigation(at, site):
    zh = at("tabs.html")
    out = zh(f"js(\"location.href = {site + '/slow.html?ms=600'!r}\"); print(wait_for_load(), js('document.title'))")
    assert out == "True \U0001F916 Slow page"  # re-marked after the navigation


def test_wait_for_element_looks_at_the_new_page(at, site):
    # Both pages have an <a>; without navigation tracking the old page's link would match.
    zh = at("tabs.html")
    zh(f"js(\"document.getElementById('next').href = {site + '/slow.html?ms=600'!r}\")")
    out = zh("click('#next'); print(wait_for_element('a', timeout=10), js('document.title'))")
    assert out == "True \U0001F916 Slow page"  # re-marked after the navigation


def test_wait_for_load_is_quick_when_nothing_navigates(page):
    start = time.time()
    assert page("click('#name'); type_text('x'); print(wait_for_load())") == "True"
    assert time.time() - start < 3


def test_wait_for_load_returns_when_beforeunload_is_declined(at, site):
    zh = at("dialogs.html")
    out = zh(f"""
click('#dirty'); type_text('x')
js("location.href = {site + '/forms.html'!r}")
print(page_info()['dialog']['type'])
handle_dialog(accept=False)
print(wait_for_load(timeout=5), page_info()['url'].endswith('/dialogs.html'))
""")
    assert out.splitlines() == ["beforeunload", "True True"]


def test_goto_url_with_unsaved_changes_raises_instead_of_prompting(at, site):
    zh = at("dialogs.html")
    out = zh(f"""
fill_input('#dirty', 'draft')
try:
    goto_url({site + '/forms.html'!r}, save_wait=1)
except UnsavedChanges as e:
    print('raised')
print(page_info().get('dialog'), page_info()['url'].endswith('/dialogs.html'), js('document.visibilityState'))
""")
    assert out.splitlines() == ["raised", "None True hidden"]


def test_goto_url_leave_discards_without_prompting(at, site):
    zh = at("dialogs.html")
    out = zh(f"""
fill_input('#dirty', 'draft')
goto_url({site + '/forms.html'!r}, leave=True); wait_for_load()
print(page_info()['url'].endswith('/forms.html'), js('document.visibilityState'))
""")
    assert out == "True hidden"


def test_goto_url_waits_for_the_page_to_save(at, site):
    zh = at("dialogs.html")
    out = zh(f"""
import time
fill_input('#dirty', 'draft'); click('#save')
t = time.time(); goto_url({site + '/forms.html'!r}); wait_for_load()
print(page_info()['url'].endswith('/forms.html'), time.time() - t > 0.8, js('document.visibilityState'))
""")
    assert out == "True True hidden"


def test_click_on_a_link_with_unsaved_changes(at, site):
    zh = at("dialogs.html")
    out = zh("""
fill_input('#dirty', 'draft')
try:
    click('#away', save_wait=1)
except UnsavedChanges:
    print('raised')
click('#away', leave=True); wait_for_load()
print(page_info()['url'].endswith('/forms.html'), js('document.visibilityState'))
""")
    assert out.splitlines() == ["raised", "True hidden"]


def test_wait_for_load_fails_fast_while_a_dialog_is_open(at, site):
    # The page's own navigation (not one the harness starts) still prompts.
    zh = at("dialogs.html")
    out = zh(f"""
import time
fill_input('#dirty', 'draft')
js("location.href = {site + '/forms.html'!r}"); wait(0.5)
t = time.time()
try:
    wait_for_load()
except DialogOpen as e:
    print('beforeunload' in str(e), time.time() - t < 2)
handle_dialog(accept=False)
""")
    assert out == "True True"


def test_a_dialog_from_a_frame_shows_on_its_tab(at, site):
    zh = at("frames.html")
    out = zh(f"""
f = iframe_target({site + '/frame-inner.html'!r})
js("setTimeout(() => alert('from frame'), 50)", target_id=f)
for _ in range(50):
    if 'dialog' in page_info(): break
    wait(0.1)
print(page_info().get('dialog', {{}}).get('message'))
handle_dialog()
""")
    assert out == "from frame"


def test_a_click_into_a_frame_that_opens_a_dialog_returns_at_once(at, site):
    # The click goes to the tab; Zen reports the dialog on the frame.
    zh = at("frames.html")
    out = zh(f"""
import time
f = iframe_target({site + '/frame-inner.html'!r})
js("const b = document.createElement('button'); b.id = 'hi'; b.textContent = 'Hi';"
   "b.onclick = () => alert('hi from frame'); document.body.prepend(b)", target_id=f)
fx, fy = js("const r = document.getElementById('same').getBoundingClientRect(); [r.left, r.top]")
bx, by = js("const r = document.getElementById('hi').getBoundingClientRect();"
            "[r.left + r.width / 2, r.top + r.height / 2]", target_id=f)
t = time.time()
click_at_xy(fx + bx, fy + by)
print(time.time() - t < 5, page_info().get('dialog', {{}}).get('message'))
handle_dialog()
""")
    assert out == "True hi from frame"


def test_js_declarations_stay_local_to_each_call(page):
    assert page("print(js('const x = 41; x + 1'))") == "42"
    assert page("print(js('const x = 1; let y = 2; class C {}; x + y'))") == "3"
    assert page("print(js('window.shared = 5; shared'), js('shared * 2'))") == "5 10"


def test_js_return_and_await_still_work(page):
    assert page("print(js('const a = 2; return a * 3'))") == "6"
    assert page("print(js('const v = await Promise.resolve(7); return v'))") == "7"
    assert page("print(js('({a: 1})'), js('[1, 2].map(n => n * 2)'))") == "{'a': 1} [2, 4]"
