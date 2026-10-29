"""wait_for_load / wait_for_element after actions that navigate (#1), and js() scoping (#2)."""
import time


def test_wait_for_load_after_click_waits_for_the_new_page(at, site):
    zh = at("tabs.html")
    zh(f"js(\"document.getElementById('next').href = {site + '/slow.html?ms=800'!r}\")")
    out = zh("click('#next'); print(wait_for_load(), js('document.title'))")
    assert out == "True Slow page"


def test_wait_for_load_after_js_navigation(at, site):
    zh = at("tabs.html")
    out = zh(f"js(\"location.href = {site + '/slow.html?ms=600'!r}\"); print(wait_for_load(), js('document.title'))")
    assert out == "True Slow page"


def test_wait_for_element_looks_at_the_new_page(at, site):
    # Both pages have an <a>; without navigation tracking the old page's link would match.
    zh = at("tabs.html")
    zh(f"js(\"document.getElementById('next').href = {site + '/slow.html?ms=600'!r}\")")
    out = zh("click('#next'); print(wait_for_element('a', timeout=10), js('document.title'))")
    assert out == "True Slow page"


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


def test_js_declarations_stay_local_to_each_call(page):
    assert page("print(js('const x = 41; x + 1'))") == "42"
    assert page("print(js('const x = 1; let y = 2; class C {}; x + y'))") == "3"
    assert page("print(js('window.shared = 5; shared'), js('shared * 2'))") == "5 10"


def test_js_return_and_await_still_work(page):
    assert page("print(js('const a = 2; return a * 3'))") == "6"
    assert page("print(js('const v = await Promise.resolve(7); return v'))") == "7"
    assert page("print(js('({a: 1})'), js('[1, 2].map(n => n * 2)'))") == "{'a': 1} [2, 4]"
