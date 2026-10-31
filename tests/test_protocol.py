"""Errors cross the daemon socket as one family (in-process: nothing here pretends to be Zen)."""
import json

import pytest

from zen_harness import ipc

DIALOG = {"type": "beforeunload", "message": "Leave?", "defaultValue": None}


@pytest.mark.parametrize("error", [ipc.DialogOpen(DIALOG), ipc.BrowserError("no such frame: gone", "no such frame"),
                                   ipc.HarnessError("daemon is busy"), ValueError("bad op")])
def test_an_error_crosses_the_socket_as_the_same_kind(error):
    reply = json.loads(json.dumps(ipc.error_reply(error)))
    with pytest.raises(ipc.HarnessError) as raised:
        ipc._raise(reply)
    assert str(raised.value) == str(error)
    if isinstance(error, ipc.HarnessError):
        assert type(raised.value) is type(error)
    assert isinstance(raised.value, RuntimeError)  # agents' `except RuntimeError` keeps working


def test_dialog_open_carries_the_dialog_and_one_message():
    e = ipc.DialogOpen(DIALOG)
    assert e.dialog == DIALOG
    assert str(e) == ("a beforeunload dialog is open in this tab ('Leave?'); answer it with handle_dialog() "
                      "(accept=True leaves the page, accept=False stays) first")


def test_browser_errors_keep_their_bidi_code():
    reply = ipc.error_reply(ipc.BrowserError("no such frame: x", "no such frame"))
    with pytest.raises(ipc.BrowserError) as raised:
        ipc._raise(reply)
    assert raised.value.code == "no such frame"
