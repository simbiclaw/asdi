from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from launcher.egress_proxy import EgressAuthority, EgressHandler


class ModelHandler(BaseHTTPRequestHandler):
    last_authorization: str | None = None
    last_path: str | None = None

    def do_GET(self) -> None:
        ModelHandler.last_path = self.path
        ModelHandler.last_authorization = self.headers.get("Authorization")
        payload = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class RevKEgressTests(unittest.TestCase):
    def test_authority_allows_named_endpoints_and_denies_private_routes(self) -> None:
        authority = EgressAuthority(
            allowed_connect=frozenset(),
            model_host="host.docker.internal",
            model_port=4000,
            model_key="proxy-only",
        )
        self.assertEqual(authority.decide("host.docker.internal", 4000)[0:2], (True, "local_model_proxy"))
        self.assertFalse(authority.decide("192.168.1.10", 5432)[0])

    def test_http_proxy_injects_local_model_key_and_denies_unlisted_target(self) -> None:
        try:
            model = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        except PermissionError:
            self.skipTest("this runner forbids binding local TCP test servers")
        try:
            proxy = ThreadingHTTPServer(("127.0.0.1", 0), EgressHandler)
        except PermissionError:
            model.shutdown()
            model.server_close()
            self.skipTest("this runner forbids binding local TCP test servers")
        proxy.daemon_threads = True
        model_port = model.server_port
        proxy_port = proxy.server_port
        proxy.asdi_authority = EgressAuthority(
            allowed_connect=frozenset({("github.com", 443)}),
            model_host="127.0.0.1",
            model_port=model_port,
            model_key="proxy-only-key",
        )
        model_thread = threading.Thread(target=model.serve_forever, daemon=True)
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        model_thread.start()
        proxy_thread.start()
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{proxy_port}"})
            )
            with opener.open(
                f"http://127.0.0.1:{model_port}/v1/models", timeout=5
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())["ok"])
            self.assertEqual(
                ModelHandler.last_authorization,  # type: ignore[attr-defined]
                "Bearer proxy-only-key",
            )
            self.assertEqual(ModelHandler.last_path, "/v1/models")  # type: ignore[attr-defined]

            with self.assertRaisesRegex(urllib.error.HTTPError, "403"):
                opener.open("http://example.com/forbidden", timeout=5)
        finally:
            proxy.shutdown()
            proxy.server_close()
            model.shutdown()
            model.server_close()
            proxy_thread.join(timeout=2)
            model_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
