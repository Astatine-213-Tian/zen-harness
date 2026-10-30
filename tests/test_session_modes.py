import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from conftest import MARIONETTE_PORT, PORT, daemon_pids, kill_profile


def doctor(env):
    return subprocess.run([sys.executable, "-m", "zen_harness.run", "doctor"], env=env,
                          capture_output=True, text=True, timeout=60).stdout


def test_launch_uses_marionette_on_the_configured_port(page, env):
    out = doctor(env)
    assert f"marionette: port {MARIONETTE_PORT}" in out
    assert "session via Marionette" in out


def test_force_killed_daemon_does_not_lock_zen(page):
    pids = daemon_pids()
    assert pids
    for p in pids:
        os.kill(p, signal.SIGKILL)
    time.sleep(1)
    assert not daemon_pids()
    assert page("print(js('1 + 1'))") == "2"


@pytest.fixture
def bidi_only_env(env):
    """A second headless Zen started with --remote-debugging-port only, as a user might."""
    port = str(int(PORT) + 1)
    tmp = Path(tempfile.mkdtemp(prefix="zh-test-bidi-"))
    profile = tmp / "profile"
    profile.mkdir()
    (profile / "user.js").write_text('user_pref("remote.prefs.recommended", false);\n')
    zen_env = {k: v for k, v in os.environ.items() if not k.startswith("MOZ_")}
    subprocess.Popen([env.get("ZH_ZEN_PATH", "/Applications/Zen.app/Contents/MacOS/zen"), "--profile",
                      str(profile), "--remote-debugging-port", port, "--headless"], env=zen_env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    e = {**env, "ZH_PORT": port, "ZH_PROFILE": str(profile), "ZH_WORKSPACE": str(tmp / "ws")}
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", int(port)), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.25)
        yield e
    finally:
        subprocess.run([sys.executable, "-m", "zen_harness.run", "stop"], env=e, capture_output=True)
        kill_profile(profile)


def test_attaches_without_marionette(bidi_only_env):
    assert "marionette: off" in doctor(bidi_only_env)
    p = subprocess.run([sys.executable, "-m", "zen_harness.run"], input="print(js('6 * 7'))",
                       env=bidi_only_env, capture_output=True, text=True, timeout=120)
    assert p.stdout.strip() == "42", p.stderr
    assert "session is BiDi-only" in doctor(bidi_only_env)


def orphan_session(port):
    """Open a BiDi-only session and drop its socket without ending it, like a crashed client."""
    import json
    from websockets.sync.client import connect
    with connect(f"ws://127.0.0.1:{port}/session", open_timeout=10) as ws:
        ws.send(json.dumps({"id": 1, "method": "session.new", "params": {"capabilities": {}}}))
        assert json.loads(ws.recv(10))["type"] == "success"


def cli(env, *args):
    return subprocess.run([sys.executable, "-m", "zen_harness.run", *args], env=env,
                          capture_output=True, text=True, timeout=120)


def test_stop_force_clears_an_orphaned_session(page, env):
    cli(env, "stop")
    orphan_session(PORT)
    locked = page("print(1)", check=False)
    assert locked.returncode == 1 and "stop --force" in locked.stderr
    p = cli(env, "stop", "--force")
    assert p.returncode == 0 and "ended Zen's open session" in p.stdout
    assert "even another tool's" in p.stderr  # it warns before acting
    assert page("print(js('1 + 1'))") == "2"


def test_stop_force_with_nothing_to_clear(page, env):
    page("print(1)")
    p = cli(env, "stop", "--force")
    assert p.returncode == 0 and "session ended" in p.stdout and "nothing to clear" in p.stdout


def test_stop_force_needs_marionette(bidi_only_env):
    orphan_session(bidi_only_env["ZH_PORT"])
    p = cli(bidi_only_env, "stop", "--force")
    assert p.returncode == 1 and "zen-harness relaunch" in p.stderr
