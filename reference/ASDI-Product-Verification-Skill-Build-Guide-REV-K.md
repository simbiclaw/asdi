# ASDI Product Verification Skill Build Guide

**Companion to:** ASDI Design doc REV K · ASDI Stack doc REV K · ASDI Build Guide V4 REV K · ASDI Trust Handbook REV K
**Scope:** Build the product-specific verification capability that ASDI runs independently to verify software changes produced by its agents.
**Audience:** Product-repository owners, Claude Code, Codex, and engineers implementing the ASDI verifier.
**Status:** Implementation guide; examples are illustrative unless explicitly identified as a Design REV K contract.

> **Core principle:** Do not build a prompt that says “test your work.” Build a product-specific capability that can exercise important product behavior, compare observed results with literal expectations, detect a deliberately introduced defect, and emit evidence that ASDI can independently reproduce and trust.

---

## 0. Document authority and how to use this guide

This guide explains how to construct the **product side** of ASDI verification. It does not redefine ASDI's launcher, verifier, schemas, phase order, topology, or gate behavior.

Use the four specifications with their established ownership:

| Specification | Authority | This guide must not override |
|---|---|---|
| **Design doc REV K** | Product intent, C-0–C-5, seven hard rules, lifecycle, change classes, TRM, verification doctrine | The rule that only ASDI-run verification counts (C-5); project harness ownership; H/N capability boundaries |
| **Stack doc REV K** | Component choices, local topology, runtime/network responsibilities and operational roles | Docker/Compose topology, one container/network per run, passive GitHub, local poller, Archon and launcher ownership |
| **Build Guide V4 REV K** | Normative implementation source for exact repository layout, schemas, launcher interfaces, evidence manifest, phase order, commands and exit tests | Any exact schema or phase command not reproduced from the local authoritative copy |
| **Trust Handbook REV K** | Why controls exist, native-versus-harness ownership, five trust layers, evidence adequacy and TRM rationale | Alternate schemas, another phase plan, or a second control plane |

**Precedence:** Build Guide V4 governs exact implementation details. Design REV K governs intent and hard rules. Stack REV K governs component/topology realization. The Handbook explains trust rationale and adequacy. When this guide gives a schematic example, replace it with the exact V4 schema if there is any difference.

**Source availability note:** The published V4 URL supplied for this work returned HTTP 404 during retrieval. The Design and Stack REV K pages and the available REV K Handbook were readable. This guide therefore preserves the known REV K harness contract and points exact field names, command syntax, layouts and phase tests back to the local authoritative Build Guide V4. Do not infer an undocumented V4 field or command from an example below.

### 0.1 What this guide builds

It builds the **product harness** consumed by ASDI's N-1 verifier:

- H-1: the product's agent-facing `verify/SKILL.md` and its single executable interface;
- H-2: feature map describing what behavior exists and how to prove it;
- H-3: negative controls demonstrating that proofs catch known faults;
- H-4: deterministic fixtures and drivers;
- the related product declarations and supporting artifacts defined by Build Guide V4.

ASDI-native capabilities N-1, N-2, N-4, N-5, N-17 and N-19 execute, protect, store and enforce the verification result. The product harness does not implement those platform authorities.

### 0.2 What this guide does not build

It does not create:

- a replacement for `asdi-build-conformance` (which audits ASDI's own code against the four specifications);
- another orchestrator, agent persona, review pipeline or merge authority;
- a new config system or a second feature registry;
- a model-dependent test runner;
- a mechanism for the agent to certify its own success;
- production write probes or credentials inside a verifier/run container;
- a new set of services for each H/N capability.

---

## 1. The two skills must remain distinct

There are two different verification problems in ASDI.

| Skill | Purpose | Runs against | Authority |
|---|---|---|---|
| `asdi-build-conformance` | Audit whether ASDI implementation work conforms to the four ASDI specifications | ASDI repository | Read-only auditor; cannot make a build green |
| Product `verify/SKILL.md` | Teach an agent how to launch, inspect, exercise and verify one product | Product repository | Procedural interface only; no authority to declare ASDI green |

The product verification skill is a **capability description**, not the trusted verifier. The harness executable performs deterministic operations. ASDI's clean verifier independently runs those operations and evaluates the result.

Never name the product skill `asdi-build-conformance`. Never make the product skill read or judge the four ASDI architecture specifications as its normal job. Its job is to know how to verify the product it lives with.

---

## 2. Architecture and ownership boundary

The verification chain has five distinct elements:

```text
Product behavior and feature contract
              │
              ▼
Product verification harness
  SKILL.md + feature map + fixtures + drivers
              │
              ▼
ASDI launcher / clean verifier (N-1)
  trusted base-branch verification inputs
              │
              ▼
ASDI evidence store (N-2)
  manifest + content-addressed evidence
              │
              ▼
ASDI gate / policy decision
  coverage + static gates + review + change class
```

### 2.1 Ownership table

| Concern | Owner | Why |
|---|---|---|
| Product domain semantics and expected behavior | Product repository | Only the product can define intended behavior |
| Feature map and product paths | Product repository | Product-specific impact and proof mapping |
| CLI/HTTP/UI/job/property drivers | Product repository | Depends on actual product interfaces |
| Fixtures and negative-control cases | Product repository | Need domain-specific expected and faulty cases |
| `verify/SKILL.md` | Product repository | Agent-facing procedure for this product |
| Static gate declarations and project rules | Product repository, in V4-defined locations | Language/framework/toolchain-specific |
| Clean verifier, base-branch resolution, sandbox and resource boundaries | ASDI-native | Must be independent of the implementing agent |
| Coverage/protected-path enforcement | ASDI-native | Candidate cannot decide its own proof coverage or weaken existing controls |
| Evidence storage, provenance, freshness and integrity | ASDI-native | Must outlive a run and be independently trustworthy |
| Gate decision, merge authority and post-merge verification | ASDI-native | Cross-runtime authority; not an agent instruction |
| TRM, skill evaluation and drift decision state | ASDI-native | Cross-run, auditable trust decisions |

**ASDI-native means a logical capability, not necessarily a new service.** Use the existing launcher, verifier, Archon workflows, local poller and evidence store as assigned by the Stack and Build Guide. Do not create one deployable per N-capability.

### 2.2 The C-5 boundary

The Design's C-5 rule is decisive: an agent's success claim never counts. Only verification ASDI runs itself counts.

Therefore:

- Agent-local tests are useful development feedback, not authoritative ASDI evidence.
- An agent can request or propose verification, but cannot write an authoritative verifier result.
- The clean verifier does not inherit the agent's conversation, working process, mutable workspace, or self-reported outcome.
- A passing skill invocation does not make a run green unless ASDI reruns it under the trusted verifier boundary.

---

## 3. Start with product discovery, not `SKILL.md`

Do not ask an agent to write a verification skill before it understands the product. First build a small, evidence-backed map of observable behavior.

### 3.1 Establish the product surface

Inspect the product's actual entry points and state boundaries. Typical surfaces include:

| Surface | Discover | Useful proof forms |
|---|---|---|
| CLI | Commands, options, exit codes, stdout/stderr, files created | Exact output, exit status, file bytes, structured output comparison |
| HTTP/API | Routes, methods, request/response schemas, auth boundary, status codes | Exact response fields, status, persisted state, idempotency |
| UI | Routes/pages, controls, user journeys, loading/error/empty states | Browser interaction, visible state, screenshot where useful, backend state |
| Database | Entities, constraints, transactions, state transitions | Read-back query, invariant, uniqueness, rollback behavior |
| Background job | Trigger, schedule/event, retries, side effects | Job state, output record, retry result, idempotency key |
| Webhook | Signature validation, event mapping, deduplication | Accepted/rejected request, state transition, duplicate handling |
| Library/protocol | Public functions, types, invariants, compatibility contract | Property tests, golden vectors, type/API compatibility |
| Deployment/operation | Health, readiness, telemetry, release behavior | Read-only health and metric observations; no production mutation |

Do not inventory directories for their own sake. Map **user-visible or operator-observable behavior** to the code paths that implement it.

### 3.2 Read before inferring

For each candidate feature, inspect:

1. The real entry point and caller.
2. The domain/state transition it invokes.
3. The persistence or external-system boundary.
4. Existing tests and fixtures.
5. The observable output or state that proves behavior.
6. Known failure modes, bugs and limitations.

Classify statements as:

- **Observed:** verified by reading/executing the current product;
- **Specified:** required behavior from an authoritative product specification;
- **Assumed:** plausible but not yet established;
- **Unknown:** insufficient evidence.

Do not turn an assumption into an expected value. Resolve it with the product owner or keep it in the feature's limits/unknowns.

### 3.3 Select the first slice

For the first harness, select one thin but end-to-end feature that exercises a real product boundary. Prefer a deterministic, low-risk behavior with:

- a reachable entry point;
- a controlled fixture;
- a literal expected result;
- a meaningful negative control;
- no production credential or external side effect.

The ASDI Design's illustrative `export-csv` feature is a suitable pattern. The first product in ASDI's lifecycle is the Guide's toy product; do not start by trying to map the entire ASDI platform.

---

## 4. Model behavior in the feature map (H-2)

The feature map is the central product-specific verification artifact. It has two jobs:

1. Explain how to reach, drive and prove a behavior.
2. Map source paths to the behavior(s) that must be re-verified when those paths change.

A feature is not a source directory or a test file. It is an independently meaningful behavior with an observable contract.

### 4.1 A feature proof must define

| Element | Question | Minimum quality bar |
|---|---|---|
| Identity | What behavior is this? | Stable feature ID and plain-language title |
| Ownership paths | Which product paths can affect it? | Specific paths; no broad catch-all without rationale |
| Reach | How does the driver get to the behavior? | Actual CLI/API/UI/job/protocol entry point |
| Drive | What operation exercises it? | Reproducible, bounded steps using deterministic inputs |
| Observation | What does the system actually produce? | A value/state/output captured from the running product |
| Expected value | What should it produce? | Literal, reviewed expected value—not derived from the candidate output |
| Negative control | What known bad case should be caught? | A defect/input mutation that the proof must detect |
| Limits | What does this proof not establish? | Explicit list, even when empty |
| Optional production probe | What can be checked safely after deployment? | Read-only, allowlisted, no model/write credentials; Pass 2 capability |

Every proof must compare an observed value with a literal expected value. A narrative assertion such as “looks correct” is not a proof.

### 4.2 Illustrative feature file

The following is a **shape example**, not a replacement for the exact frontmatter schema in Build Guide V4. Use the V4 field names, required keys and schema version when implementing.

```yaml
---
id: export-csv
title: Export saved reports as CSV
paths:
  - "src/export/**"
  - "cli/export.py"
drive:
  kind: cli
proof:
  expected_fixture: "verify/fixtures/export-csv/expected.csv"
negative_control:
  fixture: "verify/fixtures/export-csv/malformed-input.json"
  expected_outcome: fail
limits:
  - "Spreadsheet import is not tested by this proof"
---

## Behavior
The CLI exports saved reports as CSV with the documented header and rows.

## Reach
Use the public report export CLI command.

## Drive
Create the deterministic fixture dataset, invoke the CLI, capture exit status,
stdout/stderr and the generated file.

## Observe and prove
Compare the generated file byte-for-byte with the reviewed expected fixture.

## Negative control
Supply malformed input. The command must reject it with the specified error
behavior; a successful export is a failure of the negative control.

## Limits
This proof does not test spreadsheet import, XLSX, streaming export or UI export.
```

### 4.3 Path coverage rules

- Map every product source path that can affect behavior to at least one feature, or leave it explicitly uncovered.
- A changed path with no feature coverage is judgment-class under N-4; do not guess a feature based on a nearby filename.
- A feature may own multiple paths; a path may affect multiple features.
- Do not use `**/*` as a shortcut to make coverage look complete.
- Generated/vendor paths follow Design's protected-path rule; do not add them to normal product-edit coverage.
- Feature-map changes are themselves verification-path changes and must follow the protected-path admission rule.

### 4.4 Adding a new feature

A PR may add a feature file, but it must not edit existing verification files to weaken current proofs. The candidate's newly authored feature definition must not become a self-authorizing trust root for judging the same candidate.

Use the exact new-feature admission procedure in Build Guide V4. If that procedure does not make a newly added feature independently trusted for the current PR, keep the change judgment-class and require the prescribed review. Once merged and present on the trusted base branch, it can participate as an established proof in subsequent runs.

---

## 5. Build the deterministic executable (H-1, H-3, H-4)

Design REV K defines one executable with five commands. The executable must not require a model to run.

```text
verify launch
verify doctor
verify drive <feature-id> [<feature-id> ...]
verify control <feature-id> [<feature-id> ...]
verify cleanup
```

Use the exact path, argument syntax and exit-code mapping specified in Build Guide V4. The commands above express the required interface; do not infer extra flags from this document.

### 5.1 `launch`

Purpose: start the product and its required run-scoped test services using the environment/services provided by ASDI.

Requirements:

- Use run-assigned ports, network, directories and service endpoints.
- Use only approved service images and the V4-defined service declaration mechanism.
- Record which processes/resources this harness starts so cleanup can be ownership-safe.
- Return a clear blocked/error result if prerequisites are unavailable.
- Never start or connect to production services.
- Never read production credentials or rely on a developer's logged-in browser session.

### 5.2 `doctor`

Purpose: establish that the verification environment is ready and belongs to this run.

Requirements:

- Check application and required service readiness.
- Check endpoint and resource ownership.
- Check required binaries/tool versions and fixture availability.
- Be read-only: it must not mutate product state to make the environment appear healthy.
- Distinguish a failed health condition from an unavailable/invalid test environment.

### 5.3 `drive`

Purpose: exercise the selected product feature(s) and collect observed results.

For each feature:

1. Load the trusted feature definition supplied to the verifier.
2. Prepare deterministic, isolated fixtures.
3. Reach the product using the declared interface.
4. Exercise the behavior.
5. Capture actual output/state, including relevant errors.
6. Compare actual values with literal expected values.
7. Record status, evidence references and limits.

The harness must not decide expected values by copying the candidate's output. Expected fixtures are reviewed product contracts.

### 5.4 `control`

Purpose: prove that the feature verification procedure detects a deliberate fault.

A control is not merely a second positive run. It must challenge the specific property the proof claims to establish.

Examples:

| Proof claim | Useful negative control |
|---|---|
| Export includes every row | Remove or corrupt one expected row; proof detects mismatch |
| API rejects invalid input | Supply a malformed/unauthorized request; proof observes rejection |
| State transition is atomic | Inject a failure between writes; verify no partial state survives |
| Evidence digest detects mutation | Alter an isolated test copy; integrity check rejects it |
| Duplicate webhook is idempotent | Replay the same event; no duplicate side effect occurs |
| Run is isolated | Attempt a prohibited cross-run/production reach from the isolated test environment; connection must fail |

The control's success means **the fault was caught**, not that the corrupted operation itself passed. Store the injected fault identity and observed detection result.

### 5.5 `cleanup`

Purpose: stop only resources owned by this verification run.

Requirements:

- Stop processes and services started by `launch`.
- Remove only run-scoped temporary state.
- Do not stop shared infrastructure or another run's resources.
- Preserve evidence in the ASDI-provided evidence location.
- Be safe to call after partial launch or partial test failure.
- Report cleanup failures; do not silently claim success.

### 5.6 Status semantics

Use the exact V4 result schema. The Design's outcome vocabulary is:

| Status | Meaning | Gate effect |
|---|---|---|
| `pass` | Observed value matches the literal expected value | Only status that satisfies a gate |
| `fail` | Product behavior or control assertion is wrong | Reject |
| `blocked` | Required environment or precondition unavailable | Does not satisfy; fail closed |
| `error` | Harness/tool crashed, timed out or produced invalid output | Does not satisfy; fail closed |
| `not_applicable` | Proof does not apply to this change | Not a pass; use only when policy allows it |

Do not collapse these states into a boolean. Never retry a flaky check until it happens to pass and then discard the earlier failures. Record retry policy and outcomes exactly as V4 prescribes.

---

## 6. Write the agent-facing `verify/SKILL.md`

Only write the skill after the executable and at least one feature proof work. The skill explains how an agent should use the harness; it should not reimplement the harness in prose.

The Design/Handbook contract calls for these nine topics:

1. **Surface** — what the product exposes and the feature map location;
2. **Launch** — how to start the product;
3. **Doctor** — how to establish readiness;
4. **Drive** — how to exercise feature proofs;
5. **Observe** — what to inspect and how actual results are judged;
6. **Isolate** — run ownership and prohibited resources;
7. **Evidence** — where and what to write;
8. **Cleanup** — how to safely release run-owned resources;
9. **Limits** — what the harness cannot prove.

### 6.1 Ready-to-adapt skill template

Use this as a starting point. Replace placeholders with verified repository facts and the exact V4 interface. Do not leave bracketed placeholders in a merged skill.

```markdown
---
name: product-verification
description: >-
  Use this skill to launch, inspect, drive and verify this product through its
  deterministic verification harness. Use when implementing, debugging or
  reviewing product behavior. The executable harness, not the agent's judgment,
  produces test observations.
---

# Product Verification

## 1. Surface

This product exposes: [CLI/API/UI/jobs/protocols].
The feature map is in `verify/features/`.
Select features from the changed product paths. Do not infer coverage from
file names or from the task description alone.

## 2. Launch

Run the repository's verification executable using the V4-defined interface:

    verify launch

Use only the run-scoped services and endpoints supplied by ASDI. Do not use
production services, production data, personal credentials or a logged-in
browser session.

## 3. Doctor

Run:

    verify doctor

This check is read-only. Stop if the environment is blocked, misidentified or
not owned by this run. Do not repair readiness by mutating product state.

## 4. Drive

Run the selected feature proofs:

    verify drive <feature-id>

Use the feature map to identify the actual user/operator entry point. Exercise
the running product; source inspection alone is not product verification.

## 5. Observe

Compare observed values with the literal expected values defined by the
trusted feature contract. Capture relevant output, state, errors, screenshots
or traces. Do not infer a pass from plausibility or from your own code changes.

## 6. Isolate

Use only run-owned ports, services, directories and fixtures. Never access
production networks/secrets, another run's mutable state, or shared user data.

## 7. Evidence

Write only to the evidence location supplied by ASDI. Record feature identity,
status, observed result, evidence references and proof limitations using the
V4 result schema. Never mark an unexecuted check as passing.

## 8. Cleanup

Run:

    verify cleanup

Stop only resources created by this run. Preserve the evidence directory.

## 9. Limits

Every feature proof declares what it does not cover. Do not claim that a
passing feature proof certifies the whole product, untested paths, production
behavior or security properties outside its defined scope.
```

### 6.2 Skill quality rules

- Make steps executable and concrete; avoid generic advice such as “test thoroughly.”
- Keep domain knowledge in feature files and deterministic drivers where possible.
- Do not include secrets, credentials, live user data or production URLs containing sensitive tokens.
- Do not ask the agent to edit expected outputs to make tests pass.
- Do not tell the agent to use its own test result as ASDI evidence.
- Keep the skill short enough to be reliably consumed; link to feature files rather than copying the entire feature map into the prompt.
- Treat instructions as workflow guidance, not as security enforcement.

---

## 7. Evidence: product result versus ASDI evidence statement

There are two layers of record.

### 7.1 Product harness result

The product harness emits the exact V4-defined result format. At minimum, each feature result needs to distinguish:

- feature ID;
- status (`pass`, `fail`, `blocked`, `error`, `not_applicable`);
- observed result or observation references;
- evidence files/references;
- negative-control outcome where run;
- limits / uncovered scope.

The agent may see and discuss this result during its run. It is not authoritative merely because it exists in the agent workspace.

### 7.2 ASDI evidence statement (N-2)

ASDI's trusted verifier stores the authoritative record, including the provenance and inputs needed to interpret it. The Design and Handbook require evidence to be:

- **revision-bound:** the subject commit is the exact commit being judged;
- **producer-bound:** Pass 1 writes through the trusted launcher/verifier path, not the agent;
- **environment-bound:** verifier image digest and relevant tool versions are recorded;
- **input-bound:** harness and static-gate inputs come from the pinned trusted base branch; product profile/gate hashes are recorded;
- **integrity-protected:** content-addressed evidence and hashes match stored content;
- **fresh:** any new PR head invalidates all earlier evidence and review verdicts for that PR in this version;
- **honest:** statuses remain distinct; only `pass` satisfies a gate;
- **bounded:** every proof states what it does not cover.

Pass 1 uses a hashed evidence statement/store. Signed in-toto/DSSE attestation is Pass 2 hardening (N-18). Do not claim Pass 1 evidence is signed.

### 7.3 Minimum useful evidence

Prefer evidence that allows an independent reviewer or rerun to answer:

- Which feature was exercised?
- Which exact commit was under test?
- Which trusted feature definition and harness revision were used?
- Which literal expected value was compared?
- What was actually observed?
- Which negative control was injected and was it caught?
- Which files are available and how is integrity checked?
- What was not tested?

A screenshot without the route/action and expected state is weak evidence. A log line saying “tests passed” without command, revision and output is not adequate evidence.

---

## 8. How ASDI independently executes the harness

The product skill is authored with the product, but ASDI supplies the authority boundary.

### 8.1 Trusted input rule

For a candidate PR, the verifier must not let that candidate redefine the checks used to judge itself.

- Pin the trusted base-branch commit.
- Load existing `verify/` material and `.asdi/static-gates.yaml` from that base revision, as required by N-1/N-5/N-17 and Build Guide V4.
- Execute the candidate product code at the exact candidate head.
- Keep existing verification material protected.
- Apply the V4-defined process for adding a new feature file; do not allow a candidate-authored feature definition to self-authorize its own proof.
- A verification-path edit is flagged and routed according to the Design's hard rule and change-class policy.

The verifier's trust root is outside the agent's authority. A PR that changes an existing test command to `echo pass`, weakens an expected value, removes a negative control or changes a gate threshold must still be judged using the base version.

### 8.2 Independent execution boundary

The Stack assigns ASDI's launcher/verifier to a clean container, one per run, with its own Docker network. The launcher is the only component allowed to call the Docker socket proxy. The agent run cannot reach production, cannot write authoritative evidence and cannot choose the verifier's trusted inputs.

The verifier must not execute inside Archon or inherit the build-agent session. Archon coordinates the pipeline; it does not become the build process or verification authority.

### 8.3 PR and post-merge sequence

The REV K delivery principle is: **test what is on `main`, deploy only what passed there.**

At PR head:

1. Resolve the trusted base revision.
2. Run static gates from base-branch declarations.
3. Determine changed product paths and select all covered features.
4. Route uncovered paths to judgment (N-4).
5. Run product proofs and applicable negative controls in the clean verifier.
6. Validate the result and store evidence (N-1/N-2).
7. Run the required review/class/policy process and post required statuses.

After direct merge:

1. Re-run static gates and the verifier on the exact commit that landed on `main` (N-19).
2. If verification fails, open the prescribed auto-revert and stop release.
3. Deploy only a `main` commit with a passing post-merge result.

Do not introduce a merge queue into this flow. Do not reuse PR-head evidence to authorize a different `main` commit.

---

## 9. Negative controls: prove that the harness can catch failure

A positive proof alone does not establish verifier reliability. H-3 requires a negative control, and the Design says the harness is unusable if its proof does not pass or its negative control is not caught.

### 9.1 Design a good negative control

A useful control has:

1. A named property the proof claims to verify.
2. A deterministic fault or faulty input that violates that property.
3. A defined expected detection result.
4. A record linking the fault to the proof/control.
5. An isolated fixture/environment so the test cannot harm shared or production state.

### 9.2 Avoid weak controls

| Weak control | Why it is weak | Better approach |
|---|---|---|
| Run the same positive test twice | Does not test defect detection | Inject a controlled violation of the claimed invariant |
| Assert that a command exits nonzero for any reason | Crash may be mistaken for correct rejection | Assert the intended error/status and unchanged state |
| Compare output with itself | Candidate output defines its own expectation | Compare with a reviewed literal fixture |
| Mutate production data | Unsafe and unnecessary | Mutate an isolated test fixture or disposable per-run service |
| Add a defect but skip the proof | No demonstration that the proof catches it | Execute the proof against the faulty case and record detection |

### 9.3 Harness self-test

The self-test must establish:

- the product can launch;
- `doctor` reports a healthy, owned environment;
- at least the designated self-test feature proof passes;
- its negative control is caught;
- results conform to the V4 schema;
- evidence is written to the ASDI-provided location;
- cleanup releases run-owned resources and preserves evidence.

If positive proof fails, the harness is unusable. If a negative control is missed, the harness is unusable. Do not lower the expected value to obtain green.

---

## 10. Worked example: build the first skill for the ASDI toy product

The Design's build order places the toy product and its harness in Phase 3, after the thin Phase 1 launcher/verifier/evidence capability exists. The first target is deliberately small: a product with a CLI, HTTP/API surface and a UI, plus the service dependency defined by the Build Guide.

Use the illustrative export behavior from the Design run-contract example.

### 10.1 Define the product behavior

Outcome: the CLI exports saved reports as CSV or JSON.

Constraints from the illustrative contract: no new runtime dependencies; keep report schema v2 unchanged. XLSX, streaming and UI export are out of scope.

### 10.2 Discover and map the feature

Create one feature definition for `export-csv` after inspecting the real CLI and report model. Record its owned paths, exact command, fixture inputs, literal expected CSV, negative control and limits.

Do not copy the illustrative path names from this guide unless they match the actual toy-product repository.

### 10.3 Implement the driver

The driver should:

1. Create or load deterministic report fixtures.
2. Invoke the actual CLI entry point.
3. Capture process exit code, stdout and stderr.
4. Read the generated CSV bytes.
5. Compare against a reviewed expected fixture.
6. Emit evidence files and a structured feature result.

Do not test a private helper instead of the public behavior unless the feature explicitly describes a library contract.

### 10.4 Implement the negative control

Use malformed input or a fixture that violates a defined export invariant. Assert the specified rejection behavior and ensure no misleading partial output is treated as success.

### 10.5 Write `SKILL.md`

Use the nine-section template in §6. Replace every placeholder with the actual toy product's launch, health, drive, observation and cleanup procedures.

### 10.6 Self-test and integrate

Run the five-command sequence. Then ask ASDI's clean verifier to run the same proof with trusted base-branch verification material. Verify the evidence is preserved after run cleanup. Do not claim the toy product harness is complete until the prescribed Phase 3 exit tests in Build Guide V4 pass.

---

## 11. Apply the same method to ASDI itself (second target)

Once the toy product proves the pattern, use a separate ASDI product feature map to verify ASDI's own operator-facing behavior. Do not make the first verifier certify itself before the independent runner and trust root exist.

Start with a few high-value behaviors, not every package or directory.

| Candidate feature | Observable behavior | Example negative control |
|---|---|---|
| `run-lifecycle` | An admitted run follows valid lifecycle transitions and ends in the correct state | Supply an invalid transition/contract; it must not be accepted |
| `c5-verification-authority` | An agent's self-reported success cannot make a run green | Make the agent report success while the independent proof fails |
| `evidence-integrity` | Stored evidence is retrievable and its content hash matches | Alter an isolated copy; integrity check detects mismatch |
| `base-branch-trust-root` | Existing verification/gate inputs come from pinned base | Candidate weakens its own check; verifier still runs trusted base version |
| `run-isolation` | Run container/network cannot reach prohibited zones or another run | Attempt forbidden cross-zone/cross-run connection; it must fail |
| `main-post-merge-verification` | Deployment eligibility requires a passing check on the exact main commit | Make post-merge verification fail; release is stopped and auto-revert path begins |

These are candidate feature definitions, not assumptions about the current ASDI code. For each one, inspect the implemented interface and define the exact drive/observation before writing its feature file.

### 11.1 Keep product tests separate from platform rule tests

Some behaviors are better tested by ASDI's own native test suite rather than a product feature file:

- verifier trusts the base branch, not candidate verification files;
- the candidate cannot change its own static gates;
- only the trusted verifier can write authoritative evidence;
- merge authorization cannot be bypassed by an agent token;
- unavailable checks fail closed;
- no production route or secret is available to the run.

These test N-capabilities and C-/hard-rule enforcement. The product harness feature map proves product behavior. Do not place every platform security invariant in the product's feature map or confuse H-1 with the ASDI build-conformance auditor.

---

## 12. Maintenance and drift

A verification harness is a maintained product asset. If product behavior, entry points or data models change, the harness must be reviewed. But maintenance must never rewrite expected behavior merely to follow a regression.

### 12.1 Change-triggered maintenance

When a PR changes a feature's owned paths:

- confirm the feature still reaches the correct entry point;
- confirm driver and fixtures still represent real user behavior;
- update the expected fixture only when the intended product contract changes and the change is authorized;
- preserve a negative control for every proof;
- update explicit proof limits;
- rerun harness self-test;
- treat changes to existing verification files as protected/judgment changes per the Design.

### 12.2 Drift sweep (N-13, Pass 2)

A drift sweep compares feature maps to the actual product:

- stale paths or removed routes;
- new uncovered product paths;
- dead drivers or fixtures;
- missing or ineffective negative controls;
- tests that no longer exercise the public behavior;
- documentation and feature contract disagreement.

The drift process may propose a harness update. It must not silently edit expected values to make a broken product pass.

### 12.3 Skill evaluation (N-11, Pass 2)

Changes to the skill or persistent instructions need evaluation. Use blinded paired runs with and without the change, across supported agent CLIs. Prefer deterministic outcomes; use a rubric only for judgment that cannot be scored mechanically.

An instruction change is not automatically an improvement because one agent run looked better. Keep evaluation cases stable and require the improvement/regression conditions defined by Build Guide V4.

### 12.4 Five-layer correction rule

When an agent needs human correction, fix the strongest layer that can reliably prevent recurrence:

1. L1: change the codebase/domain structure so the bad behavior is unnatural or impossible;
2. L2: add or strengthen a compiler/type/lint/CI invariant;
3. L3: add a persistent project rule for a convention requiring judgment;
4. L4: strengthen independent automated review for defects that escape earlier controls;
5. L5: improve the procedural skill when the agent lacks a repeatable operational method.

Do not automatically add another paragraph to `SKILL.md` when the architecture or a deterministic check can prevent the error. Skills are for procedures and judgment, not a substitute for enforcement.

---

## 13. Implementation sequence and exit criteria

Follow the lifecycle-first sequence in Design REV K and the exact phase commands/exit tests in Build Guide V4. The relevant order is not simply numerical.

| Sequence | ASDI phase | Product-verification work | Exit evidence |
|---|---|---|---|
| 1 | Phase 0 | Canonical repository scaffold and schemas exist; no alternate config hierarchy is introduced | V4 scaffold/schema/identity/ruleset tests pass |
| 2 | Phase 1 | Launcher, per-run boundary, guardrails, verifier and evidence directory exist | Clean verifier can execute; evidence survives run cleanup; C-5 holds |
| 3 | Phase 3 | Toy product and its H-1–H-4 harness are built by an agent run | Harness self-test passes; positive proof passes; negative control caught; feature map covers required paths |
| 4 | Phase 4 | PR gate calls trusted verifier, checks coverage and protected paths | Candidate cannot self-weaken verification; unavailable checks fail closed |
| 5 | Phase 7 | Post-merge verification/deploy path consumes main-commit result | First-light checkpoint: valid change reaches production; bad change stops/rolls back per V4 |
| 6 | Later Pass 2 | Skill eval, drift sweep, seed suite, signed evidence, production probes and hardening | Exact Pass 2 gates from V4 |

The Design states that seven hard rules and C-5 apply from the first run. The product harness is not allowed to postpone the trust boundary until Pass 2. However, signed evidence (N-18), seeded-defect suite (N-20), skill evaluation (N-11), drift sweep (N-13), and production probes (N-14/N-15) are staged as Pass 2 hardening according to the REV K plan. Do not pull them forward or claim them complete merely because a thin stand-in exists.

### 13.1 Product harness completion gate

A product verification capability is ready for ASDI use only when:

- all required harness commands exist and have tested behavior;
- the designated self-test feature proof passes;
- its negative control is caught;
- results conform to the normative V4 schema;
- every proof compares actual observation against a literal expected value;
- all proof limits are explicit;
- the harness can run without a model;
- it operates only on run-owned resources;
- cleanup preserves evidence;
- the clean ASDI verifier can reproduce the result using trusted inputs;
- feature/path coverage meets the V4 threshold;
- existing verification files cannot be weakened by the candidate being judged.

A harness with a missed negative control is **unusable**, not “partially green.” A blocked or crashed verifier is **not green**. A feature map that does not cover a changed path cannot silently authorize agent-mergeable treatment.

---

## 14. Common implementation mistakes

| Mistake | Why it breaks trust | Correct response |
|---|---|---|
| Write `SKILL.md` first | Produces plausible instructions without executable capability | Discover behavior and build/test harness first |
| Let the agent choose which features to verify | Agent can omit the behavior most likely to fail | ASDI selects features from changed paths and trusted feature map |
| Read feature definitions/static gates only from candidate head | Candidate can weaken its own acceptance criteria | Use pinned base-branch trust root per N-1/N-5/N-17 |
| Treat agent's local tests as ASDI green | Violates C-5 | Clean independent ASDI verification |
| Compare output with itself | No independent expected contract | Literal reviewed expected fixture |
| No negative control | Does not establish that the proof detects failure | H-3 negative control; harness self-test |
| One `pass: true` boolean | Hides blocked/error/not-applicable states | Preserve all V4 statuses; only `pass` satisfies gate |
| Overly broad feature path globs | Fake coverage and missed impact analysis | Narrow path ownership, multiple features where needed |
| Use production data or credentials | Crosses trust boundary and risks real side effects | Deterministic fixtures and isolated per-run services |
| Skill tells agent to edit verifier when it fails | Allows implementer to weaken evaluator | Fail closed; protected verification paths; human/judgment route |
| Add a new config file for every capability | Config sprawl and competing sources of truth | Reuse canonical V4 product-harness layout |
| Treat screenshot as complete proof | Image may not establish state, data or expected behavior | Pair visual evidence with deterministic state/output assertions |
| Claim production safety from local test | Scope exceeds evidence | Declare limits; production probes are read-only Pass 2 capability |
| Build all features before self-testing | Large, expensive failure surface | First vertical slice; prove harness, then expand |

---

## 15. Agent implementation handoff

Use this prompt after the canonical four source documents and their local paths are available in the product repository. Replace the bracketed values. This prompt asks the agent to build the product harness; it does not ask it to modify ASDI-native verification infrastructure.

```text
Build the product-specific verification capability for this repository in
accordance with the four ASDI specifications.

Inputs
- Product repository: [repo]
- Trusted base revision: [base]
- Current candidate revision: [head]
- Current ASDI phase: [phase]
- Four spec paths: [Design REV K, Stack REV K, Build Guide V4 REV K,
  Trust Handbook REV K]

Authority
- Design governs product intent, C-0–C-5, hard rules and verification doctrine.
- Stack governs topology and runtime ownership.
- Build Guide V4 governs exact layout, schemas, commands, phase order and exit tests.
- Handbook governs trust rationale and adequacy criteria.
- Do not invent a schema, CLI flag, service, config file or phase requirement.

Task
1. Inspect the real product before authoring SKILL.md.
2. Inventory product surfaces and candidate user/operator behaviors.
3. Select one deterministic first feature.
4. Create its feature map with owned paths, reach/drive, literal proof,
   negative control and limits, using the exact V4 schema.
5. Implement the single deterministic verify executable with launch,
   doctor, drive, control and cleanup.
6. Add fixtures and drivers for the selected feature.
7. Write the nine-section verify/SKILL.md from the working implementation.
8. Run the complete harness self-test, including the negative control.
9. Verify run-owned resource cleanup and evidence preservation.
10. Prepare the harness for ASDI's independent clean verifier; do not claim
    the agent's run is authoritative ASDI verification.

Safety
- Do not access production, production secrets, live user data or another run.
- Do not edit existing verification files to make the current candidate pass.
- Do not change expected fixtures merely to match observed broken output.
- Do not weaken static gates or coverage.
- Do not add alternate configuration hierarchy or new services without V4 authority.
- Do not mark blocked/error/not-run as pass.

Deliverables
- Feature inventory and rationale.
- Exact V4-conforming feature map.
- verify executable and drivers/fixtures.
- Nine-section verify/SKILL.md.
- Harness self-test output and evidence references.
- Known limits and uncovered paths.
- Phase exit assessment with command and observed result.

Stop and report a blocking ambiguity rather than inventing product behavior or
an implementation contract. Do not modify ASDI-native components unless the
assigned task explicitly includes them.
```

---

## 16. Build-review report template

The implementation agent should leave a concise, auditable report. The report itself is not a gate result; ASDI's verifier produces the authoritative result.

```markdown
# Product Verification Harness Build Report

## Scope
- Product/repository:
- Base revision:
- Candidate revision:
- ASDI phase:
- Spec revisions read:

## Product discovery
- Surfaces inspected:
- Feature selected:
- Owned paths:
- Expected behavior source:
- Unknowns resolved / unresolved:

## Deliverables
- Feature map:
- Executable:
- Drivers/fixtures:
- SKILL.md:
- Product config references:

## Self-test
| Command | Observed result | Evidence | Status |
|---|---|---|---|
| launch | | | |
| doctor | | | |
| drive | | | |
| control | | | |
| cleanup | | | |

## Negative control
- Fault injected:
- Detection expected:
- Detection observed:
- Was the control caught?

## Evidence and limitations
- Evidence location:
- Result schema validation:
- Cleanup preserved evidence:
- Explicit proof limits:
- Uncovered paths:

## Conformance
- H-1–H-4 status:
- N-1/N-2 integration status:
- N-4/N-5 coverage/protection status:
- Phase exit status:
- Blocking gaps:

## Claim boundary
State explicitly: “This report is an implementation handoff. Only the ASDI-run
clean verifier and trusted gate evaluation can establish a green result.”
```

---

## 17. Final mental model

A product verification capability has to satisfy three different tests:

| Property | Question | Owner |
|---|---|---|
| **Capability** | Can the harness reach and exercise the behavior that matters? | Product harness (H-1–H-4) |
| **Reliability** | Does the proof detect a known violation and remain current as the product evolves? | Product negative controls/maintenance; ASDI skill evaluation and drift controls |
| **Enforcement** | Can the implementing agent alter the rules, forge the result or bypass delivery authority? | ASDI-native N-1/N-2/N-4/N-5/N-17/N-19 and hard rules |

These are not interchangeable. A detailed skill without a working driver is not a verification capability. A working positive test without a negative control has unproven detection power. A reliable harness without an independent trust boundary can be weakened by the agent whose work it evaluates.

The end-to-end contract is:

```text
Product defines behavior
        ↓
Feature map declares path, drive, proof, negative control and limits
        ↓
Deterministic harness exercises the real product
        ↓
Positive proof passes AND negative control is caught
        ↓
ASDI reruns using trusted base-branch verification material
        ↓
ASDI validates evidence provenance, integrity, freshness and coverage
        ↓
ASDI gate decides whether the change may progress
```

**The milestone is not “the agent can explain how to test the product.” The milestone is “ASDI can independently reproduce the proof, detect a deliberate defect, preserve trustworthy evidence and refuse progression when verification is absent, invalid or inadequate.”**

---

## References

- ASDI Design doc REV K: <https://claude.biothropic.com/ASDI/ASDI%20Design%20doc-REV%20K.html> — especially §02, §07, §12 and §13.
- ASDI Stack doc REV K: <https://claude.biothropic.com/ASDI/ASDI%20Stack%20doc.html> — especially §01–02 and §04.
- ASDI Build Guide V4 REV K: <https://claude.biothropic.com/ASDI/ASDI-BUILD-GUIDE-V4.md> — normative exact layout, schemas, interfaces and phase exit tests. The published URL was unavailable during preparation; use the local authoritative copy.
- ASDI Trust Handbook REV K: `ASDI-TRUST-HANDBOOK-REV-K.html` — especially ownership, evidence semantics, acceptance criteria and crosswalk.
- Existing `asdi-build-conformance` skill: the separate read-only auditor for ASDI implementation conformance; not the product H-1 skill described here.
