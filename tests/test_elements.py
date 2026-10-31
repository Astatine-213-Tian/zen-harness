"""Finding elements: one finder for CSS and refs, web components included, one set of errors."""
import time

from test_interactions import UPLOAD_FILE_URL


def test_upload_into_a_web_component(zh, tmp_path):
    f = tmp_path / "in-shadow.txt"
    f.write_text("x")
    zh(f"new_tab({UPLOAD_FILE_URL!r}); wait_for_load()")
    out = zh(f"upload_file('input[type=file]:not(#files)', {str(f)!r}); "
             "print(js(\"document.getElementById('shadow-list').textContent\"))")
    assert out == "in-shadow.txt"


def test_missing_elements_raise_not_found(page):
    out = page("""
for call in (lambda: dispatch_key('#nope'), lambda: click('#nope'), lambda: fill_input('#nope', 'x')):
    try:
        call()
    except NotFound as e:
        print(isinstance(e, RuntimeError), str(e).split(':')[0])
""")
    assert out.splitlines() == ["True dispatch_key", "True click", "True fill_input"]


def test_a_malformed_selector_fails_at_once(page):
    start = time.time()
    out = page("""
for call in (lambda: wait_for_element('##bad', timeout=5), lambda: click('@nope')):
    try:
        call()
    except ValueError as e:
        print('ValueError')
""")
    assert out.splitlines() == ["ValueError", "ValueError"]
    assert time.time() - start < 4


def test_values_with_quotes_reach_the_page_intact(page):
    out = page('''
js("""const b = document.createElement('button'); b.setAttribute('aria-label', 'It\\\\'s "x" {y}');
b.textContent = 'odd'; b.onclick = () => b.textContent = 'clicked'; document.body.prepend(b)""")
click('[aria-label="It\\'s \\\\"x\\\\" {y}"]')
print(js("document.querySelector('button').textContent"))
fill_input('#name', 'say "hi" {there}')
print(js("document.querySelector('#name').value"))
''')
    assert out.splitlines() == ["clicked", 'say "hi" {there}']


def test_a_stale_ref_says_to_take_a_new_snapshot(at, site):
    zh = at("tabs.html")
    out = zh(f"""
ref = snapshot().split()[0]
goto_url({site + '/forms.html'!r}); wait_for_load()
try:
    click(ref)
except NotFound as e:
    print('take a new snapshot()' in str(e))
""")
    assert out == "True"


def test_hidden_elements_are_not_displayed(page):
    out = page("""
js("const b = document.createElement('button'); b.id = 'ghost'; b.textContent = 'Ghost';"
   "b.style.visibility = 'hidden'; document.body.prepend(b)")
try:
    click('#ghost')
except NotDisplayed:
    print('not displayed')
print(wait_for_element('#ghost', timeout=0.5, visible=True), wait_for_element('#ghost', timeout=0.5))
""")
    assert out.splitlines() == ["not displayed", "False True"]


def test_click_waits_for_the_element_to_show(page):
    out = page("""
js("const b = document.createElement('button'); b.id = 'late'; b.textContent = 'Late';"
   "b.style.display = 'none'; b.onclick = () => b.textContent = 'clicked'; document.body.prepend(b);"
   "setTimeout(() => b.style.display = '', 500)")
click('#late', timeout=5)
print(js("document.getElementById('late').textContent"))
""")
    assert out == "clicked"
