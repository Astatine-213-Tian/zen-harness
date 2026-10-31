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
import fcntl
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

from . import config, connection, controlled, lease, runfiles, settle
from . import ipc

EVENTS = [
    "browsingContext.contextCreated", "browsingContext.contextDestroyed",
    "browsingContext.load", "browsingContext.userPromptOpened", "browsingContext.userPromptClosed",
    "log.entryAdded", "network.beforeRequestSent", "network.responseCompleted", "network.fetchError",
    "browsingContext.downloadWillBegin", "browsingContext.downloadEnd",
    # navigationAborted is not supported by Zen; subscribing to it would fail the whole list.
    "browsingContext.navigationStarted", "browsingContext.navigationCommitted",
    "browsingContext.navigationFailed", "browsingContext.fragmentNavigated",
]

# Calls that only complete once a dialog they opened is answered.
BLOCKED_BY_DIALOG = ("input.performActions", "script.evaluate", "script.callFunction",
                     "browsingContext.navigate", "browsingContext.reload")


def open_session(cfg):
    taken = lease.acquire(cfg)
    try:
        return Session(taken, tab_marker=cfg.tab_marker)
    except BiDiError as e:
        if e.code == "session not created":  # BiDi-only, and another client holds the session
            raise lease.Busy() from e
        raise


class BiDiError(ipc.BrowserError):
    """A BiDi command or session step failed; reaches snippets as BrowserError."""


class Session:
    def __init__(self, taken, session_timeout=60.0, tab_marker=""):
        """Attach to the leased session; a BiDi-only lease asks for the session on our socket."""
        self.lease = taken
        self.mode = taken.kind
        try:
            # Entered by hand: calling connect() directly is deprecated, and we close it ourselves.
            self.ws = ws_connect(taken.ws_url, max_size=None, open_timeout=10, ping_interval=None).__enter__()
        except Exception:
            taken.release()
            raise
        self.ids = itertools.count(1)
        self.pending = {}
        self.lock = threading.Lock()
        self.events = collections.deque(maxlen=500)
        self.pages = settle.PageSettle(document_ready=self._document_ready)
        self.inflight = {}  # request id -> context
        self.last_network = {}  # context -> monotonic time of its last network event
        self.started = time.monotonic()
        self.tabs = controlled.ControlledTabs(self.call, tab_marker)
        self.closing = False
        self.closed = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()
        try:
            if taken.client:
                self.id = taken.session_id
            else:
                self.id = self.call("session.new", {"capabilities": {"alwaysMatch": lease.CAPABILITIES}},
                                    timeout=session_timeout)["sessionId"]
            self.call("session.subscribe", {"events": EVENTS})
        except Exception:
            taken.release()
            self.ws.close()
            raise

    def call(self, method, params=None, timeout=30.0, navigates=False):
        """navigates=True: the call is a navigation cause (an action, not a read)."""
        msg_id = next(self.ids)
        p = dict(params or {})
        slot = {"done": threading.Event(), "method": method,
                "context": p.get("context") or p.get("target", {}).get("context")}
        if method == "input.performActions" and (d := self.pages.dialog(slot["context"])):
            raise ipc.DialogOpen(d)  # input would wait until the dialog closes
        if navigates and slot["context"]:
            self.pages.cause(slot["context"])
        self.pending[msg_id] = slot
        with self.lock:
            self.ws.send(json.dumps({"id": msg_id, "method": method, "params": p}))
        if not slot["done"].wait(timeout):
            self.pending.pop(msg_id, None)
            raise TimeoutError(f"{method} got no answer within {timeout:g}s")
        msg = slot["msg"]
        if msg.get("type") == "error":
            raise BiDiError(f"{msg.get('error')}: {msg.get('message', '')}".strip(), msg.get("error"))
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
        if method.startswith("browsingContext."):
            tab = self.pages.event(method, p)
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
            summary = {k: p.get(k) for k in ("type", "message", "defaultValue")}
            # Input or JS that opened a dialog only completes once the dialog closes; answer it
            # now so the agent can see the dialog (page_info) and handle it. A dialog from a frame
            # releases calls aimed at its tab or any frame in it.
            for msg_id, slot in list(self.pending.items()):
                if slot["method"] in BLOCKED_BY_DIALOG and self.pages.tab_of(slot["context"]) == tab:
                    self.pending.pop(msg_id, None)
                    slot["msg"] = {"type": "success", "result": {
                        "type": "success", "result": {"type": "undefined"}, "dialog": summary}}
                    slot["done"].set()
        elif method == "browsingContext.userPromptClosed":
            summary = {"accepted": p.get("accepted")}
        elif method == "browsingContext.contextDestroyed":
            self.tabs.forget(ctx)
            summary = {"url": p.get("url")}
        elif method.startswith("browsingContext.download"):
            summary = {k: p.get(k) for k in ("url", "suggestedFilename", "status", "filepath") if k in p}
        else:
            summary = {"url": p.get("url")}
        self.events.append({"event": method, "context": ctx, "time": time.time(), **summary})

    def _document_ready(self, tab):
        try:
            r = self.call("script.evaluate", {"expression": "document.readyState", "awaitPromise": False,
                                              "target": {"context": tab}}, timeout=5)
        except Exception:
            return False  # mid-navigation
        return r.get("result", {}).get("value") == "complete"

    def titles(self, contexts, timeout=1.5):
        """document.title of each context, queried in parallel; '' if a tab doesn't answer."""
        out = dict.fromkeys(contexts, "")

        def one(ctx):
            try:
                r = self.call("script.evaluate", {"expression": "document.title", "awaitPromise": False,
                                                  "target": {"context": ctx}},
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
        agent = req.get("agent", "")
        if op == "current":
            return {"context": self.tabs.get(agent)}
        if op == "set_current":
            return {"context": self.tabs.control(agent, req["context"])}
        if op == "settle":
            r = self.pages.wait(req.get("context") or self.tabs.get(agent), bool(req.get("need_load")),
                                float(req.get("timeout", 15.0)))
            if r["state"] == "dialog":
                raise ipc.DialogOpen(r["dialog"])
            return {"settled": r["state"] == "settled"}
        if op == "dialog":
            return {"dialog": self.pages.dialog(req.get("context") or self.tabs.get(agent))}
        if op == "network":
            # Per tab, so long-polling in the user's other tabs never blocks a wait.
            ctx = req.get("context") or self.tabs.get(agent)
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

    def close(self):
        """End the session (once: stop, the serve loop and errors may all call this)."""
        if self.closing:
            return
        self.closing = True
        self.tabs.release()  # don't leave markers on the user's tabs
        self.lease.release(lambda: self.call("session.end", timeout=3))
        try:
            self.ws.close()
        except Exception:
            pass


def bind(cfg):
    path = runfiles.daemon_socket(cfg)
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    os.chmod(path, 0o600)
    server.listen(16)
    server.settimeout(1.0)
    return server


def serve(cfg, session, server):
    path = runfiles.daemon_socket(cfg)
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
                    session.close()
                    resp = {"ok": True}
                elif "meta" in req:
                    resp = session.meta(req)
                else:
                    resp = {"result": session.call(req["method"], req.get("params"),
                                                   timeout=req.get("timeout", 30.0),
                                                   navigates=bool(req.get("navigates")))}
            except Exception as e:
                resp = ipc.error_reply(e)
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
        session.close()


def take_port_lock(cfg, timeout=ipc.START_TIMEOUT):
    """The one daemon serving a port holds its lock for life, so simultaneous starts can't launch
    Zen twice or race for its session. Returns the lock, or None once another daemon serves."""
    f = runfiles.port_lock(cfg).open("a")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            pass
        if ipc.daemon_alive(cfg):
            f.close()
            return None
        if time.monotonic() > deadline:
            f.close()
            raise BiDiError("another zen-harness daemon for this port is still starting or stopping; retry")
        time.sleep(0.1)


def report(outcome):
    """Tell the client that started us how the start went, then log stdout like stderr."""
    try:
        print(json.dumps(outcome), flush=True)
    except OSError:
        pass  # the client stopped waiting
    os.dup2(2, 1)


def main():
    cfg = config.load()
    lock = session = None
    try:
        lock = take_port_lock(cfg)
        if lock is None:
            report({"served": True})
            return
        session = open_session(cfg)
        server = bind(cfg)
    except Exception as e:
        msg = str(e) if isinstance(e, (connection.ConnectError, ipc.HarnessError)) else traceback.format_exc()
        if session:
            session.close()
        if lock:
            lock.close()  # free the port now: a lease may keep this process alive (lease._park)
        report({"error": msg})
        sys.exit(1)
    report({"ok": True})
    serve(cfg, session, server)


if __name__ == "__main__":
    main()
