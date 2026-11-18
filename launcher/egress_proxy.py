#!/usr/bin/env python3
"""Thin per-run egress authority used by the REV K launcher.

The agent receives only an HTTP proxy URL.  CONNECT destinations are resolved
and authorized outside the agent sandbox.  The selected local-model endpoint is
proxied over plain HTTP so the launcher can inject its credential into the
proxy process without placing a key in the agent container.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import sys
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True)
class EgressAuthority:
    allowed_connect: frozenset[tuple[str, int]]
    model_host: str
    model_port: int
    model_key: str | None

    @staticmethod
    def _addresses(host: str) -> tuple[str, ...]:
        try:
            return tuple(address[4][0] for address in socket.getaddrinfo(host, None))
        except socket.gaierror:
            return ()

    @staticmethod
    def _private(host: str, addresses: tuple[str, ...]) -> bool:
        if not addresses:
            return True
        return any(
            ipaddress.ip_address(address).is_private
            or ipaddress.ip_address(address).is_loopback
            or ipaddress.ip_address(address).is_link_local
            or ipaddress.ip_address(address).is_reserved
            for address in addresses
        )

    def decide(self, host: str, port: int) -> tuple[bool, str, tuple[str, ...]]:
        host = host.lower().strip(".")
        addresses = self._addresses(host)
        if (host, port) in self.allowed_connect:
            if self._private(host, addresses):
                return False, "private_destination_forbidden", addresses
            return True, "allowlisted_connect", addresses
        if host == self.model_host and port == self.model_port:
            return True, "local_model_proxy", addresses
        return False, "destination_not_allowlisted", addresses


class EgressHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def authority(self) -> EgressAuthority:
        return self.server.asdi_authority  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("asdi-egress " + format % args + "\n")

    def do_CONNECT(self) -> None:
        host, port = self._split_authority(self.path, 443)
        allowed, reason, addresses = self.authority.decide(host, port)
        if not allowed:
            self.send_error(403, reason)
            return
        try:
            remote = socket.create_connection((addresses[0], port), timeout=15)
        except OSError:
            self.send_error(502, "connect_failed")
            return
        try:
            self.connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.log_message("CONNECT %s:%s authorized reason=%s", host, port, reason)
            self._relay(remote)
        finally:
            remote.close()

    def do_GET(self) -> None:
        self._proxy_http("GET")

    def do_POST(self) -> None:
        self._proxy_http("POST")

    def do_PUT(self) -> None:
        self._proxy_http("PUT")

    def do_PATCH(self) -> None:
        self._proxy_http("PATCH")

    def do_DELETE(self) -> None:
        self._proxy_http("DELETE")

    def _proxy_http(self, method: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.scheme != "http" or not parsed.hostname:
            self.send_error(400, "only_absolute_http_is_supported")
            return
        host = parsed.hostname.lower()
        port = parsed.port or 80
        allowed, reason, addresses = self.authority.decide(host, port)
        if not allowed:
            self.send_error(403, reason)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in {"host", "connection", "proxy-connection", "authorization", "proxy-authorization"}
        }
        headers["Host"] = self.headers.get("Host", parsed.netloc)
        if host == self.authority.model_host and self.authority.model_key:
            headers["Authorization"] = f"Bearer {self.authority.model_key}"
        try:
            connection = http.client.HTTPConnection(addresses[0], port, timeout=30)
            origin_path = parsed.path or "/"
            if parsed.query:
                origin_path += "?" + parsed.query
            connection.request(method, origin_path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
        except OSError as error:
            self.send_error(502, f"connect_failed:{error}")
            return
        if response.status >= 400:
            body = payload[:4000].decode("utf-8", errors="replace")
            sys.stderr.write(
                json.dumps(
                    {
                        "asdi_egress_error": {
                            "host": host,
                            "port": port,
                            "path": parsed.path,
                            "status": response.status,
                            "body": body,
                        }
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        try:
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "transfer-encoding"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(payload)
        finally:
            connection.close()

    def _split_authority(self, value: str, default_port: int) -> tuple[str, int]:
        authority = value.removeprefix("//")
        if ":" not in authority:
            return authority.lower(), default_port
        host, raw_port = authority.rsplit(":", 1)
        try:
            return host.lower(), int(raw_port)
        except ValueError:
            return host.lower(), default_port

    def _relay(self, remote: socket.socket) -> None:
        sockets = (self.connection, remote)
        import selectors

        while True:
            try:
                selector = selectors.DefaultSelector()
                for source in sockets:
                    selector.register(source, selectors.EVENT_READ)
                events = selector.select(timeout=120)
                selector.close()
            except (OSError, ValueError):
                return
            if not events:
                return
            for key, _events in events:
                peer = remote if key.fileobj is self.connection else self.connection
                try:
                    data = key.fileobj.recv(65536)  # type: ignore[union-attr]
                except OSError:
                    return
                if not data:
                    return
                peer.sendall(data)


def main() -> int:
    allowlist: set[tuple[str, int]] = set()
    for item in os.environ.get(
            "ASDI_EGRESS_ALLOWLIST",
            "github.com:443,api.github.com:443,objects.githubusercontent.com:443,codeload.github.com:443,pypi.org:443,files.pythonhosted.org:443,registry.npmjs.org:443,registry.npmmirror.com:443",
    ).split(","):
        if not item:
            continue
        host, separator, raw_port = item.rpartition(":")
        if not separator:
            raise ValueError(f"invalid egress allowlist entry: {item}")
        allowlist.add((host.lower(), int(raw_port)))
    authority = EgressAuthority(
        allowed_connect=frozenset(allowlist),
        model_host=os.environ.get("ASDI_MODEL_HOST", "host.docker.internal"),
        model_port=int(os.environ.get("ASDI_MODEL_PORT", "4000")),
        model_key=os.environ.get("ASDI_MODEL_API_KEY"),
    )
    server = ThreadingHTTPServer(("0.0.0.0", 8081), EgressHandler)
    server.asdi_authority = authority  # type: ignore[attr-defined]
    server.daemon_threads = True
    print(
        json.dumps(
            {
                "status": "listening",
                "port": 8081,
                "allowlist": sorted(f"{host}:{port}" for host, port in authority.allowed_connect),
                "model_endpoint": f"{authority.model_host}:{authority.model_port}",
                "model_key_configured": authority.model_key is not None,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
