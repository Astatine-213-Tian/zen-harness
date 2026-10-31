"""Zen's one WebDriver session (ADR-0003): take it, give it back, or clear one left behind.

Zen allows one session at a time. The lease creates it through Marionette when Zen has it on,
so the session ends when our connection drops, even on kill -9; otherwise the daemon asks for
a BiDi-only one on its own socket. Closing any Marionette connection ends the open session,
even another tool's, so the lease never closes one while someone else's session is open.
"""
import json
import threading
import time

from websockets.sync.client import connect as ws_connect

from . import connection, ipc, marionette

CAPABILITIES = {"unhandledPromptBehavior": {"default": "ignore"}}
PARK_POLL = 1.0  # seconds between checks while holding a connection for another tool's session

BUSY = ("Zen already has a remote-control session open: another tool (e.g. an MCP server) holds it,\n"
        "or a zen-harness daemon was force-killed. Stop the other tool, or (after checking with the\n"
        "user, since it ends whoever's session is open) run `zen-harness stop --force`, or\n"
        "`zen-harness relaunch` to restart Zen (tabs come back through session restore).")


class LeaseError(ipc.HarnessError):
    """The session couldn't be taken or cleared; the message says what to do."""


class Busy(LeaseError):
    """Another client holds Zen's session."""

    def __init__(self):
        super().__init__(BUSY)


class Lease:
    def __init__(self, ws_url, client=None, session_id=None):
        self.ws_url = ws_url  # BiDi socket of the session (or, BiDi-only, where to ask for one)
        self.client = client  # the Marionette connection that owns the session, if any
        self.session_id = session_id
        self.kind = "marionette" if client else "bidi"
        self.released = False

    def release(self, end_bidi_session=lambda: None):
        """End the session: Marionette's DeleteSession, or BiDi's session.end sent through the
        caller's socket by `end_bidi_session()`. Safe to call twice; never raises."""
        if self.released:
            return
        self.released = True
        try:
            if self.client:
                self.client.command("WebDriver:DeleteSession", timeout=3)
            else:
                end_bidi_session()
        except Exception:
            pass
        if self.client:
            self.client.close()


def acquire(cfg) -> Lease:
    """Take Zen's session. Raises Busy if another client holds it, LeaseError or
    connection.ConnectError otherwise."""
    url = connection.connect(cfg)
    deadline = time.time() + 5  # a session that was just stopped is released a moment later
    while not _is_free(cfg) and time.time() < deadline:
        time.sleep(0.2)
    port = connection.marionette_port(cfg)
    if not port:
        return Lease(url)
    if not _is_free(cfg):
        raise Busy()
    try:
        client = marionette.Client(port)
    except (OSError, EOFError, ValueError, marionette.MarionetteError):
        return Lease(url)
    try:
        result = client.command("WebDriver:NewSession", {"webSocketUrl": True, **CAPABILITIES}, timeout=60)
        ws_url = result.get("capabilities", {}).get("webSocketUrl")
        if not ws_url:
            raise marionette.MarionetteError("Zen made a Marionette session without WebDriver BiDi")
        return Lease(ws_url, client, result.get("sessionId"))
    except Exception as e:
        if _taken(cfg):  # someone took it after our check: closing now would end their session
            _park(cfg, client)
            raise Busy() from e
        client.close()
        raise LeaseError(str(e)) from e


def force_release(cfg, timeout=5.0) -> str:
    """End whatever session Zen has open, whoever holds it (`zen-harness stop --force`).

    Closing a Marionette connection makes Firefox end the open session, so connect and close.
    Never call this automatically: it also ends another tool's live session."""
    if connection.listener(cfg.port) != "bidi":
        return f"Zen isn't accepting remote control on port {cfg.port}; nothing to clear"
    released = time.time() + 1  # a session that was just stopped is released a moment later
    while not _is_free(cfg):
        if time.time() > released:
            break
        time.sleep(0.1)
    else:
        return "Zen has no open session; nothing to clear"
    port = connection.marionette_port(cfg)
    if not port:
        raise LeaseError("Zen runs without Marionette, so its open session can only be cleared by "
                         "restarting Zen: run `zen-harness relaunch`")
    try:
        client = marionette.Client(port)
    except (OSError, EOFError, ValueError, marionette.MarionetteError) as e:
        raise LeaseError("another tool is connected to Zen through Marionette and holds the session; "
                         "stop that tool (or run `zen-harness relaunch`)") from e
    client.close()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_free(cfg):
            return "ended Zen's open session"
        time.sleep(0.2)
    raise LeaseError(f"Zen still reports an open session {timeout:g}s later; run `zen-harness relaunch`")


def _is_free(cfg):
    """True if Zen has no WebDriver session open (BiDi session.status)."""
    with ws_connect(connection.session_url(cfg), open_timeout=10) as ws:
        ws.send(json.dumps({"id": 1, "method": "session.status", "params": {}}))
        return bool(json.loads(ws.recv(10)).get("result", {}).get("ready"))


def _taken(cfg):
    try:
        return not _is_free(cfg)
    except Exception:
        return False


def _park(cfg, client):
    """Hold `client` open on a thread of its own until the other session ends or Zen goes
    away. It isn't a daemon thread, so the process lives on until then."""
    def hold():
        while True:
            time.sleep(PARK_POLL)
            try:
                if _is_free(cfg):
                    break
            except Exception:
                if not connection.listener(cfg.port):  # Zen went away; a hiccup keeps us holding
                    break
        client.close()
    threading.Thread(target=hold, name="zen-harness-park").start()
