from pathlib import Path

import pytest

SNAPSHOT_PAGE = (Path(__file__).parent / "fixtures/snapshot.html").resolve().as_uri()


@pytest.fixture
def snap_page(zh):
    zh(f"new_tab({SNAPSHOT_PAGE!r}); wait_for_load()")
    return zh


def test_lists_visible_controls_with_roles_names_and_state(snap_page):
    lines = snap_page("print(snapshot())").splitlines()
    assert lines == [
        '@e1 link "Docs"',
        '@e2 link "Pricing"',
        '@e3 textbox "Leaving from" value="Toronto"',
        '@e4 textbox "Going to"',
        '@e5 textbox "Password" value="•••"',
        '@e6 checkbox "Direct flights only" checked',
        '@e7 combobox "Cabin" value="Business"',
        '@e8 button "Search"',
        '@e9 button "Swap origin and destination"',
        '@e10 button "Book" disabled',
        '@e11 button "More filters" collapsed',
        '@e12 button "Shadow action"',
    ]


def test_query_within_limit_and_hrefs(snap_page):
    assert snap_page("print(snapshot('pricing', hrefs=True))") == '@e1 link "Pricing" -> https://example.com/pricing'
    assert snap_page("print(snapshot('example.com'))") == "(no interactive elements matching 'example.com')"
    assert snap_page("print(snapshot('example.com', hrefs=True))").startswith('@e1 link "Pricing"')
    assert snap_page("print(snapshot(within='nav'))").splitlines() == ['@e1 link "Docs"', '@e2 link "Pricing"']
    assert snap_page("print(snapshot(limit=2))").splitlines()[-1] == "... 10 more; narrow with query= or within="
    assert snap_page("print(snapshot('nope'))") == "(no interactive elements matching 'nope')"


def test_refs_work_with_selector_helpers(snap_page):
    out = snap_page("""
snapshot()
fill_input('@e4', 'Vancouver')
click('@e8')
print(js("document.getElementById('to').value"), js("document.getElementById('search-btn').textContent"))
""")
    assert out == "Vancouver Searching"


def test_refs_reach_into_shadow_dom(snap_page):
    out = snap_page("""
snapshot('shadow')
click('@e1')
print(js("document.querySelector('custom-widget').shadowRoot.getElementById('inner').textContent"))
""")
    assert out == "Shadow clicked"


def test_each_snapshot_renumbers(snap_page):
    out = snap_page("""
snapshot()
print(snapshot('search'))
print(wait_for_element('@e1', timeout=1), wait_for_element('@e12', timeout=0.5))
""").splitlines()
    assert out == ['@e1 button "Search"', "True False"]
