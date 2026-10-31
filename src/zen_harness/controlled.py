"""Controlled tabs (see GLOSSARY.md): which tab each agent acts on, and the marker on its title.

The daemon owns this so the marker can't drift from the truth: setting an agent's tab moves the
marker, a preload script limited to that tab marks every document it loads (however it got
there, waited for or not), and stopping takes every marker off once. Agents that run in
parallel set ZH_AGENT to get a tab each; the rest share the "" agent's tab.
"""
import json
import threading

from .ipc import HarnessError

# Marker code runs in its own sandbox, so pages never see it (and can't break it).
SANDBOX = "zen-harness"

# Pages that set their own title (single-page apps do on every route) would drop a prefix set
# once, so an observer puts it back. It never creates a <title> while the page is still loading,
# which would hide the page's own, and frames keep their titles.
_MARK_FN = """() => {
  if (window !== window.top) return;
  const m = %s;
  window.__zhMarker = m;
  const fix = () => {
    const m = window.__zhMarker;
    if (!m || document.title.startsWith(m)) return;
    if (document.readyState === 'loading' && !document.querySelector('title')) return;
    document.title = m + document.title;
  };
  if (!window.__zhMarkObs) {
    const opts = {subtree: true, childList: true, characterData: true};
    let onHead = false;
    window.__zhMarkObs = new MutationObserver(() => {
      if (!onHead && document.head) {  // watch only <head> once it exists: big pages mutate a lot
        onHead = true;
        window.__zhMarkObs.disconnect();
        window.__zhMarkObs.observe(document.head, opts);
      }
      fix();
    });
    window.__zhMarkObs.observe(document.head || document, opts);
    onHead = !!document.head;
    document.addEventListener('DOMContentLoaded', fix);
  }
  fix();
}"""

_UNMARK_FN = """() => {
  const m = window.__zhMarker;
  window.__zhMarker = null;
  if (window.__zhMarkObs) { window.__zhMarkObs.disconnect(); window.__zhMarkObs = null; }
  if (m && document.title.startsWith(m)) document.title = document.title.slice(m.length);
}"""


class ControlledTabs:
    def __init__(self, call, marker):
        """call(method, params, timeout=...) sends one BiDi command; marker "" turns marking off."""
        self.call = call
        self.mark_fn = _MARK_FN % json.dumps(marker + " ") if marker else None
        self.tabs = {}  # agent -> controlled tab
        self.preloads = {}  # marked tab -> its preload script id
        self.lock = threading.Lock()  # serialises control() and release(); never held by forget()
        self.released = False

    def get(self, agent=""):
        return self.tabs.get(agent)

    def control(self, agent, ctx):
        """Make ctx the agent's controlled tab and move the marker to it."""
        tree = self.call("browsingContext.getTree", {"root": ctx, "maxDepth": 0}, timeout=5)["contexts"]
        if not tree or tree[0].get("parent"):
            raise HarnessError(f"{ctx!r} is a frame, not a tab; pass frames to js(..., target_id=...)")
        with self.lock:
            old = self.tabs.get(agent)
            self.tabs[agent] = ctx
            if ctx not in self.preloads:
                self._mark(ctx)
            if old and old != ctx and old not in self.tabs.values():
                self._unmark(old)
        return ctx

    def forget(self, ctx):
        """The tab closed. Runs on the event reader thread, so it sends nothing to Zen."""
        for agent in [a for a, c in list(self.tabs.items()) if c == ctx]:
            self.tabs.pop(agent, None)
        self.preloads.pop(ctx, None)

    def release(self):
        """Take every marker off (session end). Safe to call more than once."""
        with self.lock:
            if self.released:
                return
            self.released = True
            for ctx in list(self.preloads):
                self._unmark(ctx)
            self.tabs.clear()

    def _mark(self, ctx):
        if not self.mark_fn:
            return
        self.preloads[ctx] = self.call("script.addPreloadScript", {
            "functionDeclaration": self.mark_fn, "contexts": [ctx], "sandbox": SANDBOX}, timeout=5)["script"]
        self._run(ctx, self.mark_fn)  # the document already there

    def _unmark(self, ctx):
        script = self.preloads.pop(ctx, None)
        if script:
            try:
                self.call("script.removePreloadScript", {"script": script}, timeout=2)
            except Exception:
                pass
            self._run(ctx, _UNMARK_FN)

    def _run(self, ctx, fn):
        try:
            self.call("script.callFunction", {"functionDeclaration": fn, "awaitPromise": False,
                                              "target": {"context": ctx, "sandbox": SANDBOX}}, timeout=2)
        except Exception:
            pass  # mid-navigation: the preload marks the next document
