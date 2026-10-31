"""Client side of the daemon socket: start the daemon if needed, send one request."""
import json
import socket
import subprocess
import sys
import time

from . import runfiles

# Long enough for Zen to start, or for the user to answer the "Allow remote control?" prompt.
START_TIMEOUT = 90.0


def err_path(cfg):
    return runfiles.run_dir(cfg) / f"zh-{cfg.port}.err"


def _connect(cfg):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(runfiles.daemon_socket(cfg)))
    return s


def daemon_alive(cfg) -> bool:
    try:
        _connect(cfg).close()
        return True
    except OSError:
        return False


def ensure_daemon(cfg):
    if daemon_alive(cfg):
        return
    err = err_path(cfg)
    err.unlink(missing_ok=True)
    log = runfiles.log(cfg, f"daemon-{cfg.port}").open("ab")
    proc = subprocess.Popen([sys.executable, "-m", "zen_harness.daemon"], stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if daemon_alive(cfg):
            return
        if proc.poll() is not None:
            raise RuntimeError(err.read_text() if err.exists() else "zen-harness daemon exited at startup")
        if err.exists() and err.read_text():  # a daemon may report and stay up (see daemon.park)
            raise RuntimeError(err.read_text())
        time.sleep(0.1)
    proc.terminate()
    raise RuntimeError(f"zen-harness daemon did not start within {START_TIMEOUT:.0f}s")


def send(cfg, req, timeout=60.0):
    s = _connect(cfg)
    try:
        s.settimeout(timeout)
        f = s.makefile("rwb")
        f.write((json.dumps(req) + "\n").encode())
        f.flush()
        line = f.readline()
    finally:
        s.close()
    if not line:
        raise RuntimeError("zen-harness daemon closed the connection")
    resp = json.loads(line)
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp
