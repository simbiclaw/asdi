from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .store import NoteCreationError, NoteStore


UI_FLAG = "NOTES_UI_ENABLED"


def ui_enabled() -> bool:
    return os.environ.get(UI_FLAG, "").strip().lower() in {"1", "true", "on", "yes"}


class Metrics:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.counts: dict[tuple[str, str], int] = defaultdict(int)
        self.durations: dict[tuple[str, str], float] = defaultdict(float)
        self.lock = threading.Lock()

    def observe(self, method: str, path: str, elapsed: float) -> None:
        with self.lock:
            self.counts[(method, path)] += 1
            self.durations[(method, path)] += elapsed

    def render(self, note_count: int) -> str:
        lines = [
            "# HELP toy_notes_requests_total Requests handled by this process.",
            "# TYPE toy_notes_requests_total counter",
        ]
        with self.lock:
            for (method, path), count in sorted(self.counts.items()):
                lines.append(f'toy_notes_requests_total{{method="{method}",path="{_escape(path)}"}} {count}')
                lines.append(
                    "toy_notes_request_duration_seconds_sum"
                    f'{{method="{method}",path="{_escape(path)}"}} {self.durations[(method, path)]:.6f}'
                )
                lines.append(
                    "toy_notes_request_duration_seconds_count"
                    f'{{method="{method}",path="{_escape(path)}"}} {count}'
                )
        lines.extend(
            [
                "# HELP toy_notes_notes_total Notes currently stored.",
                "# TYPE toy_notes_notes_total gauge",
                f"toy_notes_notes_total {note_count}",
                "# HELP toy_notes_process_uptime_seconds Process uptime.",
                "# TYPE toy_notes_process_uptime_seconds gauge",
                f"toy_notes_process_uptime_seconds {time.monotonic() - self.started:.3f}",
            ]
        )
        return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class ToyHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], store: NoteStore) -> None:
        super().__init__(address, handler)
        self.store = store
        self.metrics = Metrics()


class ToyRequestHandler(BaseHTTPRequestHandler):
    server_version = "toy-notes/1"
    protocol_version = "HTTP/1.1"

    @property
    def store(self) -> NoteStore:
        return self.server.store

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        started = time.monotonic()
        path = urlsplit(self.path).path
        try:
            self._route_get(path)
        finally:
            self.server.metrics.observe("GET", path, time.monotonic() - started)

    def do_POST(self) -> None:
        started = time.monotonic()
        path = urlsplit(self.path).path
        try:
            self._route_post(path)
        finally:
            self.server.metrics.observe("POST", path, time.monotonic() - started)

    def _route_get(self, path: str) -> None:
        if path == "/healthz":
            self._send_json(200, {"status": "ok", "service": "toy-notes"})
        elif path == "/readyz":
            try:
                self.store.count()
                self._send_json(200, {"status": "ready", "db": "ok"})
            except sqlite3.Error as error:
                self._send_json(503, {"status": "not_ready", "db": str(error)})
        elif path == "/metrics":
            body = self.server.metrics.render(self.store.count()).encode("utf-8")
            self._send_bytes(200, "text/plain; version=0.0.4; charset=utf-8", body)
        elif path == "/notes":
            self._send_json(200, {"notes": self.store.list()})
        elif path == "/notes/ui":
            if not ui_enabled():
                self._send_json(404, {"error": "ui_disabled"})
            else:
                self._send_ui()
        else:
            self._send_json(404, {"error": "not_found"})

    def _route_post(self, path: str) -> None:
        if path != "/notes":
            self._send_json(404, {"error": "not_found"})
            return
        try:
            payload = self._read_payload()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self._send_json(400, {"error": f"invalid body: {error}"})
            return
        title = str(payload.get("title", "")).strip()
        body = str(payload.get("body", ""))
        if not title:
            self._send_json(400, {"error": "title must not be empty"})
            return
        try:
            note = self.store.create(title, body)
            self._send_json(201, note)
        except NoteCreationError as error:
            self._send_json(500, {"error": str(error)})
        except (ValueError, sqlite3.Error) as error:
            self._send_json(400, {"error": str(error)})

    def _read_payload(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("empty body")
        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value
        if content_type.startswith("application/x-www-form-urlencoded"):
            parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
            return {key: values[0] for key, values in parsed.items()}
        raise ValueError("unsupported content type")

    def _send_ui(self) -> None:
        notes = self.store.list()
        items = "".join(
            f'<li id="note-{note["id"]}">{html.escape(str(note["title"]))}</li>'
            for note in notes
        )
        document = (
            "<!doctype html>\n"
            '<html lang="en">\n'
            "<head><meta charset=\"utf-8\"><title>Toy notes</title></head>\n"
            "<body>\n"
            "<h1>Toy notes</h1>\n"
            f'<ul id="notes">{items}</ul>\n'
            '<form method="post" action="/notes">\n'
            '<label>Title <input name="title" type="text"></label>\n'
            '<label>Body <textarea name="body"></textarea></label>\n'
            '<button type="submit">Create</button>\n'
            "</form>\n"
            "</body>\n"
            "</html>\n"
        )
        self._send_bytes(200, "text/html; charset=utf-8", document.encode("utf-8"))

    def _send_json(self, status: int, payload: object) -> None:
        body = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="toy-notes-server")
    parser.add_argument("--db", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file")
    arguments = parser.parse_args(argv)

    store = NoteStore(arguments.db)
    store.initialize()
    server = ToyHTTPServer((arguments.host, arguments.port), ToyRequestHandler, store)
    port = int(server.server_address[1])
    if arguments.port_file:
        Path(arguments.port_file).write_text(str(port), encoding="utf-8")
    print(f"toy-notes listening on {arguments.host}:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
