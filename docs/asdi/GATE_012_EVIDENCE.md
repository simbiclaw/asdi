# ASDI-012 Container Sandbox Evidence

**Date:** 2026-11-13  
**Ticket:** ASDI-012  
**Result:** **FAIL — do not proceed to ASDI-013 as an autonomous runtime**

## Changed paths

| Path | Capability |
|---|---|
| [`src/asdi/sandbox.py`](../../src/asdi/sandbox.py) | Explicit per-run Docker profile, isolated workspace/branch, no-pull image verification, hardening, container state/cleanup, and isolated containerized done-check. |
| [`src/asdi/egress.py`](../../src/asdi/egress.py) | Host-side per-run Unix-socket HTTP CONNECT and SOCKS5 CONNECT authority, allowlist/DNS/private-address checks, and event reporting callback. |
| [`src/asdi/errors.py`](../../src/asdi/errors.py) | Shared launcher/sandbox state error type. |
| [`src/asdi/runtime.py`](../../src/asdi/runtime.py) | Container launch/cancel/recovery integration, container-path discovery, structured sandbox events, cleanup, and containerized done-check. |
| [`tests/test_sandbox.py`](../../tests/test_sandbox.py) | Static hardening profile, live SOCKS allow/deny tests, and Docker-backed sandbox state test. |
| [`tests/test_run_launcher.py`](../../tests/test_run_launcher.py) | Updated fail-closed assertion for explicit sandbox configuration. |
| [`scripts/probe_container_sandbox.py`](../../scripts/probe_container_sandbox.py) | Repeatable live no-network isolation/cancellation/workspace/environment/setup-failure evidence probe. |

## Verification commands

```sh
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src:. python3 scripts/probe_container_sandbox.py
docker image inspect safeclaw:cc-2.1.283 --format '{{.Id}}'
docker ps -a --filter 'name=asdi-' --format '{{.ID}} {{.Names}}'
```

Normal repository suite result: **33 tests, OK, 3 expected AF_UNIX skips**.  
AF_UNIX/Docker tests were then rerun with local elevated execution and passed.

## Host-side egress proxy evidence

The proxy itself was tested on the host without an IP network path:

```text
test_socks5_proxy_reaches_an_allowlisted_global_endpoint ... ok
test_allowlist_proxy_denies_non_allowlisted_and_private_targets ... ok
```

Observed decisions:

* `example.com:443` → `allowed=true`, `socks_connect_relayed`, non-zero relayed bytes.
* `127.0.0.1:9` → `allowed=false`, `private_destination_forbidden`.
* `169.254.169.254` → `allowed=false`, `private_destination_forbidden`, even though included in the test allowlist.

This proves only the host authority and SOCKS5 implementation. It does **not** prove container egress enforcement.

## Live container evidence

Docker server: Docker Desktop 4.81.0 / Engine 29.6.1, Linux/arm64.  
Local compatibility image: `safeclaw:cc-2.1.283`, SHA `sha256:6fd4ab59c08dd461c6abde00c0f8b5f40966abf4f6cc5fbba40475a8dd786046`. This is **not a production trust decision**. The `safeclaw-us-egress` proxy image was intentionally excluded.

Final probe evidence root:  
`/var/folders/yf/nn0v06c92fv8yc2z36cqqjw80000gn/T/asdi-gate-012-20261113-070618-b5t2mtbm`

Observed:

| Criterion | Evidence | Result |
|---|---|---|
| No-network container launch | Run `asdi_run_47581560-5afc-48f8-aa8d-ad2ee0376a44`; container `a8e7188a7269...5a8d1f6`; `network_mode=none`; runtime stdout `container-no-network-ok`; launcher done-check exit 0; final status `succeeded`. | Pass |
| Hardened profile | `--pull never`, `--cidfile`, `--network none`, `--cap-drop ALL`, `no-new-privileges`, read-only rootfs, bounded tmpfs/memory/CPU/PIDs, explicit bind workspace, and only explicit ASDI environment flags. | Pass |
| Cancellation | Run `asdi_run_4e563e5e-cefb-4212-a33e-b613fccfc2d3`; Docker reported running before cancellation; after cancellation inspect was empty and `container_cleaned` was persisted; launcher state was `cancelled`. | Pass |
| Concurrent workspace isolation | Runs `asdi_run_3156a1b2-4d44-469b-b7a5-c0d9b99c9253` and `asdi_run_55cb558d-5e8a-47b9-8bae-a0f88f46a90e` wrote `run-0` and `run-1` only into their own workspaces. Docker inspect showed exactly one bind mount per container and distinct source paths, both at `/workspace`, with `rprivate` propagation. | Pass |
| Host secret boundary | Run `asdi_run_3213acef-ec32-42a6-9bc1-d53fbeff676d`; `ASDI_SECRET=do-not-inherit` was present in the launcher process at launch; container `env` did not contain it. Only `ASDI_ALLOWED_BRANCH`, `ASDI_RUN_ID`, and `ASDI_SANDBOX_MODE` were explicit. | Pass |
| Workspace/branch identity | Each run had a fresh Git workspace and local `asdi/run/<run-id>` branch recorded in sandbox evidence. | Pass |
| Isolation setup failure | Run `asdi_run_704d05bc-b6b2-49ef-94ba-9a9d2c5651b7`; missing local image `asdi-missing-image:do-not-pull` produced `sandbox_setup_failed`; run became durable `failed`; no fallback occurred. | Pass |
| In-container egress allowlist | No in-container allowed/denied network request was demonstrated because the Unix socket cannot be mounted on this Docker Desktop host. | **Fail** |
| Production route denial | Host proxy denies private/link-local destinations, but that authority was not reachable from the container. | **Fail** |

## Blocking platform finding

Launch with the proxy socket failed before a runtime could start:

```text
invalid mount config for type "bind": bind source path does not exist:
/socket_mnt/private/tmp/asdi-asdi_run_...sock
```

A direct Docker mount test of the same socket returned:

```text
/bin/ls: cannot access '/mnt/hosttmp/asdi-asdi_run_...sock': Operation not supported
```

Docker Desktop's macOS file-sharing layer does not support bind-mounting a host Unix socket into a Linux container. Therefore this implementation cannot truthfully claim container-side egress enforcement on the current host. The launcher correctly failed the run rather than silently falling back to host networking.

## Additional limitation

The compatibility image's own configuration exposes its base-image environment keys in addition to explicit ASDI values. No launcher/host secret was inherited, but a production image must be audited and minimized so it cannot introduce credentials or proxy configuration. The current local image is only a compatibility fixture.

## Acceptance status

**ASDI-012 is not accepted.** Container launch, cancellation, workspace isolation, no-pull/no-network hardening, secret non-inheritance, and setup-failure behavior have useful evidence. The required container-to-host egress allowlist remains a hard failure on this Docker Desktop/macOS platform.

ASDI-013 and later autonomous execution must not be enabled until ASDI-012 has an approved container-side egress architecture and passing live evidence.
