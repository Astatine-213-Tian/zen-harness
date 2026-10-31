"""The page settle module: knows when a tab is settled (see GLOSSARY.md).

The daemon feeds it every navigation cause and every browsingContext event; helpers ask it
to wait. State is per tab: a navigation cause or dialog in a frame belongs to the tab that
holds the frame, while navigations of a frame alone don't move the tab. Zen reports each
context's parent in contextCreated, and replays that event for every existing tab and frame
when a session subscribes, so the frame tree needs no lookups.
"""
import threading
import time

GRACE = 0.3  # seconds a navigation cause gets to show up as a navigation

_NAVIGATION_DONE = ("browsingContext.load", "browsingContext.navigationFailed",
                    "browsingContext.fragmentNavigated", "browsingContext.downloadWillBegin")


class PageSettle:
    def __init__(self, document_ready=lambda tab: True, clock=time.monotonic):
        """document_ready(tab) -> bool: whether the tab's document finished loading, for tabs
        whose load happened before this module saw it. It is called without the lock held."""
        self.document_ready = document_ready
        self.clock = clock
        self.cond = threading.Condition()
        self.parent = {}  # context -> parent context; None for a tab
        self.navigating = {}  # tab -> [navigation id, committed?] of its started, unfinished navigation
        self.last_cause = {}  # tab -> time of its last navigation cause
        self.last_nav = {}  # tab -> time its last navigation started
        self.dialogs = {}  # tab -> {type, message, defaultValue} of its open dialog

    def tab_of(self, ctx):
        with self.cond:
            return self._tab(ctx)

    def cause(self, ctx):
        """Record a navigation cause aimed at ctx (a tab or a frame in it)."""
        with self.cond:
            self.last_cause[self._tab(ctx)] = self.clock()

    def dialog(self, ctx):
        """The dialog open in ctx's tab, or None."""
        with self.cond:
            return self.dialogs.get(self._tab(ctx))

    def event(self, method, p):
        """Feed one browsingContext event. Returns the tab it concerns."""
        ctx = p.get("context")
        with self.cond:
            if method == "browsingContext.contextCreated":
                self.parent[ctx] = p.get("parent")
            tab = self._tab(ctx)
            is_tab = self.parent.get(ctx) is None
            nav = p.get("navigation")
            if method == "browsingContext.navigationStarted" and is_tab:
                # One navigation at a time per tab: a new one supersedes (aborts) the last.
                self.navigating[tab] = [nav, False]
                self.last_nav[tab] = self.clock()
            elif method == "browsingContext.navigationCommitted" and is_tab:
                if self.navigating.get(tab, [None])[0] == nav:
                    self.navigating[tab][1] = True  # the new document is in place
            elif method in _NAVIGATION_DONE and is_tab:
                if nav is None or self.navigating.get(tab, [None])[0] == nav:
                    self.navigating.pop(tab, None)
            elif method == "browsingContext.userPromptOpened":
                self.dialogs[tab] = {k: p.get(k) for k in ("type", "message", "defaultValue")}
            elif method == "browsingContext.userPromptClosed":
                self.dialogs.pop(tab, None)
                if p.get("type") == "beforeunload" and not p.get("accepted"):
                    self.navigating.pop(tab, None)  # stayed on the page
            elif method == "browsingContext.contextDestroyed":
                gone = {c for c in self.parent if self._descends(c, ctx)} | {ctx}
                for c in gone:
                    self.parent.pop(c, None)
                if is_tab:
                    for d in (self.navigating, self.last_cause, self.last_nav, self.dialogs):
                        d.pop(ctx, None)
            self.cond.notify_all()
            return tab

    def wait(self, ctx, need_load, timeout):
        """Wait until ctx's tab is settled: its new document in place, or with need_load also
        loaded. Returns {"state": "settled" | "dialog" | "timeout", "dialog": ...}.
        timeout=0 only checks."""
        end = self.clock() + timeout
        while True:
            with self.cond:
                tab = self._tab(ctx)
                while True:
                    now = self.clock()
                    state, wake = self._check(tab, need_load, now)
                    if state == "dialog":
                        return {"state": "dialog", "dialog": self.dialogs[tab]}
                    if state == "settled":
                        break
                    if now >= end:
                        return {"state": "timeout", "dialog": None}
                    self.cond.wait(min(end, wake or end) - now)
            if not need_load or self.document_ready(tab):
                return {"state": "settled", "dialog": None}
            if self.clock() >= end:
                return {"state": "timeout", "dialog": None}
            with self.cond:  # its load event may still come; poll in case it came before we looked
                self.cond.wait(min(0.05, end - self.clock()))

    def _check(self, tab, need_load, now):
        if tab in self.dialogs:
            return "dialog", None
        nav = self.navigating.get(tab)
        if nav and (need_load or not nav[1]):
            return "pending", None  # an event will end it
        cause, started = self.last_cause.get(tab), self.last_nav.get(tab)
        if cause is None or (started is not None and started >= cause) or now - cause >= GRACE:
            return "settled", None
        return "pending", cause + GRACE

    def _tab(self, ctx):
        seen = set()
        while self.parent.get(ctx) is not None and ctx not in seen:
            seen.add(ctx)
            ctx = self.parent[ctx]
        return ctx

    def _descends(self, ctx, ancestor):
        seen = set()
        while (ctx := self.parent.get(ctx)) is not None and ctx not in seen:
            if ctx == ancestor:
                return True
            seen.add(ctx)
        return False
