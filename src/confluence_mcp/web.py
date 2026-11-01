"""Local web page where a person approves queued Confluence writes."""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import queue
from .apply import approve_and_apply
from .web_page import PAGE

COOKIE = "cmr_session"
MAX_BODY = 64 * 1024
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'"
_ACTIVE = ("pending", "approved", "executing")
_FIELDS = (
    "id", "status", "action", "kind", "space_key", "page_id", "version_before",
    "summary", "preview", "result", "error", "created_at", "updated_at",
)
_FINISHED_SHOWN = 20
# Serializes sends so two clicks on one operation cannot race for the claim.
_apply_lock = threading.Lock()


def _state() -> dict[str, Any]:
    ops = queue.list_ops()
    active = [op for op in ops if op["status"] in _ACTIVE]
    finished = sorted(
        (op for op in ops if op["status"] not in _ACTIVE), key=lambda op: op["updated_at"]
    )[-_FINISHED_SHOWN:]
    return {"operations": [{key: op[key] for key in _FIELDS} for op in active + finished]}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # The request line of the first visit carries the token, so log nothing.
        pass

    def _send(
        self,
        status: int,
        body: bytes = b"",
        content_type: str = "application/json",
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"))

    def _deny(self) -> None:
        self._json(403, {"error": "forbidden"})

    def _hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        # Rejecting other Host values stops DNS-rebinding pages from reaching us.
        return self.headers.get("Host") in self._hosts()

    def _authorized(self, require_origin: bool) -> bool:
        if not self._host_ok():
            return False
        if require_origin and self.headers.get("Origin") not in {
            f"http://{host}" for host in self._hosts()
        }:
            return False
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        morsel = jar.get(COOKIE)
        return morsel is not None and secrets.compare_digest(
            morsel.value.encode("utf-8"), self.server.token.encode("utf-8")
        )

    def _drain(self) -> None:
        # Discard (never parse) a bounded request body so closing the socket does not
        # reset the connection before the client reads our answer.
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if length > 0:
            self.rfile.read(min(length, MAX_BODY))

    def _read_ids(self) -> list[str] | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if not 0 < length <= MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            return None
        ids = data.get("ids") if isinstance(data, dict) else None
        if not isinstance(ids, list) or not 1 <= len(ids) <= 200:
            return None
        if not all(isinstance(item, str) for item in ids):
            return None
        return ids

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        token = parse_qs(url.query).get("token")
        if url.path == "/" and token:
            if self._host_ok() and secrets.compare_digest(
                token[0].encode("utf-8"), self.server.token.encode("utf-8")
            ):
                cookie = f"{COOKIE}={self.server.token}; HttpOnly; SameSite=Strict; Path=/"
                self._send(302, headers=(("Location", "/"), ("Set-Cookie", cookie)))
            else:
                self._deny()
            return
        if not self._authorized(False):
            self._deny()
        elif url.path == "/":
            self._send(
                200,
                PAGE.encode("utf-8"),
                "text/html; charset=utf-8",
                (("Content-Security-Policy", CSP),),
            )
        elif url.path == "/api/state":
            self._json(200, _state())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized(True):
            self._drain()
            self._deny()
            return
        path = urlsplit(self.path).path
        if path not in ("/api/approve", "/api/reject"):
            self._drain()
            self._json(404, {"error": "not found"})
            return
        ids = self._read_ids()
        if ids is None:
            self._json(400, {"error": "ids must be a list of 1 to 200 strings"})
            return
        try:
            if path == "/api/approve":
                with _apply_lock:
                    result = approve_and_apply(self.server.client, ids)
            else:
                result = {"rejected": queue.reject(ids)}
        except Exception as exc:
            self._json(500, {"error": str(exc)})
            return
        self._json(200, result)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], client: Any, token: str) -> None:
        super().__init__(address, _Handler)
        self.client = client
        self.token = token


def make_server(
    client: Any, token: str, host: str = "127.0.0.1", port: int = 0
) -> ThreadingHTTPServer:
    return _Server((host, port), client, token)


def serve(client: Any) -> None:
    """Run the approval page until Ctrl+C."""
    token = secrets.token_urlsafe(32)
    server = make_server(client, token)
    url = f"http://127.0.0.1:{server.server_address[1]}/?token={token}"
    print(f"Approval page: {url}\nPress Ctrl+C to stop.", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
