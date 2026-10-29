"""Local HTTP server for the fixture pages, with the few routes file:// can't give:
cookies, downloads, a JSON API and slow responses.

    python tests/fixtures/server.py 8771     # serve until Ctrl-C (for manual runs)
"""
import json
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # fixture edits show up on reload
        super().end_headers()

    def _send(self, body, ctype="text/plain", headers=()):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/login":  # sets a session cookie the page can't read
            return self._send("<p>signed in</p>", "text/html", [
                ("Set-Cookie", "sid=s3cr3t; Path=/; HttpOnly; SameSite=Lax"),
                ("Set-Cookie", "theme=dark; Path=/; SameSite=Lax")])
        if url.path == "/api/items":  # JSON API; ?ms= delays the answer
            time.sleep(int(q.get("ms", 0)) / 1000)
            n = int(q.get("page", 1))
            return self._send(json.dumps({"page": n, "items": [f"item {n}.{i}" for i in range(3)],
                                          "cookie": self.headers.get("Cookie", "")}), "application/json")
        if url.path == "/report.csv":  # a server-side download
            return self._send("id,name\n1,Toronto\n", "text/csv",
                              [("Content-Disposition", 'attachment; filename="report.csv"')])
        if url.path == "/archive.bin":  # a download that takes ~1.5 s to arrive
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="archive.bin"')
            self.send_header("Content-Length", str(10 * 65536))
            self.end_headers()
            for _ in range(10):
                self.wfile.write(b"\0" * 65536)
                self.wfile.flush()
                time.sleep(0.15)
            return None
        return super().do_GET()


def start(port=0):
    """Serve in a background thread; returns (server, base_url)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    srv, base = start(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    print(base, flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
