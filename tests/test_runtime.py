"""remote_mode = "runtime": start remote control inside a running Zen without the automation flag."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FIXTURE, PORT, kill_profile
from zen_harness import config, connection, runtime

PREFS = "".join(f'user_pref("{n}", true);\n' for n in runtime.REQUIRED_PREFS)
# Headless tests can't click prompts.
NO_PROMPTS = ('user_pref("remote.experimental.dynamicstart.prompt.enabled", false);\n'
              'user_pref("devtools.debugger.prompt-connection", false);\n')
# Test-only: runtime start always binds 9222, which a real browser may hold; move it.
MOVE_PORT_JS = """(() => {{ const {{ HttpServer }} = ChromeUtils.importESModule("chrome://remote/content/server/httpd.sys.mjs");
  const o = HttpServer.prototype._start;
  HttpServer.prototype._start = function (p, h, d) {{ return o.call(this, p == 9222 ? {port} : p, h, d); }};
  return "moved"; }})()"""


def test_missing_prefs_and_help(tmp_path):
    assert runtime.missing_prefs(tmp_path) == list(runtime.REQUIRED_PREFS)
    (tmp_path / "prefs.js").write_text('user_pref("devtools.chrome.enabled", true);\n'
                                       'user_pref("devtools.debugger.remote-enabled", false);\n')
    missing = runtime.missing_prefs(tmp_path)
    assert missing == ["remote.experimental.dynamicstart.enabled", "devtools.debugger.remote-enabled"]
    assert "about:config" in runtime.prefs_help(missing)


def test_runtime_mode_explains_setup(tmp_path):
    cfg = config.Config(remote_mode="runtime", port=9399, profile=str(tmp_path))
    with pytest.raises(connection.ConnectError, match="port 9222"):
        connection.connect(cfg)
    cfg = config.Config(remote_mode="runtime", port=9222, profile=str(tmp_path))
    if connection.listener(9222) is None:  # don't assume anything about a real browser on 9222
        with pytest.raises(connection.ConnectError, match="about:config"):
            connection.connect(cfg)


def test_runtime_start_has_no_automation_flag(tmp_path, env):
    port = str(int(PORT) + 20)
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "user.js").write_text(PREFS + NO_PROMPTS)
    sock = Path(f"/tmp/zen-harness-{os.getuid()}") / f"devtools-test-{port}.sock"
    sock.parent.mkdir(mode=0o700, exist_ok=True)
    sock.unlink(missing_ok=True)
    zen = subprocess.Popen([config.Config().zen_path, "--profile", str(profile), "--headless",
                            *runtime.debugger_args(sock)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    e = {**env, "ZH_PORT": port, "ZH_PROFILE": str(profile), "ZH_WORKSPACE": str(tmp_path / "ws")}
    try:
        runtime.wait_for_socket(sock, 30)
        rdp = runtime.RDP(sock)
        assert rdp.evaluate(rdp.console(), MOVE_PORT_JS.format(port=port)) == "moved"
        rdp.close()
        out = runtime.start(sock)
        assert out["marionette"] > 0 and "marionetteError" not in out
        assert not sock.exists()
        snippet = f"new_tab({FIXTURE!r}); wait_for_load(); print(js('navigator.webdriver'))"
        p = subprocess.run([sys.executable, "-m", "zen_harness.run"], input=snippet, env=e,
                           capture_output=True, text=True, timeout=120)
        assert p.stdout.strip() == "False", p.stderr
        doctor = subprocess.run([sys.executable, "-m", "zen_harness.run", "doctor"], env=e,
                                capture_output=True, text=True).stdout
        assert "via Marionette" in doctor
    finally:
        subprocess.run([sys.executable, "-m", "zen_harness.run", "stop"], env=e, capture_output=True)
        zen.terminate()
        kill_profile(profile)
