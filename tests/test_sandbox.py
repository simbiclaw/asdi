from __future__ import annotations

import shutil
import subprocess
import time
import tempfile
import unittest
from pathlib import Path

from asdi.egress import EgressProxy
from asdi.run_contract import RunContractValidationError, validate_run_contract
from asdi.runtime import RunStore
from asdi.sandbox import ContainerSandbox, SandboxSpec
from tests.test_run_launcher import synthetic_contract


class SandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.store = RunStore(self.root)
        self.socket_path = Path(tempfile.mktemp(prefix="asdi-test-", dir="/tmp"))

    def tearDown(self) -> None:
        self._temporary.cleanup()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def contract(self, *, allowlist: tuple[str, ...] = ()) -> dict:
        contract = synthetic_contract()
        if allowlist:
            contract["boundaries"]["network"] = {
                "mode": "allowlist",
                "allowlist": list(allowlist),
            }
        return contract

    def development_contract(self) -> dict:
        value = self.contract()
        value["boundaries"]["network"] = {
            "mode": "development_open",
            "allowlist": [],
            "override_reason": "owner_approved",
            "override_reference": "owner-2026-11-15-dev-flow-first",
            "scope": "development_only",
        }
        return value

    def test_development_open_profile_is_explicit_and_noncompliant(self) -> None:
        created = self.store.create_run(self.development_contract())
        sandbox = ContainerSandbox(
            SandboxSpec(
                image="asdi-sandbox-test:local",
                runtime_executable="/usr/bin/python3",
                docker_path="/usr/local/bin/docker",
                container_user="65534:65534",
                network_profile="development_open",
            ),
            self.store,
        )
        evidence = sandbox.prepare(created["run_id"], self.development_contract(), command=())
        argv = sandbox.docker_run_argv(
            created["run_id"],
            evidence,
            ("/usr/bin/python3", "/workspace/fixture.py"),
        )
        self.assertFalse(evidence["isolation_compliant"])
        self.assertEqual(evidence["network_mode"], "bridge")
        self.assertEqual(evidence["egress_mode"], "development_open_noncompliant")
        self.assertIn("bridge", argv)
        self.assertIn(
            "ASDI_SANDBOX_MODE=container_development_open_noncompliant",
            argv,
        )
        self.assertIsNone(sandbox.proxy)

    def test_development_open_contract_requires_explicit_owner_override(self) -> None:
        value = self.development_contract()
        del value["boundaries"]["network"]["override_reason"]
        with self.assertRaises(RunContractValidationError):
            validate_run_contract(value)

    def test_container_profile_is_hardened_and_uses_no_ip_network(self) -> None:
        created = self.store.create_run(self.contract())
        sandbox = ContainerSandbox(
            SandboxSpec(
                image="asdi-sandbox-test:local",
                runtime_executable="/usr/local/bin/curl",
                docker_path="/usr/local/bin/docker",
                container_user="65534:65534",
                egress_host_socket_dir="/tmp",
            ),
            self.store,
        )
        contract = self.contract()
        evidence = sandbox.prepare(created["run_id"], contract, command=())
        argv = sandbox.docker_run_argv(
            created["run_id"],
            evidence,
            ("/usr/local/bin/curl", "https://example.invalid"),
        )
        self.assertIn("none", argv)
        self.assertIn("ALL", argv)
        self.assertIn("no-new-privileges", argv)
        self.assertIn("65534:65534", argv)
        self.assertIn("/tmp:rw,noexec,nosuid,nodev,size=64m", argv)
        self.assertTrue(any("type=bind" in item for item in argv))
        self.assertFalse(any("ASDI_SECRET" in item for item in argv))
        self.assertIn("--cidfile", argv)
        image_index = argv.index("asdi-sandbox-test:local")
        self.assertNotIn("--", argv[image_index + 1:])
        self.assertIn("--entrypoint", argv)
        self.assertEqual(argv[argv.index("--entrypoint") + 1], "/usr/local/bin/curl")

    def test_allowlist_proxy_denies_non_allowlisted_and_private_targets(self) -> None:
        decisions: list[tuple[bool, str]] = []
        try:
            proxy = EgressProxy(
                self.socket_path,
                ("example.com", "192.0.2.10:443", "169.254.169.254"),
                reporter=lambda decision, count: decisions.append(
                    (decision.allowed, decision.reason)
                ),
            )
        except PermissionError:
            self.skipTest("this runner forbids binding AF_UNIX sockets")
        proxy.start()
        try:
            curl = shutil.which("curl")
            self.assertIsNotNone(curl)
            completed = subprocess.run(
                [
                    curl,
                    "--silent",
                    "--show-error",
                    "--fail",
                    "--max-time",
                    "2",
                    "--proxy",
                    f"socks5h://localhost{proxy.socket_path}",
                    "http://127.0.0.1:9/",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertTrue(decisions)
            self.assertFalse(decisions[-1][0])
            self.assertIn("private_destination_forbidden", decisions[-1][1])
            metadata_completed = subprocess.run(
                [
                    curl,
                    "--silent",
                    "--show-error",
                    "--fail",
                    "--max-time",
                    "2",
                    "--proxy",
                    f"socks5h://localhost{proxy.socket_path}",
                    "http://169.254.169.254/latest/meta-data/",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(metadata_completed.returncode, 0)
            self.assertFalse(decisions[-1][0])
            self.assertIn("private_destination_forbidden", decisions[-1][1])
        finally:
            proxy.stop()
        self.assertFalse(proxy.socket_path.exists())

    def test_socks5_proxy_reaches_an_allowlisted_global_endpoint(self) -> None:
        decisions: list[tuple[bool, str]] = []
        try:
            proxy = EgressProxy(
                self.socket_path,
                ("example.com:443",),
                reporter=lambda decision, count: decisions.append(
                    (decision.allowed, decision.reason)
                ),
            )
        except PermissionError:
            self.skipTest("this runner forbids binding AF_UNIX sockets")
        proxy.start()
        try:
            curl = shutil.which("curl")
            self.assertIsNotNone(curl)
            completed = subprocess.run(
                [
                    curl,
                    "--silent",
                    "--show-error",
                    "--fail",
                    "--max-time",
                    "12",
                    "--proxy",
                    f"socks5h://localhost{proxy.socket_path}",
                    "https://example.com/",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = completed.stdout.strip()
            self.assertTrue(output.startswith("<!doctype html>"))
            self.assertIn("<title>Example Domain</title>", output)
            deadline = time.monotonic() + 1.0
            while not decisions and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(decisions)
            self.assertTrue(decisions[-1][0])
            self.assertEqual(decisions[-1][1], "socks_connect_relayed")
            self.assertGreater(len(decisions), 0)
        finally:
            proxy.stop()

    def test_state_records_container_evidence(self) -> None:
        created = self.store.create_run(self.contract(allowlist=("example.com",)))
        sandbox = ContainerSandbox(
            SandboxSpec(
                image="asdi-sandbox-test:local",
                runtime_executable="/usr/bin/python3",
                docker_path="/usr/local/bin/docker",
                egress_host_socket_dir="/tmp",
            ),
            self.store,
        )
        try:
            evidence = sandbox.prepare(
                created["run_id"],
                self.contract(allowlist=("example.com",)),
                command=(),
            )
        except OSError as error:
            sandbox.proxy = None
            self.skipTest(f"this runner forbids binding AF_UNIX sockets: {error}")
        self.assertEqual(evidence["network_mode"], "none")
        self.assertEqual(evidence["egress_mode"], "allowlist")
        self.assertEqual(evidence["allowlist"], ["example.com"])
        self.assertTrue(evidence["branch"].startswith("asdi/run/"))
        sandbox.cleanup(created["run_id"])
        events = self.store.events(created["run_id"])
        self.assertIn("run_created", {event["type"] for event in events})


if __name__ == "__main__":
    unittest.main()
