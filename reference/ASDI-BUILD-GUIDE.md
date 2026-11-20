# ASDI build guide (v4)

How and when to build ASDI. Lifecycle first, hardening second. Every open decision is deferred to the deploy gate (§15).

- Date: 2026-11-15. Replaces v3. What changed: the build order (§13). The specifications in §6 to §12 describe the full version of each part; §13.2 says which thin version to build first.
- Audience: the coding agent that builds ASDI on the Mac Studio M3 Ultra. Written for Claude Code and Codex alike; nothing here depends on one of them (§1.3).
- Revision set: REV K. The Design doc, the Stack doc, the Trust Handbook and this guide are synchronized at this revision; §19.2 lists the facts they must agree on.
- Companion: ASDI Trust Handbook — REV K. Read it with this guide.
- Design doc (REV K): https://claude.ai/artifact/5T3yXpRFvqP1ybgTobuW6E
- Stack doc (REV K): https://claude.ai/artifact/2UP3mzSnnjq9DDWpn5VgCN

## 1. Your job

Get the complete ASDI (Autonomous Software-delivery Infrastructure) lifecycle working on a toy product, in its thinnest form: a change goes from brief to production, and a production error comes back as a fix. Then stop at the deploy gate and hand the human a decision packet. Harden only after that.

### 1.1 Four documents, one system

The same split is stated in the Trust Handbook §1.

| Document | Owns | Does not carry |
|---|---|---|
| Design doc · REV K | Product thesis, principles, the seven hard rules, human authority, change classes, TRM, the production loop | Schemas, topology detail, phase steps |
| Stack doc · REV K | Which component fills each role | Trust rationale, build sequence |
| This guide · v4 · REV K | How and when: topology, launcher, contracts and schemas, phase order, exit tests, deferred decisions, file layout | The full reasoning behind each control |
| Trust Handbook · REV K | Why: the five trust layers, the ownership split, evidence semantics, rule classes, adequacy criteria, trust progression | Launcher APIs, schemas, a phase plan |

Shared across the set: the IDs in §3, the product repo layout in §6, the status vocabulary in §6.1 and the evidence manifest in §8. §19 maps every handbook section to a section here.

### 1.2 Lifecycle first

The priority is a working lifecycle, not a finished platform.

- **Pass 1** builds the thinnest version of every stage until two checkpoints pass: *first light* (a change reaches production and a bad one rolls back) and *full loop* (a production error comes back as a merged fix).
- **Pass 2** hardens. No Pass 2 item starts before the full-loop checkpoint.
- If a part is hard to build, build the stand-in from §13.2 and move on. Record what was skipped in `STATUS.md`.
- The seven hard rules and C-5 hold from the first run. They are cheap and the design rests on them.

Order of authority when sources disagree, as in handbook §1:

1. This guide, for topology, contracts, schemas, phase order, exit tests and deferred decisions.
2. The Design doc, for product intent and the hard rules.
3. The Stack doc, for which component is used.
4. The Trust Handbook, for why a control exists and whether it is adequate.

Record any conflict you find in `DECISIONS.md`.

### 1.3 Agent-neutral

Two kinds of agent appear in this guide. Neither is tied to one vendor.

| Role | What it does | Which CLI |
|---|---|---|
| Builder | Reads this guide and builds ASDI | Claude Code or Codex |
| Run agent | Does product work inside a run container that ASDI launches | Claude Code or Codex, chosen per task through the adapter in §7.6 |

Rules that keep it neutral:

- **One instruction file.** `AGENTS.md` is the source of truth in every repo, ASDI's own included. `CLAUDE.md` holds one line, `@AGENTS.md`, so Claude Code loads the same text. Codex reads `AGENTS.md` directly.
- **Enforcement never depends on an agent feature.** The launcher's verifier decides whether a run is green, for every CLI. A CLI's own stop hook is a convenience that saves a wasted turn.
- **Skills are plain `SKILL.md` folders,** which both CLIs load.
- **Anything CLI-specific lives in the adapter** (§7.6), nowhere else.

## 2. Settled constraints

Not open. Do not revisit.

| ID | Constraint |
|---|---|
| C-0 | Core is Archon plus one board: Multica or Paperclip. No other orchestrator. |
| C-1 | Every loop runs locally. GitHub is passive: code, PR UI, rulesets, CODEOWNERS. No Actions, no webhooks. |
| C-2 | One host: the Mac Studio M3 Ultra, 256 GB. |
| C-3 | No role VMs. Everything is a Docker container under Docker Compose. No Kubernetes. vllm-mlx alone runs on the host, because it needs Metal. |
| C-4 | Archon runs in its own Docker container. |
| C-5 | The agent's claim of success never counts. Only a result produced by ASDI-run verification does. |

## 3. Where each capability lives

Use this test, in order:

1. Must a failure be **blocked**, not just visible? Native.
2. Does it need authority, credentials or network reach the agent must not have? Native.
3. Must the result be **independent** of the agent that did the work? Native.
4. Must it outlive a run or cross zones? Native.
5. Is it knowledge about one product's behaviour? Product harness.
6. Otherwise it is a request the agent may override with a reason.

The handbook states the same split in its §3: centralize enforcement semantics, decentralize product knowledge.

### 3.1 ASDI-native infrastructure

Built in the ASDI repo. The agent cannot skip or edit it within a run.

| ID | Capability | Pass | Section |
|---|---|---|---|
| N-1 | Verify runner: ASDI executes the product's proofs in a clean container | 1 | §7 |
| N-2 | Evidence store | 1 | §8 |
| N-3 | Per-run service provisioning | 2 | §7.2 |
| N-4 | Coverage gate in the class check | 1 | §9.1 |
| N-5 | Verification-path protection | 1 | §9.3 |
| N-6 | Review verdict and findings schema | 1 | §10.2 |
| N-7 | Blast-radius pass | 2 | §10.3 |
| N-8 | Security pass | 2 | §10.3 |
| N-9 | PR packet assembly | 1 | §10.5 |
| N-10 | Compounding ladder and rule lifecycle | 2 | §11.1 |
| N-11 | Skill eval gate | 2 | §11.2 |
| N-12 | Pause and resume | 2 | §11.3 |
| N-13 | Drift sweep | 2 | §11.4 |
| N-14 | Production probe runner | 2 | §12.1 |
| N-15 | Canary check | 2 | §12.2 |
| N-16 | Self-healing stages | 1 | §12.3 |
| N-17 | Static-gate runner | 1 | §7.4 |
| N-18 | Evidence attestation | 2 | §8.2 |
| N-19 | Post-merge check on `main`, with auto-revert | 1 | §9.4 |
| N-20 | Seeded-defect suite | 2 | §11.5 |
| N-21 | Untrusted-text boundary | 1 (commenters), 2 (rest) | §10.4 |
| N-22 | Dependency guard | 1 (setting), 2 (proxy) | §7.5 |
| N-23 | Waivers and fail-closed policy | 1 (fail closed), 2 (waivers) | §9.5, §9.6 |

"Pass 2" items have a thin stand-in in Pass 1. See §13.2.

### 3.2 Product harness

Lives in each product repo. Written by agents as harness tasks, protected by N-5.

| ID | Artifact | Pass | Section |
|---|---|---|---|
| H-1 | Verify skill | 1 | §6.1 |
| H-2 | Feature map | 1 | §6.2 |
| H-3 | Negative control per feature | 1 | §6.2 |
| H-4 | Fixtures and drivers | 1 | §6.1 |
| H-5 | Production probes, read-only | 2 | §6.2, §12.1 |
| H-6 | Static-gate manifest | 1 (list of commands), 2 (ratchet) | §6.4 |
| H-7 | Rule registry | 2 | §6.5 |
| H-8 | Seeded defects | 2 | §6.6 |

### 3.3 Requests

Guidance in the product's `AGENTS.md`. The agent may override any of these and records the reason in `OVERRIDES.md`, which N-9 copies into the packet.

- Prove it on the real artifact; a build that compiles is no proof.
- Reproduce before fixing; chase the root cause.
- Split work into units that each verify on their own.
- Test behaviour as a user would, against literal expected values.
- Before trusting a measured number, name what limits it.
- Do not wait on the human for reversible work.
- On the second repeat of a correction, turn it into a check, not more text.
- Keep a decision log (`DECISIONS.tsv`) on long runs.
- Write the failing test first when a cheap local test path exists.

### 3.4 Excluded

| Item | Reason |
|---|---|
| A router skill that picks a playbook and stays active across turns | Second source of instructions beside the run contract |
| Any playbook where the agent lands its own stack | Rule 1 |
| "Land even if CI flakes" | Rules 1 and 2 |
| Human approval gates on plans, design or ship at T1+ | The Design doc §09 |
| A browser that uses the human's logged-in sessions | Rule 4 |
| Cloud agent runners or hosted automation | C-1 |
| Installing pstack or gstack as a dependency | Rule 7 forbids editing vendored code, and these parts must be adapted |
| A universal linter, style guide, folder tree or `SKILL.md` | Domain knowledge stays project-local (handbook §3) |

## 4. Deferred decisions

The human deferred every open decision to deployment time.

1. Never resolve a deferred decision, by choice or by code that only works one way.
2. Build a seam for each: an interface, adapter or config key.
3. Use the provisional default so the prototype runs. It carries no weight at the gate.
4. Log each use in `DECISIONS.md`.
5. New decisions get a new `DD-n` row. Stop and ask only if no reversible default exists.

| ID | Decision | Provisional default (prototype only) | Seam |
|---|---|---|---|
| D-9 | Board: Multica or Paperclip | Multica | `board/` adapter |
| D-8 | How loops learn of GitHub events | Local 60 s poller | `events/` source interface |
| D-4 | Which model triages logs with user data | Local model only | `triage.model` plus scrubber |
| DD-1 | Docker socket access | One daemon, socket proxy with an allowlist | Only `launcher/` and the deployer create containers |
| DD-2 | macOS container runtime | Whatever is installed; record it | `infra/runtime.md` |
| DD-3 | Tunnel provider | None; loopback only | `ingress` Compose profile |
| DD-4 | Reverse proxy | Either | `infra/proxy/` |
| DD-5 | Postgres layout | One instance, two databases | `.env` |
| DD-6 | Reviewer from a different model family than the run's agent | Local model via vllm-mlx; the other agent CLI is the alternative | `review.passes[].model` |
| DD-7 | Error tracker | Bugsink | Sentry-SDK DSN only |
| DD-8 | Image signing tool and key location | Throwaway key in a signer container | `ci/sign` |
| DD-9 | Networks Archon joins | `agent` and `ops`; never `prod` | Compose network list |
| DD-10 | Numeric defaults | The Design doc values | `config/defaults.yaml` |
| DD-11 | Judgment-class path list | The Design doc §02 list as globs | `config/classes.yaml` |
| DD-12 | Merge path: direct merge, or GitHub merge queue | Direct merge with required checks and an up-to-date branch | `merge/` adapter |
| DD-13 | "Verified snapshot" without VMs | `pg_dump` plus volume archive, restored into a scratch container | `backup/` |
| DD-14 | Memory and CPU limits per zone | Placeholders | `config/limits.yaml` |
| DD-15 | Offsite backup, external probe, notification channel | Local stand-ins | `ops/` adapters |
| DD-16 | Spend unit for local-model runs | Tokens and wall-clock | Guardrail config |
| DD-17 | Owner of the exposure gate | CLI the human runs | `exposure/` |
| DD-18 | Where `verify/` lives | Product repo, protected by N-5 | `verify.root` in `.asdi/product.yaml` |
| DD-19 | Evidence store backend, retention, viewing | Content-addressed directory on an `ops` volume, read-only HTTP, 30 days after PR close | `evidence/` interface |
| DD-20 | Per-run services | Launcher-provisioned from an approved image list | `services:` in the run contract |
| DD-21 | Coverage gate strictness | Uncovered product path means judgment; docs exempt | `config/coverage.yaml` |
| DD-22 | Blast-radius: Archon pass or in-run step | Archon pass | `review.passes[]` |
| DD-23 | Class for adding a lint or CI check | Judgment | `config/classes.yaml` |
| DD-24 | Skill eval sample size, threshold, budget | 5 paired runs, no regression | `config/evals.yaml` |
| DD-25 | Class for verify-only PRs | Judgment, except drift-sweep PRs with live evidence at T1+ | `config/classes.yaml` |
| DD-26 | UI driver | Playwright, headless, in the run image | Drive kind `ui` |
| DD-27 | Implementation language | Python; every part a separate process | Process boundaries in §16 |
| DD-28 | What counts as a safe production probe | HTTP GET on allowlisted paths, no auth, no writes | `config/probes.yaml` |
| DD-29 | Evidence scrubbing before store | Same scrubber as D-4 | `evidence.put()` |
| DD-30 | Only if a merge queue is adopted: how checks and review verdicts apply to its temporary commits | Not applicable while DD-12 is direct merge | `merge/` adapter |
| DD-31 | Which gates can be waived, by whom, for how long | Only static-gate legacy exceptions and flaky-feature quarantine; both expire | `config/waivers.yaml` |
| DD-32 | Dependency cooldown window and exemptions | 7 days, no exemptions, install scripts off | `config/dependencies.yaml` |
| DD-33 | Attestation tooling and key custody | in-toto statement in a DSSE envelope, signed with the DD-8 key | `evidence/attest` step |
| DD-34 | Status-posting identity: GitHub App or user token | Decide from S-4 | Credential config in `events/` and `merge/` |
| DD-35 | Formal verification scope | None in the prototype; the harness accepts drive kind `property` | Drive kind |
| DD-36 | Seeded-defect thresholds for TRM | Every seed caught by its named control before T1; re-run on a model release | `config/seeds.yaml` |
| DD-37 | Who may resume an agent by PR comment | The human's GitHub login only | `config/identities.yaml` |
| DD-38 | Which agent CLI builds ASDI, and which run product work | Either. Pass 1 uses whichever is installed; both go through the same adapter | `launcher/agents/` |

DD-27 is the least reversible default. Keep every part behind a process boundary so it can be rewritten alone.

Pass 1 exercises only these rows: D-9, D-8, D-4, DD-1, DD-2, DD-5 to DD-7, DD-9 to DD-19, DD-21, DD-26, DD-27, DD-37, DD-38. The others first matter when their Pass 2 item is built. Do not spend time on them before then.

## 5. Topology

Zones are Docker networks. A container's zone is the set of networks it joins.

| Network | Containers | Rule |
|---|---|---|
| `prod` | proxy, app blue, app green, flag service, deployer, prod database | Agent and staging containers never join. Only the proxy is published on the host. |
| `agent` | board, Archon, launcher, socket proxy, egress proxy | `internal`. Outbound only through the egress proxy. |
| `run-<id>` | one run container, its services, its verifier | Created and removed by the launcher. `internal`. Reaches the egress proxy only. |
| `staging` | staging stack, per-PR previews, preview verifier | No prod secrets. |
| `ops` | Prometheus, Loki, Grafana, error tracker, image registry, package registry proxy, signer, evidence store, probe runner, triage | Reads prod exporters read-only. |

```yaml
# compose.yaml (prototype), illustrative
networks:
  prod:    { internal: true }
  agent:   { internal: true }
  staging: { internal: true }
  ops:     { internal: true }
  egress:  {}

services:
  archon:        { networks: [agent, ops] }          # C-4, DD-9
  launcher:      { networks: [agent] }
  socket-proxy:                                       # DD-1
    networks: [agent]
    volumes: ["/var/run/docker.sock:/var/run/docker.sock:ro"]
    # allow: containers, networks named run-*, volumes named evidence-*
  egress-proxy:  { networks: [agent, egress] }       # allowlist; injects tokens;
                                                     # model API key added here
  package-proxy: { networks: [ops, egress] }         # Pass 2 (N-22)
  signer:        { networks: [ops] }                 # Pass 2 (N-18)
  evidence:      { networks: [ops] }                 # N-2
  probe-runner:  { networks: [ops, prod] }           # Pass 2 (N-14)
  deployer:      { networks: [prod, ops] }
  app-blue:
    networks: [prod]
    restart: unless-stopped
    oom_score_adj: -500
```

Containers reach vllm-mlx through the host gateway. Publish no other port on the host.

The model credential follows rule 4 like every other secret, for each provider: the agent CLI is pointed at the egress proxy as its API base URL, and the proxy adds that provider's key. No key exists inside a run container.

### 5.1 Prototype scope

In scope:

- A sandbox GitHub repo with a toy product: one small web service with a database, a CLI and one UI page.
- All loops L0 to L4 and the production loop, running against that repo.
- A local `prod` zone with fake users (a load script).
- Every hard rule and C-5 enforced, each with a negative test.

Out of scope until the gate:

- Real users, real domains, tunnel ingress.
- Real secrets. Use throwaway tokens scoped to the sandbox repo.
- Agent merges. The merge bot runs in dry-run and the human merges.
- Offsite backups and the monthly restore drill.
- Formal verification (DD-35).

## 6. Product harness specification

Every product repo carries this layout. The handbook lists who owns each artifact (its §4, H-1 to H-8) and leaves the layout to this section.

```
<product-repo>/
  AGENTS.md                 requests (§3.3); the source of truth
  CLAUDE.md                 one line: @AGENTS.md
  .asdi/
    product.yaml            profile: id, run image, services, task types,
                            architecture baseline
    static-gates.yaml       H-6
    rules.yaml              H-7
    seeds/                  H-8
  verify/
    SKILL.md                agent-readable procedure, nine sections
    verify.yaml             manifest
    bin/verify              one entry point, five subcommands
    features/<id>.md        H-2, one file per feature
    fixtures/
    drivers/                ui, http, cli, job, webhook helpers
  evals/                    skill evals (§11.2)
```

Maturity is never stored in the repo. The TRM ledger in ASDI's database is the only record of a task type's level.

### 6.1 Verify skill (H-1, H-4)

**Agent-readable part.** `SKILL.md` has nine sections (H-1 in handbook §4): surface, launch, doctor, drive, observe, isolate, evidence, cleanup, limits.

**Machine part.** One executable, five subcommands. No model is needed to run it.

| Command | Does | Exit codes |
|---|---|---|
| `verify launch` | Start the app against the services in `$ASDI_SERVICES` | 0 started, 2 blocked |
| `verify doctor` | Read-only health and ownership check | 0 healthy, 2 blocked |
| `verify drive <id>... \| --changed <base>..<head>` | Drive each feature as a user would and assert its proof | 0 all pass, 1 fail, 2 blocked |
| `verify control <id>...` | Run each feature's negative control; success means the control failed as expected | 0 caught, 1 missed |
| `verify cleanup` | Stop only what `launch` started | 0 |

**Status vocabulary, used everywhere in ASDI:**

| Status | Meaning |
|---|---|
| `pass` | The check ran and the observed value matched the expected one |
| `fail` | The check ran and the behaviour is wrong |
| `blocked` | The check could not run (environment, harness, flake) |
| `error` | The tool itself failed or timed out |
| `not_applicable` | The check does not apply to this diff |

Only `pass` satisfies a gate. `blocked` and `error` are never retried into a pass by the agent. A control is `caught` or `missed`.

Rules:

- Write all evidence to `$ASDI_EVIDENCE_DIR`. Never delete it in `cleanup`.
- Observe the resulting state and side effects (files, rows, messages), not only the action.
- Use run-owned ports, data directories and credentials only.
- Write `$ASDI_EVIDENCE_DIR/result.json` on every `drive`:

```json
{
  "schema": 2,
  "run_id": "r-01H...",
  "commit": "abc123",
  "features": [
    {
      "id": "export-csv",
      "status": "pass",
      "control": "caught",
      "evidence": ["export-csv/stdout.txt", "export-csv/out.csv"],
      "limits": ["Spreadsheet import not tested"]
    }
  ]
}
```

`verify.yaml`:

```yaml
schema: 2
product: toy-notes
services: [db]            # names only; images come from the ASDI approved list
drive_kinds: [cli, http, ui]
self_test: { feature: export-csv }
```

### 6.2 Feature map (H-2, H-3, H-5)

```markdown
---
id: export-csv
title: Export notes as CSV
paths: ["src/export/**", "cli/export.py"]
class_floor: agent-mergeable      # or judgment
drive:
  kind: cli                       # cli | http | ui | job | webhook | property
  command: "notes export --format csv --out $OUT"
proof:
  compare: { file: "$OUT", equals: "fixtures/export/expected.csv" }
negative_control:
  mutate: "fixtures/export/broken-input.json"
  expect: fail
limits: ["Spreadsheet import not tested"]
prod_probe:                        # optional, read-only (DD-28)
  http_get: "/healthz/export"
  expect_status: 200
last_verified: { commit: "abc123", date: "2026-11-15" }
---
## User-visible behaviour
## Reach
## Drive
## Proof
## Gotchas
```

Rules:

- Every product source path belongs to at least one feature's `paths`, or the coverage gate treats a change there as judgment.
- A feature without a `negative_control` fails the harness self-test.
- `limits` states what the proof does not cover. It is copied into the evidence manifest and the packet.

### 6.3 Harness self-test

1. `launch`, `doctor`.
2. `drive` the `self_test` feature. Expect `pass`.
3. `control` the same feature. Expect `caught`.
4. `cleanup`.
5. Confirm evidence still exists and `result.json` validates.

A harness that fails its self-test is unusable. Product PRs against it are judgment-class until it passes.

### 6.4 Static-gate manifest (H-6)

```yaml
# .asdi/static-gates.yaml
version: 1
checks:
  - id: typecheck
    command: ["uv", "run", "mypy", "src"]
    blocking: true
    timeout_seconds: 300
    applies_to: ["src/**/*.py"]
  - id: lint
    command: ["uv", "run", "ruff", "check"]
    blocking: true
    timeout_seconds: 300
  - id: unit-tests
    command: ["uv", "run", "pytest", "-q"]
    blocking: true
    timeout_seconds: 900
  - id: secret-scan
    command: ["scripts/secret-scan.sh"]
    blocking: true
    timeout_seconds: 300
policy:
  new_violations: reject
  legacy_findings: track_without_expanding   # ratchet
```

- ASDI reads this file from the **base branch**, never from the PR and never from an agent message.
- A PR that changes it is judgment-class and is itself judged by the old manifest.
- Exceptions live in `config/waivers.yaml` in the ASDI repo, not here (§9.6).

### 6.5 Rule registry (H-7)

```yaml
# .asdi/rules.yaml
rules:
  - id: R-017
    statement: "Empty lists still emit a header row"
    class: project-hard          # project-hard | convention
    scope: ["src/export/**"]
    enforcement:
      layer: 3                   # 1 codebase, 2 static check, 3 test, 4 text
      mechanism: "tests/export/test_empty.py"
      check: "pytest tests/export/test_empty.py"
    negative_test: ".asdi/seeds/S-export-empty.patch"
    owner: human
    introduced_by: "PR #41 review"
    recurrences: 0
    status: active
```

Four rule classes, shared with handbook §7:

| Class | Where it lives | Enforced by |
|---|---|---|
| Platform hard | The Design doc §02, `config/` in the ASDI repo | Runtime, identities, gate |
| Project hard | `.asdi/rules.yaml` | A check at layer 1 to 3, with a negative test |
| Convention | `AGENTS.md`, `.asdi/rules.yaml` at layer 4 | Review; deviation needs a reason |
| Task-specific | The run contract | Contract pass |

Every `project-hard` rule needs a named mechanism and a negative test that passes. A rule without them is a convention.

### 6.6 Seeded defects (H-8)

```yaml
# .asdi/seeds/S-export-empty.yaml
id: S-export-empty
patch: S-export-empty.patch
layer: 5                     # which trust layer should catch it
expect_caught_by: [verify]   # static | verify | review:<pass> | policy
unit_tests_stay_green: true
```

Each product keeps at least one seed per layer 2, 4 and 5, plus one policy seed (a judgment-class path hidden behind a flag). §11.5 runs them.

## 7. Launcher, gates and guards

### 7.1 Run contract

the Design doc §07 fields, plus:

```yaml
contract_version: 3
task_type: feature.cli
product: toy-notes
services: [db]                 # N-3
verify:
  features: [export-csv]       # explicit, or
  changed: true                # derive from the diff via feature paths
evidence: { required: true }
resume: { from: null }         # checkpoint id, set by N-12
guardrails: { turns: 200, spend_usd: 8, minutes: 90, tokens: null }
```

### 7.2 Run lifecycle

```
launcher run <contract.yaml>
  1  validate contract; refuse if over budget or WIP
  2  create network run-<id> (internal) and volume evidence-<id>
  3  start services from config/services.yaml (approved images only)
  4  start run container: worktree mounted, evidence volume mounted,
     no socket, no tokens, egress via proxy, packages via package-proxy
  5  agent works; guardrails enforced from outside the container
  6  agent stops -> done_check (the CLI's own stop hook, where it has one)
  7  launcher re-check in a VERIFIER container: static gates (§7.4),
     then verify (§7.3)
  8  evidence put -> attest (§8); record manifest id on the board task
  9  remove run container, services, network, volume
 10  report status to the board
```

Launcher CLI: `run`, `pause <id>`, `resume <checkpoint>`, `kill <id>`, `status <id>`. Nothing else touches the socket proxy.

### 7.3 Verifier container (N-1)

This is how C-5 is enforced.

- Same run image, clean checkout of the head commit, fresh services, no agent session, no model access.
- `.asdi/static-gates.yaml` and `verify/` are taken from the **base branch**. New feature files added by the PR are overlaid. Edits to existing files there are ignored.
- Runs static gates, then `launch`, `doctor`, `drive --changed`, `control` for the same features, `cleanup`.
- Green only if every blocking static gate and every touched feature is `pass` and every control is `caught`.
- `blocked` or `error` ends the run red and opens a harness task. It is not a strike against the agent.

The same verifier image is reused at the PR gate, on `main` after a merge, and in the seed suite.

### 7.4 Static-gate runner (N-17)

- Runs each declared check in the verifier container with its timeout.
- Maps tool outcome to the status vocabulary. A tool crash or timeout is `error`, never `pass`.
- Applies the ratchet: a legacy finding count may fall, never rise.
- Emits one check entry per gate into the evidence manifest.

### 7.5 Dependency guard (N-22)

Pass 1, no new infrastructure:

- Set the package manager's minimum release age (DD-32) in the product repo.
- Disable install scripts in run, verifier and CI containers.
- CI and the verifier install from the lockfile only.
- A new package is judgment-class. A bump of an existing one is agent-mergeable.

Pass 2 adds a package proxy that enforces the cooldown for every container, and read-only registry access at the egress proxy.

### 7.6 Agent CLI adapter

The launcher starts a run agent through an adapter, one entry per CLI. Everything CLI-specific is here.

| Concern | What the launcher needs | Claude Code | Codex |
|---|---|---|---|
| Headless start | One command that takes the contract and exits | `claude -p` | `codex exec` |
| Instruction file | Loaded at start | `CLAUDE.md`, which imports `AGENTS.md` | `AGENTS.md` |
| Skills | `SKILL.md` folders in the repo | Supported | Supported |
| In-agent `done_check` | Optional; saves a turn | Stop hook | Stop hook |
| Own sandbox and approvals | Never wait for a human; the run container is the sandbox | Permission setting | `--sandbox` setting |
| Model endpoint | Base URL set to the egress proxy; no key in the container | Base-URL setting | Provider base-URL setting |
| Event stream | Structured output, for counting turns and tokens | Supported | `--json` |
| Stop | Signal the process; the launcher kills the container on a limit | Same | Same |

Rules:

- Flags and hook behaviour change between releases. Confirm each cell against the CLI's current documentation and pin the CLI version in the run image. Do not write flags from memory.
- Check that each CLI runs inside an unprivileged container with its own sandbox relaxed. A CLI that needs host-level sandboxing features may fail there.
- If a CLI cannot report turns, enforce tokens and minutes only for that CLI and record it in `STATUS.md`.
- Adding a third CLI means adding one adapter entry. Nothing else changes.

## 8. Evidence (N-2, N-18)

### 8.1 Store

- Location: `ops` network. Content-addressed by SHA-256. Write-once. In Pass 1 this is a directory on a volume.
- Interface: `evidence put <dir> -> manifest_id`, `evidence get <sha>`, `evidence link <manifest_id> -> url`, `evidence verify <manifest_id>`.
- `put` pipeline: validate `result.json`, scrub (DD-29), hash, store, build the statement. Pass 2 sends it to the signer.
- Retention from `config/defaults.yaml`. Evidence for judgment-class merges and for every revert is kept until the weekly system loop releases it.
- A disk quota on the evidence volume, watched by the disk janitor.
- The packet links to manifests. Small text evidence is inlined in the PR body, because GitHub cannot reach the local store.

### 8.2 Manifest and attestation

The manifest is an in-toto statement. Pass 1 stores it unsigned. Pass 2 has the signer wrap it in a DSSE envelope with a key the agent and the verifier never hold; the format does not change.

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [
    { "name": "toy-notes",
      "digest": { "gitCommit": "abc123…" } }
  ],
  "predicateType": "https://asdi.local/verification/v1",
  "predicate": {
    "manifest_id": "m-01H…",
    "source": "run | pr-head | main | drift | prod-probe | canary | seed",
    "run_id": "r-01H…",
    "pr": 42,
    "task_type": "feature.cli",
    "producer": { "kind": "verifier", "image_digest": "sha256:…" },
    "environment": {
      "run_image_digest": "sha256:…",
      "tool_versions": { "python": "3.12", "playwright": "1.x" }
    },
    "inputs": {
      "harness_commit": "base-branch sha",
      "static_gates": "sha256:…",
      "product_profile": "sha256:…"
    },
    "checks": [
      { "id": "static:typecheck", "status": "pass" },
      { "id": "feature:export-csv", "status": "pass", "control": "caught",
        "limits": ["Spreadsheet import not tested"] }
    ],
    "files": [
      { "sha256": "9f2c…", "path": "export-csv/out.csv", "kind": "value",
        "feature": "export-csv", "bytes": 512 }
    ],
    "started": "2026-11-15T14:00:00Z",
    "finished": "2026-11-15T14:02:10Z"
  }
}
```

`kind` is one of `log`, `value`, `diff`, `http`, `screenshot`, `video`, `trace`, `heap`.

### 8.3 Validity rules

Evidence satisfies a gate only if all of these hold. The handbook lists the same rules in its §8.

| Rule | Check |
|---|---|
| Revision-bound | `gitCommit` equals the commit the gate is judging |
| Producer-bound | Pass 1: only the launcher can write to the store. Pass 2: the signature verifies against the verifier identity |
| Environment-bound | Image digest and tool versions are present |
| Input-bound | `harness_commit` is on the base branch; hashes of the gate manifest and profile match |
| Integrity | Every file's SHA-256 matches the store |
| Fresh | Any new PR head commit invalidates all evidence and review verdicts for that PR. No selective carry-forward in this version |
| Honest negatives | `fail`, `blocked` and `error` stay distinct and are stored, not discarded |
| Limits stated | `limits` is present for every feature check, even if empty |

Invalidated evidence stays in the store for audit. It cannot satisfy a gate.

## 9. Gate (N-4, N-5, N-19, N-23)

Rulesets require two statuses: `ci` and `asdi/policy`. `ci` carries the static-gate result. `asdi/policy` aggregates the sub-results `asdi/verify`, `asdi/review` and, in Pass 2, `asdi/skill-eval`, which are posted for information. Rulesets never change when a sub-check is added.

### 9.1 Class check

```
input: PR diff, config/classes.yaml, config/coverage.yaml, config/waivers.yaml,
       feature map and gate manifest from the base branch
       (+ new feature files in the PR), attested manifest, pass outputs,
       TRM ledger

 1  class = agent-mergeable
 2  any path matches a judgment glob             -> class = judgment
 3  map changed product paths to features
 4  any changed product path in no feature       -> class = judgment   (N-4)
 5  any touched feature has class_floor judgment -> class = judgment
 6  blast-radius adds touched features; repeat 4 and 5
 7  PR edits existing verify/**, evals/** or .asdi/** AND product paths
                                                 -> FAIL "split the PR" (N-5)
 8  PR edits those paths only                    -> per DD-25
 9  PR adds new verify/features/*.md             -> flag for the reviewer
10  PR touches AGENTS.md, skills or evals        -> require asdi/skill-eval
11  dependency change outside §7.5 limits        -> class = judgment   (N-22)
12  evidence fails any §8.3 rule                 -> FAIL
13  any blocking static gate or touched feature not pass,
    or any control not caught                    -> FAIL
14  any required pass not pass                   -> FAIL
15  independent_family is unavailable            -> class = judgment
16  state-changing diff behind a flag            -> class = judgment
17  TRM level for task_type < T1                 -> human merges
18  unsure at any step                           -> class = judgment
output: decision (eligible | blocked | human_required), class,
        rule numbers fired, waivers applied, policy version
```

### 9.2 Coverage as a TRM precondition

A task type cannot leave T0 for a product until:

- the harness self-test passes,
- coverage of product source paths meets the threshold in `config/coverage.yaml`,
- no touched feature was `blocked` in the last three runs,
- the product's seeds are all caught by their named controls (DD-36).

### 9.3 Verification-path protection

- `verify/**`, `evals/**` and `.asdi/**` are flagged paths under rule 7.
- Only the drift sweep (N-13) and harness tasks may change existing files there.
- A product PR may add a new feature file for a new feature. The reviewer's first duty on that PR is to check the check.

### 9.4 Merge and post-merge check (N-19)

One rule: test what is on `main`, and deploy only what passed there.

1. **Before merge.** The gate runs on the PR head. The ruleset requires `ci` and `asdi/policy` and an up-to-date branch. A new head commit invalidates earlier evidence and verdicts.
2. **Merge.** The merge bot merges directly (the human does, until agent merges are on).
3. **After merge.** The poller sees the new commit on `main`. ASDI runs static gates and the verifier on that exact commit and stores the result with source `main`.
4. **Fail.** ASDI opens an auto-revert PR and stops the release.
5. **Pass.** CI builds the image from that commit. The deployer deploys only a commit with a passing `main` result.

Nothing here depends on how GitHub rewrites commit IDs, because the check runs on the commit that actually landed.

A merge queue is not used. It would add a second place to post statuses and its own timeouts, for a benefit that only appears when many PRs merge in parallel. With a WIP limit of 3 that is not the case. If it ever is, DD-12 and DD-30 cover the change.

### 9.5 Fail-closed table (N-23)

| Condition | Result |
|---|---|
| Static-gate tool crash or timeout | `error`; gate blocked |
| Verifier `blocked` | Run red; harness task; no strike |
| Reviewer unavailable | Blocked, or routed to the human. Never implementer self-review |
| No second model family available | `independent_family: unavailable`; class becomes judgment |
| Evidence missing, hash mismatch or bad signature | Invalidated; gate fails |
| Evidence store or signer unreachable | Blocked |
| Poller stalled | No statuses are posted, so nothing merges; alert after 5 minutes |
| Waiver expired | Gate returns to blocking |
| Model queue saturated | Agent runs paused; production served |

### 9.6 Waivers (Pass 2)

`config/waivers.yaml` in the ASDI repo. Changing it is judgment-class, so only the human can grant one.

```yaml
- id: W-003
  gate: "static:lint"
  scope: ["src/legacy/**"]
  reason: "Legacy module, ratchet in place"
  expires: 2026-12-15
```

Never waivable: rules 1, 3, 4 and 6, C-5, evidence validity (§8.3), and the dependency cooldown for new packages. What else may be waived is DD-31.

## 10. Review, untrusted text and the packet

### 10.1 PR gate order

1. Static gates in a throwaway verifier container. Posts `ci`.
2. Verifier against the staging preview. Posts `asdi/verify`.
3. Review, in fresh context. Posts `asdi/review`. Pass 1 runs one review pass; Pass 2 runs four in parallel.
4. Class check. Posts `asdi/policy`.
5. Packet assembly. Updates the PR body.

CI and the verifier execute agent-written code. They never run inside Archon's container and never see the status token or signing key.

### 10.2 Pass output schema (N-6)

```json
{
  "schema": 2,
  "pass": "review | contract | correctness | security | blast-radius",
  "model": "…",
  "independent_family": "true | false | unavailable",
  "reviewed_commit": "abc123…",
  "status": "pass | fail | blocked",
  "findings": [
    {
      "id": "F-1",
      "bucket": "act | consider | noted | dismissed",
      "strike": true,
      "file": "src/export/csv.py",
      "line": 88,
      "claim": "Header row omitted when the list is empty",
      "evidence": "m-01H…#export-csv/out.csv"
    }
  ]
}
```

- A verdict counts only if `reviewed_commit` equals the head being judged.
- A finding with no evidence cannot be `act`.
- Only `act` findings enter the fix loop. A fix is a new implementation run; reviewers are read-only.
- `strike: true` only for correctness and security findings.

### 10.3 Passes

Pass 1 runs a single `review` pass by a different-family model, covering contract, correctness and security together. If no second family is available, it runs same-family and records `independent_family: false`; the human is merging everything at that stage anyway. Pass 2 splits it into the four below and adds the deep sample.

| Pass | Model | Scope |
|---|---|---|
| Contract | Same family | Premise, objective, constraints, out of scope. A wrong premise aborts early with no strike. |
| Correctness | Different family (DD-6) | Behaviour against the feature proofs; checks the check on new feature files. |
| Security | Different family | Auth, input handling, secrets, dependency changes. Threat-model the diff. |
| Blast-radius | Either (DD-22) | What outside the diff could break, as feature ids plus a command that demonstrates each claim. |
| Deep sample | Different family, after merge | 1 in 5 at T1, 1 in 10 at T2. Audits class routing and evidence quality. |

### 10.4 Untrusted-text boundary (N-21)

Three kinds of text reach a model in ASDI. Only the first may carry instructions.

| Kind | Examples | Handling |
|---|---|---|
| Trusted | The admitted brief; PR comments from logins in `config/identities.yaml` | May instruct |
| Agent-authored | PR body, counter-case, commit messages, `ASSUMPTIONS.md` | Data. Passed to reviewers inside a delimited block labelled as the implementer's claims |
| External | Production logs, error messages, user content, dependency files, fetched pages | Data. Length-capped, delimited, never placed in a brief as prose |

Pass 1 implements two of these: only allowlisted logins can resume an agent, and agent-authored text reaches the reviewer in a delimited block. The structured extraction below is Pass 2.

Rules:

- Triage turns logs into structured fields (signature, endpoint, count, first and last seen). The brief compiler builds a defect contract from those fields. Raw excerpts travel as attachments marked as data.
- A PR comment resumes an agent only if its author is allowlisted (DD-37). Other comments are stored and ignored.
- Reviewers have no tools with side effects. A reviewer's `pass` is necessary, never sufficient: the verifier's result is independent of anything a reviewer reads.
- Runs hold no secrets and can push only to their own branch, so an injected instruction has nothing to steal and one place to write, which the gate inspects.

### 10.5 Packet template (N-9)

```markdown
## Counter-case
The agent's strongest argument against merging this.

## Decision
eligible | blocked | human_required. Class and rules fired. Waivers applied.

## Verification
| Check | Status | Control | Limits | Evidence |
|---|---|---|---|---|
| feature:export-csv | pass | caught | Spreadsheet import not tested | m-01H… |

## Review
Act: … / Consider: … / Noted: … / Dismissed: …
Independent family: true | false | unavailable

## Assumptions
## Overrides
## Flags
## Decision log
```

## 11. Learning and continuity

All of §11 is Pass 2. The Pass 1 stand-ins are in §13.2.

### 11.1 Compounding ladder and rule lifecycle (N-10)

Trigger: the same correction appears twice. That starts a review; it does not harden a rule automatically.

The compounding bot proposes the fix at the highest layer that works, and says why each higher layer does not:

| Layer | Fix | PR class |
|---|---|---|
| 1 | Codebase change that makes the mistake impossible or unnatural | By diff |
| 2 | Type, lint or CI check in `.asdi/static-gates.yaml` | DD-23 |
| 3 | Test | Agent-mergeable |
| 4 | `AGENTS.md` or skill text | Needs `asdi/skill-eval` |

Every fix adds or updates a row in `.asdi/rules.yaml` (§6.5) and, for layers 1 to 3, a seed proving the control catches the original mistake.

- A layer-4 rule with two or more recurrences is escalated one layer.
- A rule with no recurrence for a full model release cycle is a retirement candidate in the weekly system loop. History is kept.

### 11.2 Skill eval gate (N-11)

Required on any PR touching `AGENTS.md`, skills or `evals/`. Run the cases under each agent CLI in use.

```
evals/<skill>/
  cases/<case>.yaml     task prompt, repo fixture, scoring checks
  rubric.md             only for what checks cannot score
```

- Run each case N times with the change and N times without (DD-24), in ordinary run containers.
- Blinded: nothing tells the agent it is an eval.
- Score with deterministic checks first, the rubric second.
- Pass only if the change regresses no case and improves the targeted one.
- Eval runs draw from a separate budget and never count toward TRM.

### 11.3 Pause and resume (N-12)

```
launcher pause <run-id>
  1  signal the agent through board.cancel_task with a grace period
  2  agent writes HANDOFF.md: state, next step, open questions, what failed
  3  agent commits to its branch with a "wip:" prefix and pushes
  4  launcher records a checkpoint:
       {id, branch, commit, handoff_path, turns_used, spend_used, minutes_used}
  5  grace expired with no commit -> launcher archives the worktree
     to the evidence store and records that instead
  6  tear down as in §7.2 steps 8 to 10
```

- `launcher resume <checkpoint>` starts a fresh session with `resume.from` set.
- Guardrail use carries over. A resume never resets the budget.
- Preemption is not a strike. A reset is.
- `wip:` commits are squashed before the PR is opened.

### 11.4 Drift sweep (N-13)

Weekly, and whenever a merge touches a feature's `paths`.

1. Source pass: for each feature, diff `paths` since `last_verified.commit`.
2. Live pass on staging: harness self-test, then `drive` and `control` for every changed feature.
3. Harness out of date, product correct: one PR changing only `verify/**`, with evidence.
4. Product wrong: a board issue under the charter. Never edit a feature file to match broken behaviour.
5. Update `last_verified`. Report drift age per feature.

A feature whose drift age passes the threshold is marked stale. Changes touching it are judgment-class until it is re-verified.

### 11.5 Seeded-defect suite (N-20)

Answers "do the controls catch real faults?" for gates and reviewers, where the negative control answers it for one proof.

1. For each seed in `.asdi/seeds/`, apply the patch on a scratch branch.
2. Run the PR gate in dry mode: no statuses posted, no PR opened.
3. Record which control caught it, with evidence source `seed`.
4. Compare with `expect_caught_by`. A seed nobody catches is a `missed` seed.

Runs: before a task type leaves T0, weekly, and on every model or runtime release before T2 work resumes. Catch rate per control goes to the metrics store. A missed seed blocks promotion (DD-36).

## 12. Production loop

### 12.1 Probe runner (N-14, Pass 2)

- A container on `ops` and `prod`. No model, no agent session, no write credentials.
- Executes only `prod_probe` entries that pass `config/probes.yaml` (DD-28).
- Results go to the evidence store with source `prod-probe`.

### 12.2 Canary check (N-15, Pass 2) and the deployer rule

At each deploy stage the rollback controller reads error rate and latency from Prometheus, and probe results for every feature touched since the last release. Any failed probe or breach triggers a swap back.

The deployer accepts an image only if both hold:

1. The image was built by CI from a commit on `main`.
2. That commit has a passing `main` result (§9.4).

Pass 1 has the deployer pull by digest from the `ops` registry, which only CI can push to. Pass 2 adds image signing and checks the signature too.

### 12.3 Self-healing stages (N-16)

| Stage | Owner | Output |
|---|---|---|
| Detect | Error tracker, Prometheus, probe runner | Raw signal |
| Triage | Archon pipeline, local model, scrubbed and structured input (§10.4) | Cluster, score, dedupe or reopen |
| Charter check | Archon | Below threshold: agent fixes. Above: human decides. |
| Reproduce | Run container | Failing test or failing `drive`, as evidence |
| Fix | Run container | Red-then-green repro, PR through the normal gate |
| Verify in production | Probe runner | Error gone for the window, probes pass |
| Close or reopen | Archon sweep | Reopen is a strike and a TRM demotion signal |

A fix with no reproduction cannot be agent-mergeable. An escaped defect is linked to the evidence manifest of the run that shipped it, and classified: weak proof, missing feature path, stale harness or reviewer miss.

## 13. Build order

### 13.1 Rules

- Phase numbers are the same as in v3, so references elsewhere still resolve. The order is not numeric.
- Pass 1 order: **0 → 1 → 3 → 4 → 7 → first light → 2 → 5 → 9 → full loop → 6 → 8 → 10 → deploy gate.**
- Build the thin version in §13.2. Do not build the full version of anything in Pass 1.
- A phase is done when its exit test passes. End each phase with a commit and a `STATUS.md` update.
- For Multica, Paperclip and Archon, read the upstream documentation for the version you install and pin it. Do not write their config from memory.

### 13.2 Pass 1 stand-ins

| Part | Build this in Pass 1 | Full version |
|---|---|---|
| Brief | A hand-written run contract, validated against the schema | Brief compiler |
| Run isolation | One container per run on its own network; no secrets inside; egress allowlist | Same |
| Services for a run | Processes inside the run image (the toy product uses SQLite) | Launcher-provisioned containers, §7.2 |
| Static gates | The launcher runs the commands listed in `.asdi/static-gates.yaml` | Ratchet, §7.4 |
| Verification | Verify skill, feature map, negative control; verifier re-run from the base branch | Same, plus seeds §11.5 |
| Evidence | Directory on a volume, unsigned statement with hashes | Signed, §8.2 |
| Review | One `review` pass | Four passes and deep sample, §10.3 |
| Class check | Steps 1 to 5, 7 to 9, 12 to 14, 17 and 18 of §9.1 | All steps |
| Merge | You merge; merge bot logs what it would do | Merge bot live |
| After merge | Static gates and verifier on `main`; auto-revert PR on failure | Same |
| Deploy | Build, push to `ops` registry, blue/green swap, smoke test, swap back on failure | Signed images, canary stages, probe runner |
| Observe | Error tracker and Prometheus | Same |
| Triage | Daily pipeline: cluster errors with the local model, open a board issue | Structured extraction, §10.4 |
| Preemption | `launcher kill`, then re-queue the task | Pause and resume, §11.3 |
| Reset | Kill, then re-run in a fresh session with a revised contract | Same, with handoff note |
| Learning | Append corrections to `CORRECTIONS.md`; you approve any rule change | Compounding ladder, rule registry, skill evals |
| Flags | A flag file in the product, default off, with an expiry list a sweep checks | GrowthBook, experiment readouts |
| TRM | Ledger table with counters; every task type stays at T0 | T1 and T2 transitions with preconditions |
| Dependencies | Package-manager cooldown setting; install scripts off | Package proxy |
| Backups | Local dump and one restore test | Offsite, monthly drill |
| Notifications | Append to a log file | Push channel, capped queue |

### 13.3 Pass 1 phases

#### Phase 0: scaffold

Deliver: repo layout (§16); `compose.yaml` with the networks; `config/` files; JSON Schemas for the run contract, feature front matter, `result.json`, evidence statement and pass output; three GitHub identities; a ruleset requiring `ci`, `asdi/policy` and an up-to-date branch; CODEOWNERS for judgment paths. Spike S-4.

Exit test: schemas validate their examples; an `agent` container cannot connect to `prod`; the agent token is refused on merge.

#### Phase 1: launcher and verifier

Deliver: contract validation; `launcher run`, `kill`, `status`; one container and network per run; guardrails enforced from outside; egress proxy with an allowlist that also adds the model key; the agent adapter (§7.6) with at least one working CLI and its stop hook; the verifier container (static gates, then verify, both read from the base branch); evidence directory and statement.

Exit test:

- A run whose agent claims success but whose verifier returns `fail` ends red.
- A run that edits an existing feature file to pass still ends red.
- Each guardrail kills the run.
- No token or model key exists inside a run or verifier container.
- Evidence survives teardown and its hashes check out.

#### Phase 3: toy product and harness

Deliver: the toy product; `.asdi/product.yaml`; `.asdi/static-gates.yaml` with three or four commands; `verify/` with at least three features across `cli`, `http` and `ui`, each with a negative control. Have an agent write the harness through `launcher run`.

Exit test: harness self-test passes; every source path belongs to a feature; breaking each feature by hand turns its status to `fail`.

#### Phase 4: PR gate

Deliver: poller behind `events/`; on a new PR head: `ci`, verifier, one review pass, class check, `asdi/policy`, packet; allowlisted commenters; merge bot in dry-run; the post-merge check on `main` with auto-revert (§9.4); poller health alert.

Exit test:

- A judgment-path PR and a change to an uncovered path both require the human.
- A PR mixing product code with edits to protected paths fails with "split the PR".
- One more commit after a green gate makes it red until the checks re-run.
- A commit on `main` that fails the post-merge check gets an auto-revert PR.
- With GitHub unreachable, no state is lost and the poller catches up.

#### Phase 7: production

Deliver: CI build from a `main` commit that passed the post-merge check; push to the `ops` registry; deployer with blue/green swap, smoke test and swap back; error tracker and Prometheus; container limits with OOM priority for prod; local backup and one restore.

Exit test: a merged change is serving in `prod`; a release that fails its smoke test is swapped back without the human; a commit with no passing `main` result is not deployed; an agent container still has no path to `prod`.

#### Checkpoint: first light

By hand, with `launcher run`: one contract → run → verifier → PR → review → gate → you merge → post-merge check → build → deploy → serving. Then one deliberately bad change that is rolled back. Do not continue until both work.

#### Phase 2: board

Deliver: the board on Compose behind `board/`; an admitted task starts a run through the launcher and gets its status back; WIP limit. Spikes S-1 and S-2. A stub adapter for the other board.

Exit test: a task admitted on the board reaches production with no hand-launched step; the WIP limit refuses the next task.

#### Phase 5: fix loop and reset

Deliver: fix loop (max 2 attempts) fed by `act` findings; strike counting; on two strikes, kill and re-run once in a fresh session with a revised contract; a failed reset drops the task.

Exit test: a seeded failing PR is fixed within two attempts or reset once; a dropped task appears in the weekly report.

#### Phase 9: triage and self-healing

Deliver: daily triage over the error tracker with the local model; board issue under the charter; fix run that starts from a failing test; close when the error stays gone for the (shortened) window, reopen otherwise.

Exit test: see the checkpoint.

#### Checkpoint: full loop

A seeded production error is detected → triaged into a board issue → fixed by a run with a red-then-green test → merged by you → deployed → error gone → issue closed. A reopen records a strike.

This is the complete ASDI lifecycle. Everything after it is breadth and hardening.

#### Phase 6: ledger, metrics, reports

Deliver: TRM ledger table with first-pass approvals and reverts per task type, all at T0; the metrics of §14.2 that Pass 1 can measure; weekly report; notifications to a log; `CORRECTIONS.md`.

Exit test: the weekly report shows counts that match the board and GitHub.

#### Phase 8: flags

Deliver: flag file, default off; `exposure` CLI to turn a flag on, keep or kill; a sweep that opens a cleanup issue at expiry.

Exit test: a flag with no decision by expiry is killed and gets a cleanup issue; a state-changing diff behind a flag is still judgment-class.

#### Phase 10: probation

Deliver: three task types at T0, five tasks each, through the board. The Phase 1 exit test repeated under the second agent CLI. `GATE.md` (§15).

### 13.4 Pass 2: hardening

Start only after the full-loop checkpoint. Each item is independent; build and test one at a time. The spike for an item is done when that item starts, not before.

| Item | Adds | Sections | Needed before agent merges |
|---|---|---|---|
| P2-1 | Evidence and image signing; signer container | §8.2, §12.2 (S-9) | Yes |
| P2-2 | Seeded defects and the seed suite | §6.6, §11.5 | Yes |
| P2-3 | Four review passes, deep sample, independent-family rule | §10.3 (S-3) | Yes |
| P2-4 | Static-gate ratchet, waivers, fail-closed tests | §7.4, §9.5, §9.6 | Yes |
| P2-5 | TRM T1 and T2 transitions with preconditions; merge bot live; sampling; circuit breaker | §9.2 | Yes |
| P2-6 | Compounding ladder, rule registry, skill evals | §6.5, §11.1, §11.2 | No |
| P2-7 | Pause and resume; per-run service containers; steer agent | §7.2, §11.3 (S-8) | No |
| P2-8 | Probe runner, canary stages, drift sweep | §11.4, §12 | No |
| P2-9 | Structured log extraction for triage and the MCP log path | §10.4 | No |
| P2-10 | Package proxy | §7.5 (S-11) | No |
| P2-11 | GrowthBook and experiment readouts | The Design doc §05 (S-6) | No |
| P2-12 | Brief compiler; UI driver hardening; offsite backups and restore drill | The Design doc §07 (S-7) | No |

### 13.5 Spikes

One page each under `spikes/`. Run a spike when its phase or item starts, not earlier.

| ID | Question | When |
|---|---|---|
| S-4 | GitHub: a required status pinned to one identity, and whether that identity must be a GitHub App; the agent token cannot merge; rate use of a 60 s poll | Phase 0 |
| S-1 | Board: cancel a running task from outside | Phase 2 |
| S-2 | Board: start a run through a wrapper command, so the launcher creates the container | Phase 2 |
| S-12 | Each agent CLI with no credential in the container, model key added by the egress proxy | Inside Phase 1; no separate page unless it fails |
| S-3 | Archon running a review pass on a different model family than the build agent | P2-3 |
| S-9 | Sign an in-toto statement for a non-image subject with a local key and verify it elsewhere | P2-1 |
| S-8 | Socket proxy allowlist for service containers | P2-7 |
| S-5 | vllm-mlx: reserve one instance for products while agent requests queue or shed | P2-7 |
| S-11 | Package proxy enforcing a minimum release age | P2-10 |
| S-6 | GrowthBook data source for experiment analysis | P2-11 |
| S-7 | Headless UI driver under the egress allowlist | Phase 3 if the toy UI feature needs it, else P2-12 |
| S-10 | Merge queue without Actions | Only if DD-12 changes to a merge queue |

## 14. Standing checks

### 14.1 Hard-rule and verification suite

`tests/rules/`, run on every PR to the ASDI repo and before the gate. Pass 1 runs rows 1 to 7, C-5, N-4 and N-19. Each other row joins with its Pass 2 item. The handbook's §11 gives the adequacy criterion behind each trust layer.

| Rule | Negative test |
|---|---|
| 1 Merge authority | Agent and status identities refused on merge; only the merge identity merges |
| 2 `done_check` | A red verifier cannot be reported green by any agent CLI |
| 3 Sandbox | A run container cannot reach `prod`, the socket, another run's network, or a host off the allowlist |
| 4 Secrets | No token or model key in run, service, verifier or CI job containers |
| 5 Guardrails | Each limit kills the run; a resume does not reset them |
| 6 Irreversible | Migration, force-push, ramp, external side effects refused for agent identities |
| 7 Protected paths | Generated and vendored edits fail; `verify/`, `evals/`, `.asdi/`, test and CI edits flagged |
| C-5 | Verifier uses base-branch harness and gate manifest; a weakened proof in the PR has no effect |
| N-4 | Uncovered path forces judgment |
| N-18 | An unsigned or agent-signed statement fails the gate; a tampered file fails |
| N-19 | A failing post-merge check on `main` opens an auto-revert; a commit with no passing `main` result is not deployed; stale verdicts rejected |
| N-21 | Injected instructions in a log line, a stranger's comment and a counter-case have no effect |
| N-22 | Fresh package version refused; install script not run; registry write refused |
| N-23 | Every row of §9.5 fails closed; an expired waiver blocks again |

### 14.2 Metrics and countermeasures

the Design doc §10, plus:

| Metric | Countermeasure |
|---|---|
| Feature-map coverage | False-green rate: verifier `pass` followed by revert or escaped defect |
| Verifier pass rate | Control catch rate; share of `blocked` and `error` |
| Evidence current-head rate | Invalidations per PR; integrity failures |
| Seeded-defect catch rate, per control | Missed seeds; reviewer false positives |
| Drift age per feature | Verify-only PRs rejected in review |
| Rules in the registry | Recurrences per rule; share at layer 4; active waivers |
| Skill PRs merged | Eval regressions caught |
| Runs preempted | Resume success rate |

## 15. Gates

### 15.1 Deploy gate, after Pass 1

Stop here. Do not deploy a real product or touch real secrets until the human has answered.

Write `GATE.md`:

1. One section per register row that Pass 1 exercised (§4): options, what the prototype showed, cost of switching later, recommendation.
2. Results of spikes S-1, S-2 and S-4.
3. Both checkpoints, the suite result (§14.1) and probation metrics.
4. Open risks (§17) with status, and the list of Pass 1 stand-ins still in place.

After the human answers:

1. Apply each answer as a config or adapter change. Re-run the suite.
2. Replace throwaway identities and tokens.
3. Set real limits; confirm the prod reserve under load.
4. Enable `ingress`: tunnel, TLS, no inbound ports.
5. Configure offsite encrypted backups; run one restore. Migrations stay blocked until it passes.
6. Start the external probe and push alerts.
7. Apply the macOS host rules of the Design doc §06.
8. Build the first real product's `.asdi/` and `verify/` before admitting any other task type.
9. Deploy. The human merges everything. Every task type is at T0.

### 15.2 Agent-merge switch, after Pass 2

Agent merges stay off until P2-1 to P2-5 are built and tested, and the human says so. Present the remaining register rows (DD-22 to DD-25, DD-28 to DD-36) with what was learned, the same way as at the deploy gate.

Stop and ask at any point only when: a hard rule or C-5 cannot be enforced; a spike breaks a settled constraint; no reversible default exists; an action would leave the sandbox repo or the ASDI directories; or you would need a real secret, a paid plan change, or a public endpoint.

## 16. ASDI repo layout

```
asdi/
  compose.yaml
  config/      defaults  classes  coverage  limits  services  probes  evals
               waivers  dependencies  identities  seeds
  schemas/     run-contract  product  verify  feature  result  statement
               pass  static-gates  rules  seed  waiver
  board/       adapter interface, multica/, paperclip/
  AGENTS.md    points the builder at this guide; CLAUDE.md is one line: @AGENTS.md
  launcher/    run lifecycle, guardrails, verifier, static-gate runner,
               agents/ (adapters: claude-code, codex),
               pause/resume                                         (CLI)
  evidence/    store, put/get/link/verify, attest                   (HTTP + CLI)
  events/      source interface, poller/, audit log
  archon/      pipelines: pr-gate, post-merge, passes, class-check,
               packet, fix-loop, compounding, skill-eval, seed-suite, drift,
               triage, readout, sweeps, trm
  merge/       merge adapter, dry-run
  ci/          job runner, sign step
  deploy/      deployer, rollback controller, canary
  probes/      probe runner
  backup/      snapshot, verify, restore
  exposure/    ramp, keep, kill
  ops/         external probe, notify, offsite adapters
  infra/       proxy/, egress/, package-proxy/, socket-proxy/, runtime.md
  images/      run image base, verifier entrypoint
  tests/rules/ standing suite
  spikes/      S-1 .. S-12
  STATUS.md  DECISIONS.md  ASSUMPTIONS.md  GATE.md
```

## 17. Failure modes

| Failure | Signal | Mitigation |
|---|---|---|
| Agent weakens verification to pass | Edits to protected paths in a product PR | Verifier reads harness and gate manifest from the base branch; class check fails the PR |
| Verification theatre | Control `missed` | Mandatory negative control; `control` in every verifier run |
| False green | Revert or escaped defect after `pass` | Paired metric; demote to T0; harness task |
| Controls never tested against real faults | Seed catch rate unknown or falling | Seed suite before promotion and on every model release |
| Stale evidence authorises a merge | Verdict or manifest for an older commit | Evidence bound to its commit; invalidation on a new head; post-merge check on `main` |
| Forged evidence | Signature fails or signer is not the verifier identity | Signer holds the key; agents and verifier never do |
| Hardening built before the lifecycle works | Weeks pass with no change reaching production | Pass 1 stand-ins; no Pass 2 item before the full-loop checkpoint |
| Prompt injection through logs, comments or the packet | Seeded injection changes behaviour | Untrusted-text boundary; allowlisted commenters; reviewers read-only; runs hold no secrets |
| Compromised dependency | Fresh version in a lockfile diff; install script executed | Cooldown at the package proxy; scripts off; lockfile-only installs; new packages are judgment |
| Coverage gate floods the human | Notification queue at K | Harness first; WIP limit; coverage precondition on promotion |
| Flaky proof | Same commit alternates `pass` and `fail` | Treated as `blocked`; harness task; quarantine only by expiring waiver |
| Stale feature map | Drift age rising | Drift sweep; stale features force judgment |
| Product bug hidden by a harness edit | Verify-only PR changes an expected value | Drift sweep opens an issue; reviewer checks expected-value changes |
| Waivers accumulate | Active waiver count; expired waivers renewed | Expiry is mandatory; weekly loop reviews; non-waivable list |
| Evidence leaks user data or fills the disk | Scrubber hits; quota alarm | Scrub on `put`; fixtures only in runs; retention and quota |
| Service image abuse | Unapproved image requested | `config/services.yaml` allowlist |
| Preemption loses work | Resume fails | Launcher archives the worktree when the agent misses the grace period |
| Eval cost runs away | Eval budget burn | Separate budget; N from config |
| Compounding bot adds text rules | Share of layer-4 rules rising | Ladder; escalation on recurrence |
| A deferred decision gets baked in | Adapter switch breaks tests elsewhere | Stub adapter from Phase 2; process boundaries |
| Socket holder compromised | Unexpected container on `prod` | Socket proxy allowlist by name pattern |
| Run escapes to the shared kernel | Rule 3 test fails | No privileged mode, no host mounts, dropped capabilities, user namespaces |
| Agent burst starves prod | Prod latency tracks agent concurrency | Limits, OOM priority, production-first admission via pause |
| Poller stalls | No status for 5 minutes | Health check on `ops`; reconcile from current state |
| Archon scripts the build agent | New pipeline step inside a run | Such workflows are judgment-class |
| Shared disk fills | Free space alarm | Disk janitor; image pruning; separate volumes |
| Docker daemon restart takes prod down | Probe fails during a runtime upgrade | Announced windows only; `restart: unless-stopped`; probe alert |
| Prototype default mistaken for a decision | `GATE.md` section missing options | Every register row needs options and switching cost |
| The two documents drift apart | A term, path or schema differs between them | §19 crosswalk; shared items change in both in one PR |

## 18. Audit events

Append-only table in Archon's database. No message broker. Pass 1 emits whichever of these its parts produce. The handbook defines no event list of its own and defers to this one.

```
project.capabilities.registered
run.contract.compiled | run.admitted | run.started | run.paused
run.resumed | run.cancelled | run.finished
static_gate.completed | verification.completed
evidence.ingested | evidence.attested | evidence.invalidated
review.requested | review.completed
gate.evaluated            # sha, decision, rules fired
waiver.granted | waiver.expired
merge.completed | main.verified | main.reverted
release.started | release.healthy | release.rolled_back
production.defect.detected | defect.fix.verified
seed.caught | seed.missed
trust.level.changed
rule.candidate.created | rule.promoted | rule.retired
verification.drift_detected
```

Reporting files: `STATUS.md` (phase, exit tests, blockers; every session), `DECISIONS.md` (the register and what the prototype taught), `ASSUMPTIONS.md`. One phase deliverable per PR against the ASDI repo.

## 19. Crosswalk to the trust handbook

| Handbook section | Subject | Here |
|---|---|---|
| §0 Executive decision | ASDI as a trust control plane | §1, §3 |
| §1 Scope and authority | Document boundaries, precedence, C-0 to C-5 | §1.1, §1.2, §2 |
| §2 Trust baseline | Why an agent's own report is insufficient | §2 (C-5), §7.3 |
| §3 Ownership boundary | Native, harness, request | §3 |
| §4 Six logical modules; N and H catalogs | Grouping of native parts and harness artifacts | §3.1, §3.2, table below |
| §5 Five trust layers | L1 codebase, L2 static, L3 rules, L4 review, L5 skills | L1: §6, §11.1 · L2: §6.4, §7.4 · L3: §3.3, §6.5 · L4: §10 · L5: §6.1 to §6.3, §7.3 |
| §6 Correction ladder mapping | Four correction levels against the five layers | §11.1 |
| §7 Rule classes and lifecycle | Four classes, the seven hard rules, instruction source | §6.5, §11.1, §11.2, §1.3, §14.1 |
| §8 Evidence validity | Validity conditions, staged signing, what the deployer trusts | §8, §9.4, §12.2 |
| §9 Review and delivery authority | Passes, change classes, direct merge, human touchpoints | §10, §9.1, §9.4 |
| §10 Trust and TRM | Levels, promotion as a proof obligation | §9.2, §11.5, §13.4 (P2-5) |
| §11 Acceptance criteria | Positive and adversarial evidence per layer | §13.3 exit tests, §14.1, §11.5 |
| §12 Metrics and operations | Paired metrics | §14.2 |
| §13 REV K conflict register | Corrections made on the handbook side | §19.1 |
| §14 Companion crosswalk | The handbook's own map to this guide | This section |

Handbook logical modules to components:

| Handbook module | Components here |
|---|---|
| Trust Profile Registry | `.asdi/product.yaml` indexed by Archon; TRM ledger |
| Verification Contract Compiler | Brief compiler; contract validation in `launcher/` |
| Evidence Ledger | `evidence/` (N-2, N-18) |
| Gate / Policy Evaluator | `archon/` class check and post-merge check (N-4, N-5, N-19, N-23) |
| Review Coordinator | `archon/` passes (N-6 to N-8), deep sample |
| Trust and Rule Lifecycle | TRM ledger, compounding, seed suite, skill evals (N-10, N-11, N-20) |


### 19.1 Revision note: differences closed at REV K

Historical. Between guide v4 and the handbook's REV K revision, the handbook (then rev 2) differed from this guide on the seven points below. The handbook's REV K revision closed them, and the two documents now agree. The table is kept only to explain older references. The handbook's own §13 records the full list of corrections made on its side.

| Point | Handbook rev 2 | Agreed at REV K |
|---|---|---|
| Merge path | A merge-queue tier (Tier B) re-ran gates on the queue's temporary commit | No merge queue. Checks re-run on `main` after the merge, with auto-revert (§9.4) |
| Evidence binding | Bound to commit and tree; the deployer required a merge-group attestation for the tree | Bound to the commit. The deployer requires a passing `main` result for that commit |
| Timing of hardening | Signed evidence, static-gate ratchet, seeds and four passes in Phases 1, 3 and 4 | Pass 2 items P2-1 to P2-4. Pass 1 uses the stand-ins in §13.2 |
| Checkpoints | One vertical-slice checkpoint between Phases 4 and 5, with seeds caught | Two Pass 1 checkpoints, first light and full loop. Seeds are P2-2 |
| Merge events | `merge.enqueued`, `merge_group.verified` | `merge.completed`, `main.verified`, `main.reverted` |
| Gate result | Carried a `tier` field | No tier. One gate on the PR head, one check on `main` |
| Instruction file | Requests in `CLAUDE.md` | `AGENTS.md` is the source of truth; `CLAUDE.md` imports it |

### 19.2 Shared facts: Design doc, Stack doc, guide

These must read the same in all three, and in the Trust Handbook. Change one, change them all, and keep the revision letter equal.

| Fact | Value | Design doc | Stack doc | Guide |
|---|---|---|---|---|
| Names | Design doc, Stack doc, guide, Trust Handbook | Header | Header | Header |
| Revision | REV K | Header | Header | Header |
| Constraints | C-0 to C-5 | §00, §02 | Header | §2 |
| Host and zones | One Mac Studio; Docker networks `prod`, `agent`, `staging`, `ops`, one per run; no VMs | §06 | §01, §04 | §5 |
| Archon | Own container; pipelines only; never scripts the build agent | §04, §08 | §00, §01 | §2, §16 |
| Board | D-9 deferred; Multica as the prototype default, behind an adapter | §12 | §00, §06 | §4 |
| Run launch and verification | ASDI launcher; verifier re-runs checks in a clean container from the base branch | §02, §08, §13 | §01 | §7 |
| Evidence | Hashed statement per run; signed in Pass 2 | §13 | §01 | §8 |
| GitHub | Passive; required statuses `ci` and `asdi/policy`; up-to-date branch; three identities; 60 s poller | §02, §08 | §01, §02 | §9, §13.3 |
| Merge path | Direct merge; same checks on `main` after merge; auto-revert; no merge queue | §02, §13 | §01, §02 | §9.4 |
| Review | One pass in Pass 1; four passes and a deep sample in Pass 2 | §01, §13 | §01 | §10.3 |
| Deploy | Only a `main` commit that passed the post-merge check; blue/green; rollback | §05, §13 | §01 | §12.2 |
| Agents | Claude Code and Codex through one adapter; `AGENTS.md` is the instruction file and `CLAUDE.md` imports it; the launcher's verifier decides for every CLI | §02, §13 | §00, §01 | §1.3, §7.6 |
| Build order | Pass 1 lifecycle with two checkpoints, then Pass 2 hardening | §12 | §04, §07 | §13 |
| Decisions | All deferred to the deploy gate; register in the guide | §12 | §06 | §4, §15 |
