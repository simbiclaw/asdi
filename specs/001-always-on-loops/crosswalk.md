# Crosswalk: always-on agent primitives → ASDI REV K

Companion to [`spec.md`](spec.md). The spec says what ASDI must guarantee. This file says where each idea came from, where it lands in REV K, what was rejected, and what needs an owner decision.

**Source.** William Hu, "Building always-on agents", claude.com/resources/articles/building-always-on-agents, read 2026-11-18. It is paraphrased below and treated as design input only. It has no authority over REV K.

**REV K references** are to the authority set in [`reference/AUTHORITY.md`](../../reference/AUTHORITY.md). `Design` is the Design doc REV K, `Stack` is the Stack doc, `Guide` is ASDI-BUILD-GUIDE.md v4, and `Handbook` is the Trust Handbook.

## 1. What the article proposes

| # | Component | Article's design |
|---|---|---|
| A-1 | Wake cycle | "Always-on" is the experience. The agent sleeps, wakes on an event, does one **run** inside a **session**, saves state and sleeps again. Sleep costs nothing. |
| A-2 | Event inbox | Every source writes to a durable event list through a handler. A worker pulls from the list. Status tracking; dedupe on source IDs. |
| A-3 | Inbox practices | Acknowledge fast. Inbox is the source of truth, so a new worker can retry. One active worker per inbox. A mid-run event is queued, folded in, or interrupts. Batch quick messages into one run. |
| A-4 | Timers | Follow-ups (self-set deadlines) and schedules (recurring) live in their own durable store. A scheduler polls it, marks follow-ups done or advances schedules, then writes an inbox event. A timer never starts a run itself. Build it yourself or use a durable execution engine. |
| A-5 | Memory | A durable directory that outlives workers. Store only what cannot be looked up, and use pointers otherwise. Four kinds: user instructions, user notes, past messages and task progress. Index files are loaded every run, details on demand. |
| A-6 | Dreaming | A background process reviews past sessions to curate memory: it replaces stale entries and surfaces patterns that only show up across runs. |
| A-7 | Context overhead | The system prompt, tools and memory are reloaded every run. Keep them lean and use prompt caching. Long sessions are compacted or restarted, so save anything that must persist. |
| A-8 | Credential proxy | The agent sends requests without credentials. A proxy outside its environment adds them. |
| A-9 | Auto mode | Classifiers review risky actions and block dangerous ones, but the user still decides the important ones. |
| A-10 | Deferred tool calls | A hook defers a call, the run ends, and the session is saved mid-call. The user answers, for example on an interactive card. The answer arrives as an inbox event that resumes the session. The worker is never blocked. |
| A-11 | Outbox | Deliver outcomes, not step-by-step progress. A run ends in one of three ways: send, nothing, or a deferred request. An outbox table plus a dispatcher handles pacing and error recovery. Start quiet and tune volume with evals. |

## 2. Harvest decisions and where each lands

Decisions: **Keep** means adopted as is. **Adapt** means adopted with ASDI-specific changes. **Reject** means not adopted; see §4.

| # | Decision | ASDI home in REV K | Spec |
|---|---|---|---|
| A-1 | **Keep.** It names what ASDI's loops already do. | Design §03 loops L0–L4; Stack §01 "Archon + sweeps, state in Postgres" | Context, FR-019 |
| A-2 | **Adapt.** The handler is the 60 s poller and never an HTTP endpoint. Each event is keyed by its source ID, for example (repo, PR, head SHA). | D-8; Guide §4 `events/` seam; Stack §02 "Poller reconciles PRs, pushes, review comments and new commits on main every 60 s"; Guide §16 `events/ source interface, poller/, audit log` | FR-001, FR-002, FR-010 |
| A-3 | **Adapt.** "Acknowledge fast" does not apply, because nothing calls in. One worker per inbox becomes one active handling per **subject**. For mid-run events: a new PR head **interrupts**, because REV K already says a new head invalidates evidence. Allowlisted comments are **queued and batched**. Other comments are stored as data. | Guide §9.4 "A new head commit invalidates earlier evidence and verdicts"; Guide §10.4 + DD-37 allowlisted resumers; Guide §13.3 Phase 4 exit "With GitHub unreachable, no state is lost" | FR-004 to FR-009 |
| A-4 | **Adapt.** Keep follow-ups and schedules, the separate store, and "a timer only writes an event". Use REV K's **hourly idempotent sweep**, not a durable execution engine. Add coalescing of missed schedule occurrences. | Stack §01 "Timers are due-dates in Postgres plus hourly idempotent sweeps"; Stack §04 "Timers are hourly sweeps, not durable workflows" and "Missed sweep … idempotent catch-up; overdue items in the digest"; Design §05 72 h / 14 d; `config/defaults.yaml` | FR-012 to FR-017 |
| A-5 | **Adapt.** Map the four memory kinds onto ASDI artifacts (table below). Memory lives off the run container. Agent-written memory is **data**, not instruction. | Guide §11.3 HANDOFF.md + checkpoint (N-12); Guide §13.2 `CORRECTIONS.md` stand-in; Guide §3.3 requests and `DECISIONS.tsv`; Guide §10.4 untrusted-text boundary (N-21) | FR-018 to FR-024 |
| A-6 | **Adapt.** Dreaming becomes the weekly curation input to the compounding ladder and rule retirement. It proposes and never applies. | Design §04 compounding bot; Guide §11.1 (N-10), "retirement candidate in the weekly system loop"; Guide §13.4 P2-6 | FR-032 |
| A-7 | **Keep as a constraint on the plan.** Lean always-loaded memory with a budget. Caching is an implementation choice. | Design §02 requests ("AGENTS.md; CLAUDE.md is a one-line import"); Stack §01 vllm-mlx local models | FR-023, Assumptions |
| A-8 | **Keep. Already REV K.** | Design §02 hard rule 4 "Tokens, the model key included, are injected at egress"; Guide §5 egress proxy; spike S-12 | (none needed; hard rule) |
| A-9 | **Reject as authority.** Classifiers may advise a run but never replace a hard rule, the class check or the verifier. | C-5; Design §02 hard rules; Guide §9.1 class check | Out of Scope |
| A-10 | **Adapt.** Keep "end the handling, save state, the answer comes back as an event, the worker is not blocked". Replace "resume the saved session" with a **fresh session plus handoff**. Replace interactive cards with REV K's allowed channels: allowlisted PR comment, board, `exposure` CLI. | Design §09 five touchpoints; Design §04 "ESCALATION decisions only after a failed reset"; Guide §3.3 "Do not wait on the human for reversible work"; Stack §00 Archon "never uses interactive approval nodes"; DD-17 exposure CLI | FR-025, FR-027 |
| A-11 | **Adapt.** Keep the three-way ending, outcome-level messages, a durable outbox and "start quiet". Volume is paired with a missed-escalation countermeasure, per REV K §10. | DD-15 notification channel (Pass 1: log file; full: "Push channel, capped queue", Guide §13.2); Design §04 "queue ≤ K"; Design §05 daily digest; Guide §13.3 Phase 6 weekly report | FR-025, FR-026, FR-028 to FR-031 |

### 2.1 Memory kinds mapped to ASDI artifacts

| Article memory kind | ASDI artifact | Who may write | Loaded |
|---|---|---|---|
| User instructions | Run contract (Design §07) + product `AGENTS.md` (Guide §3.3) | Owner, or a reviewed PR with skill eval (N-11) | Every session |
| User notes | Learned corrections: `CORRECTIONS.md` in Pass 1, `.asdi/rules.yaml` in Pass 2 (Guide §6.5, §11.1) | ASDI (compounding), owner | Index every session; detail on demand |
| Past messages | A record of what the owner was told: subject, state, time. **(new)** | ASDI outbox | By the outbox for dedup; summary into sessions on that subject |
| Task progress | `HANDOFF.md` + checkpoint `{id, branch, commit, handoff_path, turns_used, spend_used, minutes_used}` (Guide §11.3); `ASSUMPTIONS.md`, `DECISIONS.tsv` (Guide §3.3) | Agent: **data only** (N-21) | The subject's own progress, every session on that subject |

Pointers, not copies: board tasks, PRs, evidence manifests and audit events stay in their own systems (Guide §8, §18). Memory cites their IDs.

## 3. Pass placement

This follows Guide §13. The pass order is `0 → 1 → 3 → 4 → 7 → first light → 2 → 5 → 9 → full loop → 6 → 8 → 10 → deploy gate`.

| Spec area | Pass 1 (thin) | Lands in | Pass 2 / full |
|---|---|---|---|
| Inbox: FR-001 to FR-011 | Poller writes events to Archon's database; dedup by source ID; one handling per subject; staleness alert | **Phase 4** (Guide §13.3: "poller behind `events/` … poller health alert") | None; the inbox has no Pass 2 change |
| Timers: FR-012 to FR-017 | Due dates plus an hourly sweep for the 72 h window, flag expiry, daily triage and the weekly report | **Phases 9, 8, 6** | Experiment expiry with GrowthBook readouts (P2-11); drift sweep (P2-8) |
| Memory: FR-018 to FR-024 | Hand-written contract; `CORRECTIONS.md`; reset = kill and re-run with a revised contract (Guide §13.2) | **Phase 5** | HANDOFF and checkpoint with budget carry-over (**P2-7**, N-12) |
| Decisions: FR-025, FR-027 | Allowlisted PR comment resumes; `exposure` CLI | **Phases 4, 8** | Board approvals, if D-9 picks Paperclip |
| Outbox: FR-026, FR-028 to FR-031 | Notifications appended to a log file (DD-15 stand-in); daily digest; weekly report | **Phase 6** | Push channel, capped queue (Guide §13.2 "full version") |
| Curation: FR-032 | None | None | **P2-6** |
| Audit: FR-033 | Emit whichever events the parts produce (Guide §18) | **Phase 4 onward** | Same |

Nothing here moves a Pass 2 item into Pass 1, so the lifecycle-first rule (Design §12, Guide §13.1) holds.

## 4. Conflicts and rejections

Each item is resolved in REV K's favour unless it says *needs owner*.

| ID | Article says | REV K says | Resolution |
|---|---|---|---|
| X-1 | The handler is usually an HTTP endpoint fed by webhooks; acknowledge quickly | C-1 "No Actions, no webhooks"; D-8 local poller; Stack §02 "nothing calls in" | The poller is the only handler. "Acknowledge fast" is dropped. **Resolved.** |
| X-2 | Timers can run on a durable execution engine | Stack §04 "Timers are hourly sweeps, not durable workflows"; archived REV H/G also said "Do not introduce a separate durable workflow engine" | Hourly sweep only. Timer precision is 60 min (FR-013). **Resolved.** |
| X-3 | Auto-mode classifiers gate risky actions | C-5; hard rules are platform-enforced (Design §02) | Advisory only, never authority (Out of Scope). **Resolved.** |
| X-4 | An event that continues earlier work resumes the existing session | Design §01 "Fresh eyes beat re-reading … reset to brief v2 … fresh session"; Guide §11.3 "resume starts a fresh session" | Always a fresh session plus memory (FR-019). **Resolved.** |
| X-5 | Interactive approval cards (MCP Apps) inside the session | Stack §00 Archon "never uses interactive approval nodes"; DD-37 allowlisted comments; DD-17 exposure CLI | Answers come only through allowed channels (FR-027). **Resolved.** |
| X-6 | (Not from the article.) On 2026-11-18 a hosted, hourly Claude scheduled task was set up to review new PRs on `simbiclaw/asdi`. | Guide §3.4 excludes "Cloud agent runners or hosted automation" (C-1). It does not violate D-8, because it polls outward, but it is a loop that does not run locally. | **Needs owner.** Treat it as a stopgap outside ASDI, and retire it when Phase 4's local review pass is live. Or retire it now. It never posts `ci` or `asdi/policy`, so it cannot affect a gate. |
| X-7 | Inbox per user | One owner; parallelism is limited per subject and by the WIP limit of 3 (`config/defaults.yaml`) | Per-subject single handling (FR-004). **Resolved.** |
| X-8 | User instructions are a memory file the agent loads every run | Instructions are `AGENTS.md` plus the run contract. Text changes need `asdi/skill-eval` (Guide §11.1 layer 4, §11.2) | Agents cannot write instructions (FR-021). **Resolved.** |
| X-9 | (Spec addition.) FR-033 needs audit events `event.recorded`, `event.deduplicated`, `event.failed`, `timer.fired`, `handling.ended`, `decision.requested`, `decision.answered`, `notification.sent` | Guide §18 is the event list; "The handbook defines no event list of its own and defers to this one." | **Needs owner.** Adding names to Guide §18 changes an authority document. Until approved, emit them only under an `x-` prefix, or record `SPEC_CONFLICT` per `reference/AUTHORITY.md`. |
| X-10 | (Spec addition.) A judgment-queue limit K = 5 (FR-031) | Design §04 "queue ≤ K" and §11 "Notification queue at K" never give K a value | **Needs owner** as a register row (DD-45 below). The default carries no weight at the gate (Guide §4 rule 3). |

## 5. Proposed register rows

These follow Guide §4: each gets a seam and a provisional default. "Never resolve a deferred decision, by choice or by code that only works one way." Numbering continues after DD-38. Add them to `DECISIONS.md` only once accepted.

| ID | Decision | Provisional default | Seam |
|---|---|---|---|
| DD-39 | Where events are stored, and the subject key | Table in Archon's Postgres; key = (source, source ID); subject = PR, task, defect cluster or experiment | `events/` source interface |
| DD-40 | No-progress lease for a non-run handling | 15 min | `config/defaults.yaml` `handling_lease_seconds: 900` |
| DD-41 | Attempts before an event is marked failed | 3 | `config/defaults.yaml` `event_max_attempts: 3` |
| DD-42 | Missed occurrences of a schedule | Coalesce into one catch-up event | Sweep config |
| DD-43 | Memory store and always-loaded budget | Evidence-store volume on `ops` (DD-19), scrubbed (DD-29); 8,000 tokens | `memory/` interface; `config/defaults.yaml` `memory_boot_tokens: 8000` |
| DD-44 | Notification urgency list and dedup window | Immediate list as FR-026; 24 h dedup | `ops/` notify adapter (DD-15) |
| DD-45 | Judgment-queue limit K | 5 | `config/defaults.yaml` `judgment_queue_limit: 5` |
| DD-46 | Decision-request reminder | One reminder at 24 h, then daily digest; never auto-resolve | Sweep config |
| DD-47 | GitHub event handling start target | 120 s (two poll cycles) | `config/defaults.yaml` |

`memory/` is not in the Guide §16 layout. Either the plan puts memory under `evidence/` and `archon/`, or the layout gains a directory. That is a plan-level choice, listed here so it is not made silently.

## 6. Where the article confirms REV K

The article reached several REV K choices independently. Nothing below needs to change, but it gives these choices outside support:

- A credential proxy outside the agent's environment matches hard rule 4 and the egress proxy.
- "The inbox is the source of truth, and a new worker can retry" matches the Stack §02 test "if GitHub is unreachable, no loop crashes or loses state".
- "A timer never starts a run directly; it writes an event" matches due dates swept into pipelines.
- "Store only what the agent cannot look up again" matches pointers to the evidence store and board (Guide §8).
- "Start quiet and let the agent earn attention" matches TRM: autonomy is earned on the record (Design §07). It also matches the paired metrics (Design §10).
- "Deferred requests don't block the worker" matches "Do not wait on the human for reversible work" (Guide §3.3).

Not used: the article's cost figures for model generations. They do not bear on ASDI's design and are not repeated here.
