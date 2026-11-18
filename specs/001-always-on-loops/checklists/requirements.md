# Qualification checklist: 001-always-on-loops

Run on 2026-11-18 against `spec.md`.

- **Linter** (`lint_spec.py`): 0 errors and 5 warnings. The counts are 33 FR, 8 SC, 37 scenarios and 0 markers.
- **Verdict**: **Qualified**, with two items that need the owner. Neither blocks planning (see the end of this file).

## Linter warnings, confirmed by reading

| Warning | Line | Judgment |
|---|---|---|
| T01 "class" | Story 3 scenario 3, FR-020 | Domain term: ASDI's *change class* (Design §02). Not an implementation leak. |
| T01 "queue" | Story 5 scenario 5, FR-031 | Domain term: the owner's judgment-review queue (Design §04). Not an implementation leak. |
| T03 file paths | Header, Assumptions, Out of Scope | They point to the companion files and to REV K config that holds the existing values (`config/defaults.yaml`, `config/identities.yaml`). They are kept so the spec can be checked against REV K. No requirement names a file. |

## Content quality

- [x] No implementation details in requirements. Storage, tables, process names and directory layout are in `crosswalk.md` §5 as proposed register rows, not in FRs.
- [x] Focused on owner value: no lost work, things happen on time, no repeated questions, fewer interruptions.
- [x] Readable by the owner without engineering vocabulary beyond ASDI's own terms (PR, run, gate, change class).
- [x] All mandatory sections completed.

## Requirement completeness

- [x] No `[NEEDS CLARIFICATION]` markers. Gaps were filled with provisional defaults, as REV K's Guide §4 asks.
- [x] Requirements are testable. Each FR states one observable behaviour.
- [x] Success criteria are measurable (SC-001 to SC-008 all have numbers).
- [x] Success criteria are technology-agnostic.
- [x] Acceptance scenarios are defined for every story.
- [x] Edge cases are identified (7).
- [x] Scope is bounded (9 out-of-scope items).
- [x] Assumptions and dependencies are identified.

## Feature readiness

- [x] Every FR is cited by at least one scenario; the linter's A04 check passed.
- [x] Primary flows are covered: events, timers, continuity, decisions, outbox, curation.
- [x] Each story has an independent test.
- [x] No implementation leak into FRs.

## Beyond the repo

- [x] **Two-way traceability.** Checked by the linter.
- [x] **Numbers, not adjectives.** These are all stated:
  - 120 s handling start, 15 min lease, 3 attempts, 2 poll cycles, 300 s staleness.
  - 60 min timer firing, 72 h, 14 d, 30 d.
  - 8,000-token budget, 24 h dedup and reminder, queue limit 5.
- [x] **Behaviour defined, not just properties.** Example: FR-005 says what happens to the old evaluation, not only that heads are "handled".
- [x] **Claims match definitions.** FR-019's continuity claim names its inputs: instructions, progress, events and carried-over guardrail use.
- [x] **Examples agree with rules.** Story 1 scenario 8's "3 failed attempts" matches FR-009. Story 2 scenario 4's 6-hour stop matches SC-003.
- [x] **Counts and cross-references are current.** The FR IDs cited in `crosswalk.md` all exist.
- [x] **Volume expectations** appear in SC-002, SC-007 and SC-008.
- [x] **Out of Scope is explicit.**
- [x] **Every requirement traces to a user need** (Stories 1 to 6).
- [x] **Unknowns are visible.** Each new number is marked **(new)** or listed under Assumptions, and proposed as a register row (DD-39 to DD-47).

## Needs the owner (not spec blockers)

1. **X-9**: new audit event names need an addition to Guide §18, which is an authority-document change.
2. **X-6** (resolved 2026-11-18): the hosted reviewer was replaced by the local REV K reviewer.

Ready for the plan step once the owner accepts or amends DD-39 to DD-47.
