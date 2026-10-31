"""The page settle module, fed recorded event sequences in-process (no browser; see ADR-0007).
The agent-facing waits are covered against real Zen in test_navigation.py."""
import threading
import time

from zen_harness.settle import GRACE, PageSettle

TAB, FRAME, NESTED, OTHER = "tab-uuid", "101", "102", "other-uuid"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def pages(ready=True):
    clock = Clock()
    p = PageSettle(document_ready=lambda tab: ready, clock=clock)
    for ctx, parent in ((TAB, None), (FRAME, TAB), (NESTED, FRAME), (OTHER, None)):
        p.event("browsingContext.contextCreated", {"context": ctx, "parent": parent})
    return p, clock


def state(p, ctx=TAB, need_load=True):
    return p.wait(ctx, need_load, 0)["state"]


def ev(p, name, ctx=TAB, **params):
    p.event(f"browsingContext.{name}", {"context": ctx, **params})


def test_a_tab_without_navigation_causes_is_settled():
    p, _ = pages()
    assert state(p) == "settled"


def test_a_cause_without_navigation_settles_after_the_grace_period():
    p, clock = pages()
    p.cause(TAB)
    assert state(p) == "timeout"
    clock.t += GRACE + 0.001
    assert state(p) == "settled"


def test_a_navigation_holds_until_commit_or_load():
    p, clock = pages()
    p.cause(TAB)
    ev(p, "navigationStarted", navigation="n1")
    clock.t += 5
    assert state(p, need_load=False) == "timeout"
    ev(p, "navigationCommitted", navigation="n1")
    assert state(p, need_load=False) == "settled"
    assert state(p, need_load=True) == "timeout"
    ev(p, "load", navigation="n1")
    assert state(p) == "settled"


def test_a_superseded_navigation_does_not_end_the_new_one():
    p, _ = pages()
    p.cause(TAB)
    ev(p, "navigationStarted", navigation="n1")
    ev(p, "navigationStarted", navigation="n2")
    ev(p, "load", navigation="n1")
    assert state(p) == "timeout"
    ev(p, "load", navigation="n2")
    assert state(p) == "settled"


def test_fragment_navigation_and_download_end_a_navigation():
    p, _ = pages()
    p.cause(TAB)
    ev(p, "navigationStarted", navigation="n1")
    ev(p, "fragmentNavigated", navigation=None)  # Zen reports no id for anchor jumps
    assert state(p) == "settled"
    p.cause(TAB)
    ev(p, "navigationStarted", navigation="n2")
    ev(p, "downloadWillBegin", navigation="n2")
    assert state(p) == "settled"


def test_staying_on_the_page_at_a_beforeunload_prompt_ends_the_navigation():
    p, _ = pages()
    p.cause(TAB)
    ev(p, "navigationStarted", navigation="n1")
    ev(p, "userPromptOpened", type="beforeunload", message="Leave?")
    assert p.wait(TAB, True, 0) == {"state": "dialog", "dialog": {
        "type": "beforeunload", "message": "Leave?", "defaultValue": None}}
    ev(p, "userPromptClosed", type="beforeunload", accepted=False)
    assert state(p) == "settled"


def test_leaving_at_a_beforeunload_prompt_keeps_waiting_for_the_new_page():
    p, _ = pages()
    p.cause(TAB)
    ev(p, "navigationStarted", navigation="n1")
    ev(p, "userPromptOpened", type="beforeunload", message="Leave?")
    ev(p, "userPromptClosed", type="beforeunload", accepted=True)
    assert state(p) == "timeout"


def test_a_cause_in_a_frame_belongs_to_its_tab():
    p, clock = pages()
    p.cause(NESTED)
    assert state(p, TAB) == "timeout"
    ev(p, "navigationStarted", navigation="n1")  # e.g. a target=_top link in the frame
    ev(p, "load", navigation="n1")
    assert state(p, TAB) == "settled"


def test_a_frame_navigating_alone_does_not_hold_its_tab():
    p, clock = pages()
    ev(p, "navigationStarted", ctx=FRAME, navigation="f1")
    assert state(p, TAB) == "settled"


def test_a_cause_in_another_tab_does_not_hold_this_one():
    p, _ = pages()
    p.cause(OTHER)
    assert state(p, TAB) == "settled"
    assert state(p, OTHER) == "timeout"


def test_a_dialog_in_a_nested_frame_belongs_to_its_tab():
    p, _ = pages()
    ev(p, "userPromptOpened", ctx=NESTED, type="alert", message="hi")
    assert p.dialog(TAB)["message"] == "hi"
    assert p.dialog(FRAME)["message"] == "hi"
    assert state(p, TAB) == "dialog"
    ev(p, "userPromptClosed", ctx=NESTED, type="alert", accepted=True)
    assert p.dialog(TAB) is None


def test_frames_are_forgotten_with_their_tab():
    p, _ = pages()
    ev(p, "contextDestroyed")
    assert p.tab_of(NESTED) == NESTED
    assert p.tab_of(FRAME) == FRAME


def test_frames_replayed_before_their_tab_still_resolve():
    p = PageSettle()
    p.event("browsingContext.contextCreated", {"context": NESTED, "parent": FRAME})
    p.event("browsingContext.contextCreated", {"context": FRAME, "parent": TAB})
    p.event("browsingContext.contextCreated", {"context": TAB, "parent": None})
    assert p.tab_of(NESTED) == TAB


def test_a_load_that_happened_unseen_is_checked_on_the_document():
    p, _ = pages(ready=False)
    assert state(p, need_load=True) == "timeout"
    assert state(p, need_load=False) == "settled"


def test_wait_wakes_on_the_event_that_settles_the_tab():
    p = PageSettle()
    p.event("browsingContext.contextCreated", {"context": TAB, "parent": None})
    p.cause(TAB)
    p.event("browsingContext.navigationStarted", {"context": TAB, "navigation": "n1"})
    threading.Timer(0.2, p.event, ("browsingContext.load", {"context": TAB, "navigation": "n1"})).start()
    start = time.monotonic()
    assert p.wait(TAB, True, 5)["state"] == "settled"
    assert 0.15 < time.monotonic() - start < 1
