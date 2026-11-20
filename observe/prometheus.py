"""Stdlib Prometheus text metrics and a loopback-only text endpoint."""

from __future__ import annotations

import argparse
import os
import re
import resource
import sys
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Sequence
from urllib.request import ProxyHandler, build_opener

METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class MetricsError(ValueError):
    """Raised for an invalid metric name or label."""


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels_text(labels: dict[str, str]) -> str:
    for name, value in labels.items():
        if not LABEL_NAME.fullmatch(name):
            raise MetricsError(f"invalid label name: {name}")
        if not isinstance(value, str):
            raise MetricsError(f"label {name} must be a string")
    if not labels:
        return ""
    joined = ",".join(f'{name}="{_escape_label(value)}"' for name, value in sorted(labels.items()))
    return "{" + joined + "}"


class MetricRegistry:
    def __init__(self) -> None:
        self._started = time.monotonic()
        self._lock = threading.Lock()
        self._request_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self._duration_sums: dict[tuple[str, str, str], float] = defaultdict(float)
        self._duration_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def observe_request(
        self, *, method: str, path: str, status: int, duration_seconds: float
    ) -> None:
        if duration_seconds < 0:
            raise MetricsError("duration cannot be negative")
        key = (str(method), str(path), str(status))
        with self._lock:
            self._request_counts[key] += 1
            self._duration_counts[key] += 1
            self._duration_sums[key] += duration_seconds

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        if not METRIC_NAME.fullmatch(name):
            raise MetricsError(f"invalid metric name: {name}")
        label_items = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._gauges[(name, label_items)] = value

    def render(self) -> str:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
        lines = [
            "# HELP asdi_requests_total Requests observed by this process.",
            "# TYPE asdi_requests_total counter",
            "# HELP asdi_request_duration_seconds Request latency observed by this process.",
            "# TYPE asdi_request_duration_seconds summary",
        ]
        with self._lock:
            for method, path, status in sorted(self._request_counts):
                labels = {"method": method, "path": path, "status": status}
                suffix = _labels_text(labels)
                key = (method, path, status)
                lines.append(f"asdi_requests_total{suffix} {self._request_counts[key]}")
                lines.append(f"asdi_request_duration_seconds_sum{suffix} {self._duration_sums[key]:.6f}")
                lines.append(
                    f"asdi_request_duration_seconds_count{suffix} {self._duration_counts[key]}"
                )
            for (name, label_items), value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                suffix = _labels_text(dict(label_items))
                lines.append(f"{name}{suffix} {value}")

        process_metrics = {
            "asdi_process_uptime_seconds": time.monotonic() - self._started,
            "asdi_process_cpu_seconds_total": usage.ru_utime + usage.ru_stime,
            "asdi_process_maxrss_bytes": float(rss_bytes),
            "asdi_process_pid": float(os.getpid()),
        }
        for name, value in process_metrics.items():
            lines.extend(
                [
                    f"# HELP {name} Local process probe.",
                    f"# TYPE {name} gauge",
                    f"{name} {value:.6f}" if name != "asdi_process_pid" else f"{name} {int(value)}",
                ]
            )
        return "\n".join(lines) + "\n"


def make_metrics_handler(registry: MetricRegistry) -> type[BaseHTTPRequestHandler]:
    class MetricsHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/healthz":
                body = b'{"status":"ok"}\n'
                content_type = "application/json; charset=utf-8"
            elif self.path == "/metrics":
                body = registry.render().encode("utf-8")
                content_type = "text/plain; version=0.0.4; charset=utf-8"
            else:
                body = b'{"error":"not_found"}\n'
                content_type = "application/json; charset=utf-8"
            self.send_response(200 if self.path in {"/healthz", "/metrics"} else 404)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return MetricsHandler


def scrape(port: int, *, path: str = "/metrics", timeout: float = 2.0) -> str:
    opener = build_opener(ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
        return response.read().decode("utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asdi-phase7-prometheus")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--render-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    registry = MetricRegistry()
    if arguments.render_only:
        sys.stdout.write(registry.render())
        return 0
    server = ThreadingHTTPServer(
        (arguments.host, arguments.port), make_metrics_handler(registry)
    )
    port = int(server.server_address[1])
    print(f"metrics endpoint on http://{arguments.host}:{port}/metrics", flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
