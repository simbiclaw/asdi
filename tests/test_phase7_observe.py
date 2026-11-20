"""Local error tracker and Prometheus text endpoint tests."""

from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from observe.error_tracker import ErrorTracker, ErrorTrackerError
from observe.prometheus import MetricRegistry, make_metrics_handler, scrape


class Phase7ObserveTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="asdi-phase7-observe-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_error_tracker_is_append_only(self) -> None:
        tracker = ErrorTracker(self.root / "errors.jsonl")
        first = tracker.record(source="prod-smoke", severity="error", message="first")
        second = tracker.record(
            source="triage", severity="warning", message="second", context={"count": 2}
        )
        self.assertEqual(len(tracker.tail(10)), 2)
        self.assertEqual(tracker.tail(1)[0]["message"], "second")
        self.assertEqual(second["context"]["count"], 2)
        lines = (self.root / "errors.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], __import__("json").dumps(first, sort_keys=True))

    def test_error_tracker_rejects_bad_records_and_detects_corruption(self) -> None:
        tracker = ErrorTracker(self.root / "errors.jsonl")
        with self.assertRaises(ErrorTrackerError):
            tracker.record(source="", severity="error", message="bad")
        tracker.path.write_text("not-json\n", encoding="utf-8")
        with self.assertRaisesRegex(ErrorTrackerError, "corrupt"):
            list(tracker.iter_records())

    def test_metric_registry_renders_requests_latency_and_process_probes(self) -> None:
        registry = MetricRegistry()
        registry.observe_request(method="GET", path="/notes", status=200, duration_seconds=0.25)
        registry.set_gauge("asdi_feature_flag_enabled", 0.0, labels={"flag": "expiry-check"})
        text = registry.render()
        self.assertIn("asdi_requests_total{method=\"GET\",path=\"/notes\",status=\"200\"} 1", text)
        self.assertIn("asdi_request_duration_seconds_sum", text)
        self.assertIn("asdi_process_uptime_seconds", text)
        self.assertIn("asdi_process_cpu_seconds_total", text)
        self.assertIn("asdi_process_maxrss_bytes", text)
        self.assertIn("asdi_feature_flag_enabled{flag=\"expiry-check\"} 0.0", text)

    def test_prometheus_text_endpoint_serves_metrics(self) -> None:
        registry = MetricRegistry()
        registry.observe_request(method="GET", path="/healthz", status=200, duration_seconds=0.01)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_metrics_handler(registry))
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        thread.daemon = True
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = int(server.server_address[1])
        body = scrape(port)
        self.assertIn("asdi_requests_total", body)
        self.assertEqual(scrape(port, path="/healthz").strip(), '{"status":"ok"}')


if __name__ == "__main__":
    unittest.main()
