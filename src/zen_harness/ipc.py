"""Client side of the daemon socket: start the daemon if needed, send one request."""
import json
import select
import socket
import subprocess
import sys

from . import runfiles

# Long enough for Zen to start, or for the user to answer the "Allow remote control?" prompt.
START_TIMEOUT = 90.0


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
    log = runfiles.log(cfg, f"daemon-{cfg.port}")
    # The daemon reports how its start went in one line on stdout (only to the client that started
    # it), then logs to the file like stderr. Two clients starting at once each start one; the
    # daemon that doesn't get the port lock reports "served" once the other is up (daemon.main).
    # --port only names the daemon in `ps`; it reads its settings from the environment like we do.
    proc = subprocess.Popen([sys.executable, "-m", "zen_harness.daemon", f"--port={cfg.port}"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=log.open("ab"), start_new_session=True)
    ready, _, _ = select.select([proc.stdout], [], [], START_TIMEOUT)
    line = proc.stdout.readline() if ready else b""
    proc.stdout.close()
    if not ready:
        proc.terminate()
        raise RuntimeError(f"zen-harness daemon did not start within {START_TIMEOUT:.0f}s")
    if not line:
        raise RuntimeError(f"zen-harness daemon exited at startup; see {log}")
    outcome = json.loads(line)
    if "error" in outcome:
        raise RuntimeError(outcome["error"])


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
