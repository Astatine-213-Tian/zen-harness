"""remote_mode = "runtime": turn remote control on inside a running Zen, without the
automation flag (navigator.webdriver stays false, no automation prefs).

Firefox can start its Remote Agent at runtime (`startAtRuntime({isBrowserAutomation:
false})`), but Zen has no button for it yet. So the harness asks the running Zen to
open a DevTools server on a private Unix socket (`--start-debugger-server`, forwarded
to the running instance), evaluates the start call through it, and closes it again.
"""
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

from .config import Config

# Firefox hard-codes the runtime Remote Agent to 9222 and quits the browser if it's busy.
RUNTIME_PORT = 9222
REQUIRED_PREFS = (
    "remote.experimental.dynamicstart.enabled",  # allows starting the Remote Agent at runtime
    "devtools.chrome.enabled",                   # DevTools may evaluate browser-level code
    "devtools.debugger.remote-enabled",          # --start-debugger-server is honoured
)

# Marionette starts too, on any free port: a busy port would also make Firefox quit.
START_JS = """(async () => {
  const { RemoteAgent } = ChromeUtils.importESModule("chrome://remote/content/components/RemoteAgent.sys.mjs");
  const { Marionette } = ChromeUtils.importESModule("chrome://remote/content/components/Marionette.sys.mjs");
  const out = { bidi: RemoteAgent.running ? "running" : await RemoteAgent.startAtRuntime({ isBrowserAutomation: false }) };
  if (!Marionette.running) {
    const P = "marionette.port", had = Services.prefs.prefHasUserValue(P), old = had && Services.prefs.getIntPref(P);
    Services.prefs.setIntPref(P, 0);
    try { out.marionette = await Marionette.startAtRuntime({ isBrowserAutomation: false }); }
    catch (e) { out.marionetteError = String(e); }
    finally { had ? Services.prefs.setIntPref(P, old) : Services.prefs.clearUserPref(P); }
  }
  return JSON.stringify(out);
})()"""

CLOSE_JS = """(() => {
  const L = ChromeUtils.importESModule("resource://devtools/shared/loader/DistinctSystemPrincipalLoader.sys.mjs", { global: "shared" });
  const me = {};
  try { L.useDistinctSystemPrincipalLoader(me).require("resource://devtools/server/devtools-server.js").DevToolsServer.closeAllSocketListeners(); }
  finally { L.releaseDistinctSystemPrincipalLoader(me); }
  return "closed";
})()"""


class BootstrapError(RuntimeError):
    pass


def devtools_socket() -> Path:
    return Path(f"/tmp/zen-harness-{os.getuid()}") / "devtools.sock"


def missing_prefs(profile: Path):
    """Required prefs not set to true in the profile's prefs.js or user.js."""
    text = ""
    for name in ("prefs.js", "user.js"):
        p = Path(profile) / name
        if p.exists():
            text += p.read_text(errors="replace")
    return [n for n in REQUIRED_PREFS
            if not re.search(r'user_pref\("' + re.escape(n) + r'",\s*true\);', text)]


def prefs_help(missing) -> str:
    lines = "\n".join(f"    {n} = true" for n in missing)
    return ("remote_mode = \"runtime\" needs these Zen settings once. Open about:config in Zen, "
            "search each name and set it:\n" + lines)


class RDP:
    """Just enough of Firefox's DevTools protocol to evaluate code in the browser process."""

    def __init__(self, path, timeout=60.0):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(timeout)  # a DevTools "Allow connection?" prompt may be waiting for the user
        self.s.connect(str(path))
        self.buf = b""
        self.recv()  # root greeting

    def send(self, packet):
        data = json.dumps(packet).encode()
        self.s.sendall(str(len(data)).encode() + b":" + data)

    def recv(self):
        while b":" not in self.buf:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("DevTools connection closed (refused in Zen?)")
            self.buf += chunk
        size, rest = self.buf.split(b":", 1)
        while len(rest) < int(size):
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("DevTools connection closed mid-message")
            rest += chunk
        self.buf = rest[int(size):]
        return json.loads(rest[:int(size)])

    def request(self, packet):
        self.send(packet)
        while True:
            r = self.recv()
            if r.get("from") == packet["to"]:
                if "error" in r:
                    raise BootstrapError(f"{r['error']}: {r.get('message', '')}")
                return r

    def console(self):
        process = self.request({"to": "root", "type": "getProcess", "id": 0})["processDescriptor"]["actor"]
        return self.request({"to": process, "type": "getTarget"})["process"]["consoleActor"]

    def evaluate(self, actor, text):
        rid = self.request({"to": actor, "type": "evaluateJSAsync", "text": text,
                            "mapped": {"await": True}})["resultID"]
        while True:
            m = self.recv()
            if m.get("type") == "evaluationResult" and m.get("resultID") == rid:
                if m.get("exceptionMessage"):
                    raise BootstrapError(m["exceptionMessage"])
                return m.get("result")

    def close(self):
        self.s.close()


def debugger_args(sock: Path) -> list:
    return ["--start-debugger-server", str(sock)]


def request_debugger(cfg: Config, profile: Path, sock: Path, timeout=15.0):
    """Ask the running Zen for a DevTools server on `sock` (the flag is forwarded to it)."""
    sock.parent.mkdir(mode=0o700, exist_ok=True)
    os.chmod(sock.parent, 0o700)
    sock.unlink(missing_ok=True)
    subprocess.run([cfg.zen_path, "--profile", str(profile), *debugger_args(sock)],
                   capture_output=True, timeout=timeout)
    wait_for_socket(sock, timeout)


def wait_for_socket(sock: Path, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sock.exists():
            return
        time.sleep(0.2)
    raise BootstrapError("Zen did not open its DevTools socket; check the three about:config settings, "
                        "and that Zen is not headless (a running headless Zen ignores forwarded flags)")


def start(sock: Path, timeout=30.0) -> dict:
    """Connect over DevTools, start the Remote Agent (and Marionette) at runtime, close DevTools."""
    rdp = RDP(sock)
    try:
        actor = rdp.console()
        deadline = time.time() + timeout
        while True:
            try:
                out = json.loads(rdp.evaluate(actor, START_JS))
                break
            except BootstrapError as e:  # the window may still be starting up
                if time.time() > deadline or "starting up" not in str(e) and "no window" not in str(e):
                    raise
                time.sleep(0.5)
        try:
            rdp.evaluate(actor, CLOSE_JS)
        except (BootstrapError, OSError):
            pass
    finally:
        rdp.close()
        sock.unlink(missing_ok=True)
    if out.get("bidi") == -1:
        raise BootstrapError("Zen refused to start remote control at runtime; "
                            "is remote.experimental.dynamicstart.enabled true?")
    return out
