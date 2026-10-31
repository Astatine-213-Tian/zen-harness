"""#4: never end another tool's session; `stop` leaves no marker on the user's tab."""
import json
import subprocess
import sys
import threading

from websockets.sync.client import connect as ws_connect

from conftest import FIXTURE, PORT
from zen_harness import config, daemon


def run(env, *args):
    return subprocess.run([sys.executable, "-m", "zen_harness.run", *args], env=env, capture_output=True, text=True)


def test_session_taken_after_our_check_is_left_alone(page, env, monkeypatch):
    run(env, "stop")
    cfg = config.load(env=env, config_file=env["ZH_CONFIG"])
    # Another tool opens a BiDi-only session...
    with ws_connect(f"ws://127.0.0.1:{PORT}/session", open_timeout=10) as other:
        other.send(json.dumps({"id": 1, "method": "session.new", "params": {"capabilities": {}}}))
        assert json.loads(other.recv(10))["type"] == "success"
        # ...right after our "is Zen free?" check said yes.
        checks = iter([True])
        monkeypatch.setattr(daemon, "session_free", lambda c: next(checks, False))
        try:
            daemon.marionette_session(cfg)
            raise AssertionError("expected the session request to fail")
        except daemon.BiDiError as e:
            client = getattr(e, "client", None)
        monkeypatch.undo()
        parked = threading.Thread(target=daemon.park, args=(cfg, client, 0.2)) if client else None
        if parked:
            parked.start()
        # The other tool's session must still work.
        other.send(json.dumps({"id": 2, "method": "browsingContext.getTree", "params": {}}))
        assert json.loads(other.recv(10))["type"] == "success"
        other.send(json.dumps({"id": 3, "method": "session.end", "params": {}}))
        other.recv(10)
    if parked:
        parked.join(10)
        assert not parked.is_alive()  # released once the other session ended
    assert page("print(js('1 + 1'))") == "2"


def test_marker_survives_the_page_changing_its_title(zh, env):
    url = FIXTURE + "#retitle-test"
    zh(f"new_tab({url!r}); wait_for_load()")
    out = zh("js(\"document.title = 'Renamed'\"); wait(0.2); print(js('document.title'))")
    assert out == "\U0001F916 Renamed"
    run(env, "stop")  # and stop takes it off for good
    out = zh(f"print([t['title'] for t in list_tabs() if t['url'] == {url!r}])")
    assert out == "['Renamed']"


def test_stop_removes_the_tab_marker(zh, env):
    url = FIXTURE + "#marker-test"  # tab ids change between sessions, so find the tab by URL
    zh(f"new_tab({url!r}); wait_for_load()")
    assert zh("print(current_tab()['title'])") == "\U0001F916 Fixture"
    run(env, "stop")
    assert zh(f"print([t['title'] for t in list_tabs() if t['url'] == {url!r}])") == "['Fixture']"
