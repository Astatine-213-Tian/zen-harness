"""Just enough of a Marionette (WebDriver classic over TCP) client to own a session.

Marionette deletes its session when the TCP connection closes, even after `kill -9`,
so a session created here never outlives the daemon. Packets are `<length>:<json>`;
the server sends a hello first, commands are `[0, id, name, params]` and replies
`[1, id, error, result]`.
"""
import itertools
import json
import socket


class MarionetteError(RuntimeError):
    pass


def encode(msg) -> bytes:
    body = json.dumps(msg).encode()
    return str(len(body)).encode() + b":" + body


def read_packet(f):
    """Next packet from a binary file object. EOFError if the peer closed the connection."""
    size = b""
    while (c := f.read(1)) != b":":
        if not c:
            raise EOFError("Marionette closed the connection")
        if not c.isdigit() or len(size) > 9:
            raise MarionetteError("not a Marionette server")
        size += c
    body = f.read(int(size))
    if len(body) < int(size):
        raise EOFError("Marionette closed the connection")
    return json.loads(body)


class Client:
    def __init__(self, port, timeout=5.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.file = self.sock.makefile("rb")
        self.ids = itertools.count(1)
        try:
            # Marionette closes the connection without a hello while another client holds a session.
            hello = read_packet(self.file)
            if not isinstance(hello, dict) or hello.get("applicationType") != "gecko":
                raise MarionetteError("not a Marionette server")
        except Exception:
            self.close()
            raise

    def command(self, name, params=None, timeout=30.0):
        msg_id = next(self.ids)
        self.sock.settimeout(timeout)
        try:
            self.sock.sendall(encode([0, msg_id, name, params or {}]))
            while True:
                msg = read_packet(self.file)
                if isinstance(msg, list) and len(msg) == 4 and msg[0] == 1 and msg[1] == msg_id:
                    break
        except TimeoutError:
            raise TimeoutError(f"{name} got no answer within {timeout:g}s") from None
        if msg[2]:
            raise MarionetteError(f"{msg[2].get('error')}: {msg[2].get('message', '')}".strip())
        return msg[3]

    def close(self):
        try:
            self.file.close()
            self.sock.close()
        except OSError:
            pass
