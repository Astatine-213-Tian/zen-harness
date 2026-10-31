"""#4: never end another tool's session; `stop` leaves no marker on the user's tab."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from websockets.sync.client import connect as ws_connect

from conftest import FIXTURE, PORT, kill_profile
from zen_harness import config, connection, daemon


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
    assert page("new_tab(); print(js('1 + 1'))") == "2"


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


def _together(env, n, code="print(len(list_tabs()) > 0)"):
    """Start n snippets a moment apart: some find no daemon yet, others one still starting."""
    procs = []
    for _ in range(n):
        procs.append(subprocess.Popen([sys.executable, "-m", "zen_harness.run"], stdin=subprocess.PIPE, text=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env))
        time.sleep(0.15)
    outs = [p.communicate(code, timeout=120) for p in procs]
    return [p.returncode for p in procs], outs


def _daemons():
    """Every zen-harness daemon process for this test port, parked or still starting included."""
    out = subprocess.run(["pgrep", "-f", f"zen_harness.daemon --port={PORT}$"], capture_output=True, text=True).stdout
    return out.split()


def _zens(env):
    out = subprocess.run(["pgrep", "-f", "--", f"--profile {env['ZH_PROFILE']} --remote-debugging-port"],
                         capture_output=True, text=True).stdout
    return out.split()


def test_snippets_started_together_share_one_daemon(zh, env):
    for _ in range(6):
        run(env, "stop")
        codes, outs = _together(env, 4)
        assert codes == [0] * 4, outs
        time.sleep(0.5)
        # One daemon holds the session; no other is left waiting, parked, or about to fail.
        assert len(_daemons()) == 1


def test_cold_start_together_launches_zen_once(zh, env):
    for _ in range(3):
        run(env, "stop")
        kill_profile(env["ZH_PROFILE"])
        deadline = time.time() + 15
        while (connection.listener(int(PORT)) or _zens(env)) and time.time() < deadline:
            time.sleep(0.2)
        log = Path(env["ZH_WORKSPACE"]) / "run" / "zen.log"
        seen = log.stat().st_size if log.exists() else 0
        codes, outs = _together(env, 3)
        assert codes == [0] * 3, outs
        assert len(_zens(env)) == 1
        assert "already open" not in log.read_text()[seen:]  # a second copy of Zen was started
