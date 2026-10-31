import io
import json
import socket
import threading

import pytest

from zen_harness import config, connection, marionette

HELLO = {"applicationType": "gecko", "marionetteProtocol": 3}


def test_encode_and_read_packets():
    stream = io.BytesIO(marionette.encode(HELLO) + marionette.encode([1, 1, None, {"value": "é"}]))
    assert marionette.encode([0, 1, "X", {}]) == b'15:[0, 1, "X", {}]'
    assert marionette.read_packet(stream) == HELLO
    assert marionette.read_packet(stream) == [1, 1, None, {"value": "é"}]
    with pytest.raises(EOFError):
        marionette.read_packet(stream)


def test_read_packet_rejects_truncated_and_foreign_data():
    with pytest.raises(EOFError):
        marionette.read_packet(io.BytesIO(b'20:{"a": 1}'))
    with pytest.raises(marionette.MarionetteError):
        marionette.read_packet(io.BytesIO(b"HTTP/1.1 400 Bad Request\r\n"))


def serve_once(handler):
    """A one-connection TCP server on a free port; `handler(conn)` runs in a thread."""
    server = socket.create_server(("127.0.0.1", 0))

    def run():
        conn, _ = server.accept()
        with conn:
            handler(conn)
        server.close()

    threading.Thread(target=run, daemon=True).start()
    return server.getsockname()[1]


def test_client_matches_replies_by_id_and_raises_errors():
    def handler(conn):
        f = conn.makefile("rb")
        conn.sendall(marionette.encode(HELLO))
        _, msg_id, name, params = marionette.read_packet(f)
        assert name == "WebDriver:NewSession" and params == {"webSocketUrl": True}
        conn.sendall(marionette.encode([1, msg_id + 100, None, {"stale": True}]))
        conn.sendall(marionette.encode([1, msg_id, None, {"sessionId": "abc"}]))
        _, msg_id, _, _ = marionette.read_packet(f)
        conn.sendall(marionette.encode([1, msg_id, {"error": "session not created",
                                                    "message": "Maximum number of active sessions"}, None]))

    client = marionette.Client(serve_once(handler))
    assert client.command("WebDriver:NewSession", {"webSocketUrl": True}) == {"sessionId": "abc"}
    with pytest.raises(marionette.MarionetteError, match="session not created: Maximum number"):
        client.command("WebDriver:NewSession")
    client.close()


def test_client_command_times_out():
    done = threading.Event()

    def handler(conn):
        conn.sendall(marionette.encode(HELLO))
        done.wait(5)

    client = marionette.Client(serve_once(handler))
    with pytest.raises(TimeoutError, match="WebDriver:NewSession got no answer within 0.2s"):
        client.command("WebDriver:NewSession", timeout=0.2)
    done.set()
    client.close()


def test_client_refused_without_hello():
    # What Marionette does while another client holds a session.
    with pytest.raises(EOFError):
        marionette.Client(serve_once(lambda conn: None))


def test_read_active_port(tmp_path):
    assert connection.read_active_port(tmp_path) is None
    (tmp_path / "MarionetteActivePort").write_text("2861")
    assert connection.read_active_port(tmp_path) == 2861
    (tmp_path / "MarionetteActivePort").write_text("2861\n")
    assert connection.read_active_port(tmp_path) == 2861
    for bad in ("", "abc", "0", "70000", "-1"):
        (tmp_path / "MarionetteActivePort").write_text(bad)
        assert connection.read_active_port(tmp_path) is None


def test_parse_lsof_ports():
    out = "p123\nf23\nn127.0.0.1:2861\nf29\nn127.0.0.1:9361\nf31\nn[::1]:9361\nf40\nn*:*\n"
    assert connection.parse_lsof_ports(out) == {2861, 9361}
    assert connection.parse_lsof_ports("") == set()


def test_start_command_turns_on_marionette_on_the_configured_port(tmp_path):
    cfg = config.load(env={"ZH_MARIONETTE_PORT": "2861", "ZH_PORT": "9361"}, config_file=tmp_path / "none")
    assert cfg.marionette_port == 2861
    cmd, env = connection.zen_command(cfg, tmp_path)
    assert "--marionette" in cmd
    assert json.loads(env[connection.MARIONETTE_PREFS_ENV]) == {"marionette.port": 2861}
    line = connection.shell_line(cfg, tmp_path)
    assert line.startswith(connection.MARIONETTE_PREFS_ENV + "='{\"marionette.port\": 2861}' ")
    assert "--remote-debugging-port 9361 --marionette" in line
    assert config.Config().marionette_port == 0
