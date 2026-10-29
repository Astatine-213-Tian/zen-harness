"""Integration tests run real snippets through the CLI against a headless Zen
on a throwaway profile (the local stand-in for the user's browser)."""
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = (ROOT / "tests/fixtures/page.html").as_uri()
# Override to run several test sessions side by side.
PORT = os.environ.get("ZH_TEST_PORT", "9345")
# Never Marionette's default 2828, which a real Firefox may hold.
MARIONETTE_PORT = str(int(PORT) - 6500)


def daemon_pids(port=PORT):
    """Pids of zen-harness daemons connected to Zen on `port`, so other runs' daemons are left alone."""
    def pids(cmd):
        return set(subprocess.run(cmd, capture_output=True, text=True).stdout.split())
    return [int(p) for p in pids(["pgrep", "-f", "zen_harness.daemon"])
            & pids(["lsof", "-nP", "-t", f"-iTCP@127.0.0.1:{port}", "-sTCP:ESTABLISHED"])]


def kill_profile(profile):
    out = subprocess.run(["pgrep", "-f", "--", f"--profile {profile}"], capture_output=True, text=True).stdout
    for pid in out.split():
        os.kill(int(pid), signal.SIGTERM)


@pytest.fixture(scope="session")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="zh-test-"))
    (tmp / "profile").mkdir()
    e = {**os.environ, "ZH_CONFIG": str(tmp / "none.toml"), "ZH_WORKSPACE": str(tmp / "ws"),
         "ZH_PROFILE": str(tmp / "profile"), "ZH_PORT": PORT, "ZH_HEADLESS": "1",
         "ZH_MARIONETTE_PORT": MARIONETTE_PORT}
    yield e
    subprocess.run([sys.executable, "-m", "zen_harness.run", "stop"], env=e, capture_output=True)
    kill_profile(tmp / "profile")


@pytest.fixture
def zh(env):
    """Run a snippet; return stdout. Raises with stderr on a non-zero exit."""
    def run(code, check=True):
        p = subprocess.run([sys.executable, "-m", "zen_harness.run"], input=code, env=env,
                           capture_output=True, text=True, timeout=120)
        if check and p.returncode:
            raise AssertionError(f"snippet failed ({p.returncode}):\n{p.stderr}")
        return p.stdout.strip() if check else p
    return run


@pytest.fixture
def page(zh):
    """A fresh fixture tab controlled by the harness."""
    zh(f"new_tab({FIXTURE!r}); wait_for_load()")
    return zh
