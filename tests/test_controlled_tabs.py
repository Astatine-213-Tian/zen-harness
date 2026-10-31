"""Controlled tabs: each agent's own tab, never the user's by accident, marked on every page."""
import subprocess
import sys

MARK = "\U0001F916 "


def agent(env, name, code):
    p = subprocess.run([sys.executable, "-m", "zen_harness.run"], input=code, capture_output=True, text=True,
                       env={**env, "ZH_AGENT": name}, timeout=120)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def test_a_page_reached_without_waiting_is_marked(at, site):
    zh = at("tabs.html")
    zh(f"js(\"document.getElementById('next').href = {site + '/slow.html?ms=300'!r}\"); click('#next')")
    out = zh("""
for _ in range(100):
    if 'slow.html' in js('location.href') and js('document.readyState') == 'complete': break
    wait(0.1)
wait(0.3)
print(js('document.title'))
""")
    assert out == MARK + "Slow page"


def test_agents_get_a_tab_each(env, site):
    agent(env, "a", f"new_tab({site + '/forms.html'!r}); wait_for_load()")
    agent(env, "b", f"new_tab({site + '/tabs.html'!r}); wait_for_load()")
    assert agent(env, "a", "print(js('location.pathname'), js('document.title'))") == f"/forms.html {MARK}Forms"
    assert agent(env, "b", "print(js('location.pathname'), js('document.title'))") == f"/tabs.html {MARK}Tabs"
    agent(env, "b", "close_tab()")
    assert agent(env, "a", "print(js('document.title'))") == MARK + "Forms"  # a's tab keeps its marker


def test_no_tab_is_taken_over_without_asking(zh, env):
    subprocess.run([sys.executable, "-m", "zen_harness.run", "stop"], env=env, capture_output=True)
    p = zh("js('1')", check=False)
    assert p.returncode == 1 and "no tab is controlled" in p.stderr
    assert zh("ensure_real_tab(); print(js('1 + 1'))") == "2"  # taking a tab is explicit


def test_frames_keep_their_titles(at, site):
    zh = at("frames.html")
    out = zh(f"print(js('document.title'), js('document.title', target_id=iframe_target({site + '/frame-inner.html'!r})))")
    assert out == f"{MARK}Frames Inner"


def test_a_frame_cannot_be_the_controlled_tab(at, site):
    zh = at("frames.html")
    p = zh(f"switch_tab(iframe_target({site + '/frame-inner.html'!r}))", check=False)
    assert p.returncode == 1 and "is a frame, not a tab" in p.stderr
