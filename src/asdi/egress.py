"""Per-run egress proxy over a Unix-domain socket.

The runtime container uses Docker ``network=none``.  The only mounted network
resource is this host-side proxy socket.  Destination checks therefore happen
outside the untrusted container and cannot be bypassed through the absent IP
network.
"""

from __future__ import annotations

import ipaddress
import selectors
import socket
import socketserver
import struct
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EgressDecision:
    allowed: bool
    host: str
    port: int
    reason: str
    addresses: tuple[str, ...] = ()


class _EgressHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            first_byte = self.connection.recv(1, socket.MSG_PEEK)
        except OSError:
            return
        if first_byte == b"\x05":
            self._socks5()
            return

        request_line = self.rfile.readline(16_384)
        if not request_line:
            return
        headers: dict[str, str] = {}
        while True:
            line = self.rfile.readline(16_384)
            if not line or line in (b"\r\n", b"\n"):
                break
            try:
                key, value = line.decode("latin-1", errors="replace").split(":", 1)
            except ValueError:
                continue
            headers[key.strip().lower()] = value.strip()

        parts = request_line.decode("latin-1", errors="replace").strip().split()
        if len(parts) < 3:
            self._deny("malformed_request")
            return
        method, target, version = parts[0].upper(), parts[1], parts[2]
        if method == "CONNECT":
            self._connect(target, version)
            return
        if method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            self._absolute_http(method, target, version, headers)
            return
        self._deny("unsupported_method")

    def _socks5(self) -> None:
        proxy: "EgressProxy" = self.server.asdi_proxy
        method_count = self._read_exact(2)[1]
        methods = self._read_exact(method_count)
        if 0 not in methods:
            self.connection.sendall(b"\x05\xff")
            proxy.report(EgressDecision(False, "unknown", 0, "socks_no_acceptable_auth"))
            return
        self.connection.sendall(b"\x05\x00")

        version, command, _, address_type = self._read_exact(4)
        if version != 5:
            self._socks_failure(0x01, "socks_invalid_version")
            return
        if command != 1:
            self._socks_failure(0x07, "socks_command_not_supported")
            return
        try:
            if address_type == 1:
                host = socket.inet_ntop(socket.AF_INET, self._read_exact(4))
            elif address_type == 3:
                host = self._read_exact(self._read_exact(1)[0]).decode(
                    "ascii", errors="strict"
                )
            elif address_type == 4:
                host = socket.inet_ntop(socket.AF_INET6, self._read_exact(16))
            else:
                self._socks_failure(0x08, "socks_address_type_not_supported")
                return
            (port,) = struct.unpack("!H", self._read_exact(2))
        except (OSError, UnicodeDecodeError):
            self._socks_failure(0x01, "socks_malformed_address")
            return

        decision = proxy.authorize(host, port)
        if not decision.allowed:
            code = 0x02 if "private" in decision.reason else 0x05
            self._socks_failure(code, decision.reason, host=host, port=port)
            return
        try:
            remote = socket.create_connection(
                (decision.addresses[0], decision.port), timeout=10
            )
        except OSError as error:
            proxy.report(
                EgressDecision(
                    False,
                    host,
                    port,
                    f"connect_failed:{error}",
                    decision.addresses,
                )
            )
            self._socks_failure(0x01, "connect_failed", host=host, port=port)
            return
        self.connection.sendall(
            b"\x05\x00\x00\x01" + socket.inet_aton("0.0.0.0") + struct.pack("!H", 0)
        )
        bytes_relayed = _relay(self.connection, remote)
        proxy.report(
            EgressDecision(
                True,
                host,
                port,
                "socks_connect_relayed",
                decision.addresses,
            ),
            bytes_relayed=bytes_relayed,
        )
        remote.close()

    def _read_exact(self, count: int) -> bytes:
        chunks: list[bytes] = []
        remaining = count
        while remaining:
            chunk = self.connection.recv(remaining)
            if not chunk:
                raise OSError("truncated SOCKS request")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _socks_failure(
        self,
        code: int,
        reason: str,
        *,
        host: str = "unknown",
        port: int = 0,
    ) -> None:
        proxy: "EgressProxy" = self.server.asdi_proxy
        proxy.report(EgressDecision(False, host, port, reason))
        self.connection.sendall(
            b"\x05" + bytes((code,)) + b"\x00\x01"
            + socket.inet_aton("0.0.0.0") + struct.pack("!H", 0)
        )

    def _connect(self, authority: str, version: str) -> None:
        proxy: "EgressProxy" = self.server.asdi_proxy
        host, port = _split_authority(authority, default_port=443)
        decision = proxy.authorize(host, port)
        if not decision.allowed:
            self._deny(decision.reason, host=host, port=port)
            return
        try:
            remote = socket.create_connection(
                (decision.addresses[0], decision.port), timeout=10
            )
        except OSError as error:
            proxy.report(
                EgressDecision(False, host, port, f"connect_failed:{error}", decision.addresses)
            )
            self._deny("connect_failed")
            return
        self.connection.sendall(f"{version} 200 Connection Established\r\n\r\n".encode("ascii"))
        bytes_relayed = _relay(self.connection, remote)
        proxy.report(
            EgressDecision(True, host, port, "connect_relayed", decision.addresses),
            bytes_relayed=bytes_relayed,
        )
        remote.close()

    def _absolute_http(
        self,
        method: str,
        target: str,
        version: str,
        headers: dict[str, str],
    ) -> None:
        proxy: "EgressProxy" = self.server.asdi_proxy
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            self._deny("unsupported_target")
            return
        host, port = _split_authority(
            parsed.hostname,
            default_port=parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        decision = proxy.authorize(host, port)
        if not decision.allowed:
            self._deny(decision.reason, host=host, port=port)
            return
        try:
            remote = socket.create_connection(
                (decision.addresses[0], decision.port), timeout=10
            )
        except OSError as error:
            proxy.report(
                EgressDecision(False, host, port, f"connect_failed:{error}", decision.addresses)
            )
            self._deny("connect_failed")
            return
        request_target = target if parsed.scheme == "http" else "/"
        forwarded_headers = [
            f"{method} {request_target} {version}\r\n",
            f"Host: {headers.get('host', parsed.netloc)}\r\n",
            "Connection: close\r\n",
        ]
        for key, value in headers.items():
            if key not in {"host", "connection", "proxy-connection", "transfer-encoding"}:
                forwarded_headers.append(f"{key}: {value}\r\n")
        forwarded_headers.append("\r\n")
        remote.sendall("".join(forwarded_headers).encode("latin-1", errors="replace"))
        bytes_relayed = _relay(self.connection, remote)
        proxy.report(
            EgressDecision(True, host, port, "http_relayed", decision.addresses),
            bytes_relayed=bytes_relayed,
        )
        remote.close()

    def _deny(self, reason: str, *, host: str = "unknown", port: int = 0) -> None:
        proxy: "EgressProxy" = self.server.asdi_proxy
        proxy.report(EgressDecision(False, host, port, reason))
        body = b"ASDI egress denied\n"
        self.connection.sendall(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Connection: close\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n"
            + body
        )


class EgressProxy:
    """Host-side allowlist proxy listening on one per-run Unix socket."""

    def __init__(
        self,
        socket_path: str | Path,
        allowlist: tuple[str, ...],
        *,
        reporter: Callable[[EgressDecision, int], None] | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.allow_hosts: set[str] = set()
        self.allow_ports: dict[str, set[int]] = {}
        for endpoint in allowlist:
            host, port = _split_authority(endpoint, default_port=0)
            normalized = host.lower()
            self.allow_hosts.add(normalized)
            self.allow_ports.setdefault(normalized, set()).add(port)
        self.reporter = reporter

        class Server(socketserver.ThreadingUnixStreamServer):
            allow_reuse_address = True
            daemon_threads = True

        Server.allow_reuse_address = True
        Server.daemon_threads = True
        self.server = Server(str(self.socket_path), _EgressHandler)
        self.server.asdi_proxy = self
        os_chmod_socket(self.socket_path)
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name=f"asdi-egress-{self.socket_path.stem}",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def authorize(self, requested_host: str, requested_port: int) -> EgressDecision:
        host = requested_host.strip().lower().rstrip(".")
        if _is_forbidden_literal(host):
            return EgressDecision(False, host, requested_port, "private_destination_forbidden")
        ports = self.allow_ports.get(host, set())
        allowed_port = 0 in ports or requested_port in ports
        if host not in self.allow_hosts or not allowed_port:
            return EgressDecision(False, host, requested_port, "destination_not_allowlisted")
        try:
            infos = socket.getaddrinfo(host, requested_port, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            return EgressDecision(False, host, requested_port, f"dns_failed:{error}")
        addresses: list[str] = []
        for info in infos:
            address = info[4][0]
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
            if not parsed.is_global:
                return EgressDecision(
                    False,
                    host,
                    requested_port,
                    "resolved_private_address_forbidden",
                    tuple(addresses),
                )
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            return EgressDecision(False, host, requested_port, "dns_no_addresses")
        return EgressDecision(
            True,
            host,
            requested_port,
            "allowlisted_global_destination",
            tuple(addresses),
        )

    def report(
        self, decision: EgressDecision, *, bytes_relayed: int = 0
    ) -> None:
        if self.reporter is not None:
            self.reporter(decision, bytes_relayed)


def os_chmod_socket(path: Path) -> None:
    path.chmod(0o660)


def _split_authority(value: str, *, default_port: int) -> tuple[str, int]:
    value = value.strip()
    if value.startswith("[") and "]" in value:
        host, remainder = value[1:].split("]", 1)
        port = int(remainder[1:]) if remainder.startswith(":") else default_port
        return host.lower(), port
    if value.count(":") == 1:
        host, raw_port = value.rsplit(":", 1)
        return host.lower(), int(raw_port)
    return value.lower(), default_port


def _is_forbidden_literal(host: str) -> bool:
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return (
            host == "localhost"
            or host.endswith(".localhost")
            or host.endswith(".local")
            or host.endswith(".internal")
        )


def _relay(client: socket.socket, remote: socket.socket) -> int:
    selector = selectors.DefaultSelector()
    client.setblocking(False)
    remote.setblocking(False)
    selector.register(client, selectors.EVENT_READ, remote)
    selector.register(remote, selectors.EVENT_READ, client)
    total = 0
    while True:
        for key, _ in selector.select(timeout=1):
            source: socket.socket = key.fileobj  # type: ignore[assignment]
            target: socket.socket = key.data
            try:
                data = source.recv(65_536)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                selector.close()
                client.close()
                remote.close()
                return total
            if not data:
                selector.close()
                client.close()
                remote.close()
                return total
            total += len(data)
            offset = 0
            while offset < len(data):
                try:
                    offset += target.send(data[offset:])
                except (BlockingIOError, InterruptedError):
                    continue
    selector.close()
    return total
