# REV K Phase 7 builder-side production layer

**Status:** builder-side Pass 1 stand-in only. This is **not Phase 7 acceptance**
and is not a claim that a merged change is serving in `prod`. No real registry
daemon, external network, real user, secret, or agent path to `prod` is used.

## Authoritative seams

Build Guide V4 REV K §7.2, §9.4, §12, §13.2 and §13.3 govern this layer. The
build and deploy commands accept a durable post-merge deployment decision for
an exact 40-character `main` commit. Missing, stale, failed, non-main, or
auto-revert evidence fails closed before any Docker command runs.

| Concern | New seam | Runtime boundary |
|---|---|---|
| CI build | `ci/build.py`, `ci/docker.py`, `ci/approval.py` | Docker CLI injected through `DockerRunner`; build uses `--network=none` and pushes only to an ops-registry seam. |
| Image | `pilots/toy_notes/Dockerfile`, `pilots/toy_notes/.dockerignore` | Stdlib toy-notes HTTP server; non-root; no pip install; no external package fetch. |
| Deploy | `deploy/deployer.py`, `deploy/config.py` | `asdi-prod` network only; loopback smoke ports; resource limits and `oom_score_adj=-500` from the `config/limits.yaml` seam. No socket, privileged mode, secret, agent, or staging network. |
| Flags | `exposure/cli.py` | Default-off flag file. `set`, `keep`, and `kill` require a decision reference. Sweeps kill expired flags and write a judgment-class cleanup issue artifact; merge policy is unchanged. |
| Backup | `backup/local.py` | Local SQLite backup API, `PRAGMA integrity_check`, restore to a temporary file followed by atomic replace, and a one-restore drill record. |
| Observe | `observe/error_tracker.py`, `observe/prometheus.py` | Append-only local JSONL and stdlib Prometheus text endpoint bound to loopback. |

## Exact local commands

The real Docker commands below require an operator-supplied ops-registry seam
and an existing passing decision file. They are the intended interface; the
unit suite exercises the same code with `FakeDockerRunner`, so no registry is
contacted by tests.

```sh
python3 -m ci.build \
  --commit "$COMMIT" \
  --decision-file /tmp/asdi-main-decision.json \
  --registry ops-registry.local/toy-notes \
  --artifact /tmp/asdi-phase7/image.tar \
  --record /tmp/asdi-phase7/build-record.json

python3 -m deploy.deployer \
  --commit "$COMMIT" \
  --digest "$DIGEST" \
  --decision-file /tmp/asdi-main-decision.json \
  --build-record /tmp/asdi-phase7/build-record.json \
  --registry ops-registry.local/toy-notes \
  --state-dir /tmp/asdi-phase7/deploy-state \
  --limits config/limits.yaml

python3 -m exposure.cli --flag-file /tmp/asdi-phase7/flags.json \
  set ramp-1 --decision ADR-0003 --expires-at 2026-12-01T00:00:00Z
python3 -m exposure.cli --flag-file /tmp/asdi-phase7/flags.json \
  keep ramp-1 --decision ADR-0003 --expires-at 2027-01-01T00:00:00Z
python3 -m exposure.cli --flag-file /tmp/asdi-phase7/flags.json \
  kill ramp-1 --decision ADR-0003
python3 -m exposure.cli --flag-file /tmp/asdi-phase7/flags.json \
  sweep --issues-dir /tmp/asdi-phase7/issues --now 2026-11-20T00:00:00Z

python3 -m backup.local drill \
  --db /tmp/asdi-phase7/toy-notes.sqlite3 \
  --record /tmp/asdi-phase7/restore-drill.json

python3 -m observe.error_tracker --log /tmp/asdi-phase7/errors.jsonl \
  record --source prod-smoke --severity error --message 'synthetic failure'
python3 -m observe.prometheus --port 9090
```

`ci.build` writes `asdi.phase7-build-record/v1` containing the exact commit,
registry digest, saved-artifact SHA-256, and hashed main approval evidence.
`deploy.deployer` pulls by digest, starts the candidate on a run-owned
loopback smoke port, checks `/healthz`, `/readyz`, and `/notes`, swaps the
`active.json` pointer only after smoke passes, and removes the candidate while
leaving the previous digest active when smoke fails. A failed smoke exits 3;
a refused request exits 2.

## Boundaries not crossed

- No spec, reference, skill, verification harness, or existing tracked file was changed.
- No commit, push, GitHub comment, registry push, or production deployment was performed.
- The flag layer records state changes as `judgment`; it does not alter merge policy.
- The live-Docker test requires a cached base image and `--network=none`; it skips when Docker or that image is unavailable, rather than fetching from the network.
