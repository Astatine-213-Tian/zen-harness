"""Background process that owns the single WebDriver BiDi session with Zen.

Zen accepts one session at a time and opening one costs ~300 ms (plus an
"Allow remote control?" prompt in Remote Control mode), so the daemon keeps it
open and serves helper calls over a Unix socket: one JSON line in, one out.
It ends the session after `idle_timeout` seconds without calls.

When Zen runs with --marionette, the session is created through Marionette, which
ends it when the daemon's connection drops, even on `kill -9`. Otherwise it is a
BiDi-only session that Zen keeps until it restarts if the daemon dies uncleanly.
"""
import collections
import itertools
import json
import os
import signal
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

from websockets.sync.client import connect as ws_connect

from . import config, connection, marionette

CAPABILITIES = {"unhandledPromptBehavior": {"default": "ignore"}}
EVENTS = [
    "browsingContext.contextCreated", "browsingContext.contextDestroyed",
    "browsingContext.load", "browsingContext.userPromptOpened", "browsingContext.userPromptClosed",
    "log.entryAdded", "network.beforeRequestSent", "network.responseCompleted", "network.fetchError",
    "browsingContext.downloadWillBegin", "browsingContext.downloadEnd",
    # navigationAborted is not supported by Zen; subscribing to it would fail the whole list.
    "browsingContext.navigationStarted", "browsingContext.navigationCommitted",
    "browsingContext.navigationFailed", "browsingContext.fragmentNavigated",
]

# Calls that may start a navigation. wait_for_load gives one a moment to begin; reads that
# can't navigate send params["zh_passive"] = True so they don't count.
NAVIGATION_CAUSES = ("input.performActions", "script.evaluate", "script.callFunction",
                     "browsingContext.navigate", "browsingContext.reload", "browsingContext.traverseHistory")


BLOCKED_BY_DIALOG = ("input.performActions", "script.evaluate", "script.callFunction",
                     "browsingContext.navigate", "browsingContext.reload")


def sock_path(cfg):
    # Unix socket paths are capped at 104 bytes on macOS, so keep them out of the workspace.
    return Path(f"/tmp/zen-harness-{os.getuid()}") / f"{cfg.port}.sock"


def err_path(cfg):
    return cfg.run_dir / f"zh-{cfg.port}.err"


def open_session(cfg):
    try:
        url = connection.connect(cfg)
        # A session that was just stopped is released a moment later; don't race it.
        deadline = time.time() + 5
        while not session_free(cfg) and time.time() < deadline:
            time.sleep(0.2)
        client = marionette_session(cfg)
        if client:
            return Session(client.ws_url, marionette=client)
        return Session(url)
    except BiDiError as e:
        if "Maximum number of active sessions" not in str(e):
            raise
        # Firefox never ends a BiDi-only session whose socket dropped, and it can't be rejoined.
        raise BiDiError(
            "Zen already has a remote-control session open: another tool (e.g. an MCP server) holds it,\n"
            "or a zen-harness daemon was force-killed. Stop the other tool, or (after checking with the\n"
            "user, since it ends whoever's session is open) run `zen-harness stop --force`, or\n"
            "`zen-harness relaunch` to restart Zen (tabs come back through session restore).") from e


class BiDiError(RuntimeError):
    pass


class SessionTaken(BiDiError):
    """Another tool took Zen's session while we connected to Marionette. `client` must stay
    open until that session ends: closing any Marionette connection ends the open session."""

    def __init__(self, message, client):
        super().__init__(message)
        self.client = client


def force_end_session(cfg, timeout=5.0) -> str:
    """End whatever remote-control session Zen has open, whoever holds it (`stop --force`).

    Closing a Marionette connection makes Firefox end the open session, so connect and
    close. Never call this automatically: it also ends another tool's live session."""
    if connection.listener(cfg.port) != "bidi":
        return f"Zen isn't accepting remote control on port {cfg.port}; nothing to clear"
    released = time.time() + 1  # a session that was just stopped is released a moment later
    while not session_free(cfg):
        if time.time() > released:
            break
        time.sleep(0.1)
    else:
        return "Zen has no open session; nothing to clear"
    port = connection.marionette_port(cfg)
    if not port:
        raise BiDiError("Zen runs without Marionette, so its open session can only be cleared by "
                        "restarting Zen: run `zen-harness relaunch`")
    try:
        client = marionette.Client(port)
    except (OSError, EOFError, ValueError, marionette.MarionetteError) as e:
        raise BiDiError("another tool is connected to Zen through Marionette and holds the session; "
                        "stop that tool (or run `zen-harness relaunch`)") from e
    client.close()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if session_free(cfg):
            return "ended Zen's open session"
        time.sleep(0.2)
    raise BiDiError(f"Zen still reports an open session {timeout:g}s later; run `zen-harness relaunch`")


def park(cfg, client, poll=1.0):
    """Hold `client` open until Zen's other session ends (or Zen goes away), then close it."""
    while True:
        time.sleep(poll)
        try:
            if session_free(cfg):
                break
        except Exception:
            break
    client.close()


def session_free(cfg):
    """True if Zen has no WebDriver session open (BiDi session.status)."""
    with ws_connect(connection.session_url(cfg), open_timeout=10) as ws:
        ws.send(json.dumps({"id": 1, "method": "session.status", "params": {}}))
        return bool(json.loads(ws.recv(10)).get("result", {}).get("ready"))


def marionette_session(cfg, timeout=60.0):
    """A Marionette client holding a new session with BiDi on, or None to fall back to BiDi-only.

    Marionette deletes its session when this connection drops, even on kill -9.
    """
    port = connection.marionette_port(cfg)
    if not port:
        return None
    # Closing any Marionette connection deletes the open session, even another tool's,
    # so only connect when there is none.
    if not session_free(cfg):
        raise BiDiError("session not created: Maximum number of active sessions")
    try:
        client = marionette.Client(port)
    except (OSError, EOFError, ValueError, marionette.MarionetteError):
        return None
    try:
        result = client.command("WebDriver:NewSession", {"webSocketUrl": True, **CAPABILITIES}, timeout=timeout)
        client.ws_url = result.get("capabilities", {}).get("webSocketUrl")
        client.session_id = result.get("sessionId")
        if not client.ws_url:
            raise marionette.MarionetteError("Zen made a Marionette session without WebDriver BiDi")
    except Exception as e:
        try:
            taken = not session_free(cfg)
        except Exception:
            taken = False
        if taken:  # someone took it after our check; closing now would end their session
            raise SessionTaken("session not created: Maximum number of active sessions", client) from e
        client.close()
        raise BiDiError(str(e)) from e
    return client


class Session:
    def __init__(self, url, session_timeout=60.0, marionette=None):
        """Attach to the BiDi session at `url`; without a `marionette` client holding one, create it."""
        self.marionette = marionette
        self.mode = "marionette" if marionette else "bidi"
        try:
            # Entered by hand: calling connect() directly is deprecated, and we close it ourselves.
            self.ws = ws_connect(url, max_size=None, open_timeout=10, ping_interval=None).__enter__()
        except Exception:
            if marionette:
                marionette.close()
            raise
        self.ids = itertools.count(1)
        self.pending = {}
        self.lock = threading.Lock()
        self.events = collections.deque(maxlen=500)
        self.dialogs = {}  # context -> prompt params
        self.navigating = {}  # context -> [id, committed?] of its started, not yet loaded navigation
        self.last_cause = {}  # context -> monotonic time of the last call that may navigate
        self.last_nav = {}  # context -> monotonic time its last navigation started
        self.inflight = {}  # request id -> context
        self.last_network = {}  # context -> monotonic time of its last network event
        self.started = time.monotonic()
        self.current = None
        self.closed = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()
        try:
            if marionette:
                self.id = marionette.session_id
            else:
                self.id = self.call("session.new", {"capabilities": {"alwaysMatch": CAPABILITIES}},
                                    timeout=session_timeout)["sessionId"]
            self.call("session.subscribe", {"events": EVENTS})
        except Exception:
            self.ws.close()
            if marionette:
                marionette.close()
            raise

    def call(self, method, params=None, timeout=30.0):
        msg_id = next(self.ids)
        p = dict(params or {})
        passive = p.pop("zh_passive", False)
        slot = {"done": threading.Event(), "method": method,
                "context": p.get("context") or p.get("target", {}).get("context")}
        if method == "input.performActions" and slot["context"] in self.dialogs:
            # Input would wait until the dialog closes; say so instead of hanging.
            d = self.dialogs[slot["context"]]
            raise BiDiError(f"a {d['type']} dialog is open in this tab ({d['message']!r}); "
                            "answer it with handle_dialog() first")
        if method in NAVIGATION_CAUSES and not passive and slot["context"]:
            now = time.monotonic()
            self.last_cause[slot["context"]] = now
            if self.current and slot["context"] != self.current:
                self.last_cause[self.current] = now  # e.g. a click in a frame can navigate the whole tab
        self.pending[msg_id] = slot
        with self.lock:
            self.ws.send(json.dumps({"id": msg_id, "method": method, "params": p}))
        if not slot["done"].wait(timeout):
            self.pending.pop(msg_id, None)
            raise TimeoutError(f"{method} got no answer within {timeout:g}s")
        msg = slot["msg"]
        if msg.get("type") == "error":
            raise BiDiError(f"{msg.get('error')}: {msg.get('message', '')}".strip())
        return msg.get("result", {})

    def _read(self):
        try:
            for raw in self.ws:
                msg = json.loads(raw)
                slot = self.pending.pop(msg["id"], None) if "id" in msg else None
                if slot:
                    slot["msg"] = msg
                    slot["done"].set()
                elif msg.get("type") == "event":
                    self._on_event(msg["method"], msg.get("params", {}))
        except Exception:
            pass
        self.closed.set()
        for slot in list(self.pending.values()):
            slot["msg"] = {"type": "error", "error": "disconnected", "message": "Zen closed the connection"}
            slot["done"].set()

    def _on_event(self, method, p):
        ctx = p.get("context")
        self._track_navigation(method, ctx, p)
        if method.startswith("network."):
            req = p.get("request", {})
            self.last_network[ctx] = time.monotonic()
            if method == "network.beforeRequestSent":
                self.inflight[req.get("request")] = ctx
            else:
                self.inflight.pop(req.get("request"), None)
            if method == "network.beforeRequestSent":
                return  # only finished requests go to the event log
            summary = {"request": req.get("request"), "url": req.get("url"), "method": req.get("method"),
                       "status": p.get("response", {}).get("status"), "error": p.get("errorText")}
        elif method == "log.entryAdded":
            ctx = p.get("source", {}).get("context")
            summary = {"level": p.get("level"), "text": p.get("text")}
        elif method == "browsingContext.userPromptOpened":
            self.dialogs[ctx] = {k: p.get(k) for k in ("type", "message", "defaultValue")}
            summary = self.dialogs[ctx]
            # Input or JS that opened a dialog only completes once the dialog closes; answer it
            # now so the agent can see the dialog (page_info) and handle it.
            for msg_id, slot in list(self.pending.items()):
                if slot["method"] in BLOCKED_BY_DIALOG and slot["context"] == ctx:
                    self.pending.pop(msg_id, None)
                    slot["msg"] = {"type": "success", "result": {
                        "type": "success", "result": {"type": "undefined"}, "dialog": summary}}
                    slot["done"].set()
        elif method == "browsingContext.userPromptClosed":
            self.dialogs.pop(ctx, None)
            summary = {"accepted": p.get("accepted")}
        elif method == "browsingContext.contextDestroyed":
            if ctx == self.current:
                self.current = None
            summary = {"url": p.get("url")}
        elif method.startswith("browsingContext.download"):
            summary = {k: p.get(k) for k in ("url", "suggestedFilename", "status", "filepath") if k in p}
        else:
            summary = {"url": p.get("url")}
        self.events.append({"event": method, "context": ctx, "time": time.time(), **summary})

    def _track_navigation(self, method, ctx, p):
        nav = p.get("navigation")
        if method == "browsingContext.navigationStarted":
            # One navigation at a time per tab: a new one supersedes (aborts) the last.
            self.navigating[ctx] = [nav, False]
            self.last_nav[ctx] = time.monotonic()
        elif method == "browsingContext.navigationCommitted":
            if self.navigating.get(ctx, [None])[0] == nav:
                self.navigating[ctx][1] = True  # the new document is in place
        elif method in ("browsingContext.load", "browsingContext.navigationFailed",
                        "browsingContext.fragmentNavigated", "browsingContext.downloadWillBegin"):
            if nav is None or self.navigating.get(ctx, [None])[0] == nav:
                self.navigating.pop(ctx, None)
        elif method == "browsingContext.userPromptClosed" and p.get("type") == "beforeunload" and not p.get("accepted"):
            self.navigating.pop(ctx, None)  # the user chose to stay
        elif method == "browsingContext.contextDestroyed":
            for d in (self.navigating, self.last_cause, self.last_nav):
                d.pop(ctx, None)

    def load_state(self, ctx):
        now = time.monotonic()
        cause, nav = self.last_cause.get(ctx), self.last_nav.get(ctx)
        return {"navigating": ctx in self.navigating,
                "committed": self.navigating.get(ctx, [None, True])[1],
                "since_cause_ms": None if cause is None else int((now - cause) * 1000),
                "navigated_since_cause": cause is not None and nav is not None and nav >= cause}

    def titles(self, contexts, timeout=1.5):
        """document.title of each context, queried in parallel; '' if a tab doesn't answer."""
        out = dict.fromkeys(contexts, "")

        def one(ctx):
            try:
                r = self.call("script.evaluate", {"expression": "document.title", "awaitPromise": False,
                                                  "target": {"context": ctx}, "zh_passive": True},
                              timeout=timeout)
                out[ctx] = r.get("result", {}).get("value", "")
            except Exception:
                pass

        threads = [threading.Thread(target=one, args=(c,), daemon=True) for c in contexts]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout + 0.5)
        return out

    def meta(self, req):
        op = req["meta"]
        if op == "ping":
            return {"ok": True, "mode": self.mode}
        if op == "current":
            return {"context": self.current}
        if op == "set_current":
            self.current = req["context"]
            return {"context": self.current}
        if op == "load_state":
            ctx = req.get("context") or self.current
            return {**self.load_state(ctx), "dialog": self.dialogs.get(ctx)}
        if op == "dialog":
            return {"dialog": self.dialogs.get(req.get("context") or self.current)}
        if op == "network":
            # Per tab, so long-polling in the user's other tabs never blocks a wait.
            ctx = req.get("context") or self.current
            last = self.last_network.get(ctx, self.started)
            return {"inflight": sum(1 for c in self.inflight.values() if c == ctx),
                    "idle_ms": int((time.monotonic() - last) * 1000)}
        if op == "drain_events":
            events = list(self.events)
            self.events.clear()
            return {"events": events}
        if op == "titles":
            return {"titles": self.titles(req["contexts"])}
        raise ValueError(f"unknown meta op {op!r}")

    def close(self, tab_marker=""):
        if tab_marker and self.current:  # don't leave the "controlled" marker on the user's tab
            m = json.dumps(tab_marker + " ")
            try:
                self.call("script.evaluate", {"expression": f"if(document.title.startsWith({m}))"
                                              f"document.title=document.title.slice({m}.length)",
                                              "awaitPromise": False, "target": {"context": self.current},
                                              "zh_passive": True}, timeout=2)
            except Exception:
                pass
        try:
            if self.marionette:
                # BiDi's session.end refuses sessions made through WebDriver classic.
                self.marionette.command("WebDriver:DeleteSession", timeout=3)
            else:
                self.call("session.end", timeout=3)
        except Exception:
            pass
        try:
            if self.marionette:
                self.marionette.close()
            self.ws.close()
        except Exception:
            pass


def bind(cfg):
    path = sock_path(cfg)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    os.chmod(path, 0o600)
    server.listen(16)
    server.settimeout(1.0)
    return server


def serve(cfg, session, server):
    path = sock_path(cfg)
    inode = path.stat().st_ino

    def unlink_own():
        # After stop, a new daemon may already listen at this path; only remove our own socket.
        try:
            if path.stat().st_ino == inode:
                path.unlink()
        except FileNotFoundError:
            pass
    state = {"last": time.monotonic(), "stop": False}

    # A session left open would lock Zen until it restarts, so end it on any catchable exit.
    def request_stop(*_):
        state["stop"] = True

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, request_stop)

    def handle(conn):
        with conn:
            f = conn.makefile("rwb")
            line = f.readline()
            if not line:
                return
            req = json.loads(line)
            state["last"] = time.monotonic()
            try:
                if req.get("meta") == "stop":
                    state["stop"] = True
                    unlink_own()
                    session.close(cfg.tab_marker)
                    resp = {"ok": True}
                elif "meta" in req:
                    resp = session.meta(req)
                else:
                    resp = {"result": session.call(req["method"], req.get("params"),
                                                   timeout=req.get("timeout", 30.0))}
            except Exception as e:
                resp = {"error": str(e), "kind": type(e).__name__}
            f.write((json.dumps(resp) + "\n").encode())
            f.flush()
            state["last"] = time.monotonic()

    handlers = []
    try:
        while not state["stop"] and not session.closed.is_set():
            if cfg.idle_timeout and time.monotonic() - state["last"] > cfg.idle_timeout:
                break
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            t = threading.Thread(target=handle, args=(conn,), daemon=True)
            t.start()
            handlers.append(t)
    finally:
        for t in handlers:  # let in-flight replies (e.g. to stop) reach their clients
            t.join(timeout=2)
        server.close()
        unlink_own()
        session.close(cfg.tab_marker)


def main():
    cfg = config.load()
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cfg.run_dir, 0o700)
    err_path(cfg).unlink(missing_ok=True)
    session = None
    try:
        session = open_session(cfg)
        server = bind(cfg)
    except Exception as e:
        msg = str(e) if isinstance(e, (connection.ConnectError, BiDiError)) else traceback.format_exc()
        err_path(cfg).write_text(msg)
        if session:
            session.close()
        taken = e if isinstance(e, SessionTaken) else e.__cause__ if isinstance(e.__cause__, SessionTaken) else None
        if taken:
            park(cfg, taken.client)  # the error is already reported; keep the other tool's session alive
        sys.exit(1)
    serve(cfg, session, server)


if __name__ == "__main__":
    main()
