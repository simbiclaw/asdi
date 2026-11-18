#!/usr/bin/env python3
"""Local test-only server that returns the request's Authorization header."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps(
            {"authorization": self.headers.get("Authorization")}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 4000), Handler).serve_forever()
