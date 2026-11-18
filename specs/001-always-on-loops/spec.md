# Feature Specification: Always-on loop primitives for ASDI

**Feature**: `001-always-on-loops`
**Created**: 2026-11-18
**Status**: Draft (proposal; not part of the REV K authority set)
**Input**: User description: "harvest the useful components and design from https://claude.com/resources/articles/building-always-on-agents, and then adapt them to fit ASDI. write a standalone spec, and cross-reference with REV K"

**Companion files**:

- [`crosswalk.md`](crosswalk.md) maps each harvested component to REV K, records what was rejected and why, and lists conflicts and proposed register rows.
- [`checklists/requirements.md`](checklists/requirements.md) is the qualification result.

**Standing.** [`reference/AUTHORITY.md`](../../reference/AUTHORITY.md) names four REV K documents as authoritative, and this spec is not one of them. Where it disagrees with them, REV K wins, and the disagreement is listed in `crosswalk.md` §4 rather than resolved here. Every requirement below either restates a REV K behaviour in testable form, or adds behaviour REV K leaves unstated. Each addition is marked **(new)**.

## Context

ASDI should feel always on to its owner: work moves forward while the owner is away, and the owner is contacted only for decisions only they can make. In reality, every part of ASDI that uses a model sleeps between short bursts of work. That covers the build runs, the review pass, the fix loop, triage and the sweeps. Each burst starts from some event: a new PR head, a comment, a production error, or a due date. It does its work, records what happened, and stops.

The source article breaks this cycle into five primitives: an **event inbox**, **timers**, **memory**, **permissions** and an **outbox**. REV K already has most of the pieces: the 60-second poller (D-8), due dates with hourly idempotent sweeps, the handoff note (N-12), the egress proxy (hard rule 4), notifications (DD-15). But REV K never states them as one cycle with shared guarantees. This spec states those guarantees: what the owner and the loops can rely on, whichever component implements them.

Terms:

- **Event**: something ASDI must react to, for example a new PR head, an allowlisted comment, a production error cluster, a due timer or an owner's answer.
- **Subject**: the thing an event is about: one PR, one board task, one defect cluster or one experiment.
- **Handling**: one burst of work in response to one or more events on one subject. A build run, a gate evaluation and a triage pass are each a handling.
- **Owner**: the human named in `allowed_comment_resumers`. ASDI has exactly one.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Nothing the owner or GitHub does is lost or handled twice (Priority: P1)

The owner pushes a commit, opens a PR, or leaves a comment, and walks away. Every one of those reaches the right loop exactly once. That holds even if a loop crashes mid-handling, GitHub is unreachable for a while, or several events land at once. The owner never has to re-push or re-comment to "wake ASDI up".

**Why this priority**: Every other loop depends on events arriving. A lost event stalls merges silently. A duplicated event double-posts statuses or starts competing runs. This is the base of the cycle and is already a REV K Phase 4 exit test ("With GitHub unreachable, no state is lost and the poller catches up").

**Independent test**: Seed 100 GitHub events across 10 subjects. Kill the handling process at random points, and cut GitHub access for 10 minutes. Then count completed handlings per event.

**Acceptance scenarios**:

1. **Given** GitHub is reachable, **When** a new PR head appears, **Then** ASDI records exactly one event for that PR head, and handling starts within 120 seconds. *(FR-001, FR-002, FR-003)*
2. **Given** the poller has already recorded a PR head, **When** the same head is seen on a later poll, **Then** no second event is recorded. *(FR-002)*
3. **Given** a handling is in progress for PR #N, **When** another event for PR #N arrives, **Then** no second handling for PR #N starts in parallel. *(FR-004)*
4. **Given** a gate evaluation is running on head A, **When** head B is pushed to the same PR, **Then** the evaluation on A is abandoned, nothing it produced counts, and a new evaluation on B starts. *(FR-005)*
5. **Given** a build run is in progress, **When** the owner posts three comments within a few minutes, **Then** all three are delivered together to the next resume of that work, as one batch. *(FR-006)*
6. **Given** a comment from a login that is not on the allowlist, **When** it is recorded, **Then** it is stored as data and starts no work. *(FR-007)*
7. **Given** the process handling an event dies, **When** 15 minutes pass with no recorded progress, **Then** the event returns to pending and a new handling picks it up. *(FR-008)*
8. **Given** an event has failed handling 3 times in total, **When** it fails again, **Then** it is marked failed, it is not retried automatically, and it appears in the next daily digest. *(FR-009, FR-028)*
9. **Given** GitHub has been unreachable for 10 minutes, **When** it becomes reachable again, **Then** every change that happened during the outage is recorded within 2 poll cycles, with no duplicates. *(FR-010, FR-002)*
10. **Given** no poll has succeeded for 300 seconds, **When** the staleness check runs, **Then** the owner receives one immediate notification. *(FR-011, FR-026)*
11. **Given** the 100-event test has finished, **When** the audit trail is read, **Then** every event shows when it was recorded, any duplicates that were dropped, and how it ended (done or failed). Every timer firing, handling ending, decision request, answer and notification from the run also appears. *(FR-033)*

---

### User Story 2 - Due dates and schedules fire on their own (Priority: P2)

Some promises ASDI makes come due later. Examples: "close this defect if the error stays gone for 72 hours", "kill this experiment if it has no verdict in 14 days", "run triage daily", "send the weekly report". These happen without anyone asking, even if ASDI was down when they came due.

**Why this priority**: This is what makes ASDI proactive rather than reactive. The self-healing loop's close-or-reopen step, experiment expiry, flag cleanup, evidence retention and the weekly L4 loop all depend on it.

**Independent test**: Register one follow-up and one daily schedule. Stop the sweep for 6 hours across both due times, restart it, and count the events produced.

**Acceptance scenarios**:

1. **Given** a follow-up is due at time T, **When** the sweep runs, **Then** an event is recorded no later than T + 60 minutes, and the follow-up is marked done. *(FR-012, FR-013)*
2. **Given** a daily schedule, **When** its occurrence fires, **Then** exactly one event is recorded and the schedule moves to its next occurrence. *(FR-013)*
3. **Given** a due timer, **When** it fires, **Then** it records an event and starts no work directly. *(FR-014)*
4. **Given** the sweep was down for 6 hours and missed one follow-up and 6 hourly occurrences of a schedule, **When** it restarts, **Then** it records exactly one event for the follow-up and exactly one catch-up event for the schedule, and the daily digest lists both as overdue. *(FR-015, FR-028)*
5. **Given** a defect fix has been deployed, **When** the 72-hour verification window ends, **Then** the defect is closed if the error stayed absent, and reopened with a strike otherwise. *(FR-016)*
6. **Given** a handling sets its own follow-up, for example "re-check this PR's review in 24 hours", **When** that follow-up comes due, **Then** an event for that subject is recorded. *(FR-017)*

---

### User Story 3 - Fresh sessions continue the work without asking again (Priority: P3)

Each handling starts in a fresh model session. ASDI uses fresh sessions on purpose: after two strikes it resets rather than piling on corrections, and preempted work resumes in a new session. A fresh session still knows the standing instructions, where the task got to, what has already been reported, and which corrections have been learned. Saved memory never becomes a way to slip instructions past the gates.

**Why this priority**: Without continuity, resets lose lessons and the owner gets asked the same question twice. Without the boundary, a planted note in memory could steer the next run. It ranks below events and timers because Pass 1 can survive on a hand-written contract and a kill-and-requeue.

**Independent test**: Pause a run mid-task, resume it in a new session, and check that it continues from the recorded next step without repeating completed work or asking a question already answered. Separately, plant an instruction in a task-progress note, and check that no gate result changes.

**Acceptance scenarios**:

1. **Given** a run is paused or preempted, **When** it resumes, **Then** the new session starts from the recorded progress, and its turn, spend and time use carry over. *(FR-018, FR-019)*
2. **Given** a task has had two strikes, **When** it is reset, **Then** the new session gets the revised contract and the recorded lessons, not the earlier transcript. *(FR-019)*
3. **Given** a task-progress note contains text phrased as an instruction, **When** a later session or a reviewer reads it, **Then** it is presented as data, and no gate result or class decision changes. *(FR-020)*
4. **Given** the standing instructions, **When** a run or handling tries to change them directly, **Then** the change is refused. Instructions change only through a reviewed PR. *(FR-021)*
5. **Given** information that the board, GitHub or the evidence store already holds, **When** memory refers to it, **Then** memory holds a pointer, not a copy. *(FR-022)*
6. **Given** the always-loaded memory exceeds its size budget, **When** a session starts, **Then** only the index is loaded in full, and detail files are read on demand. *(FR-023)*
7. **Given** a task closed 30 days ago, **When** the retention sweep runs, **Then** its progress memory is archived and leaves the active set. *(FR-024)*

---

### User Story 4 - Asking the owner without stopping everything (Priority: P4)

Some work reaches a point that is the owner's call: an escalation after a failed reset, a judgment-class merge, an exposure ramp or an irreversible action. ASDI asks once, clearly. It saves where the work stopped, and carries on with other work while it waits. When the owner answers through an allowed channel, the work resumes from where it stopped.

**Why this priority**: This matches REV K §09 ("agents only propose; you decide"; "do not wait on the human for reversible work"). Without it, a pending question either blocks the pipeline or gets answered by default. Both are unacceptable for irreversible actions.

**Independent test**: Make one task raise a decision request. Admit two other tasks, check they progress while the request is pending, then answer it and check the first task resumes.

**Acceptance scenarios**:

1. **Given** a handling needs an owner decision, **When** it raises the request, **Then** the handling ends, its progress is saved, and the owner receives one request that states the question and the options. *(FR-025, FR-026)*
2. **Given** a decision request is pending, **When** other admitted tasks are within the WIP limit, **Then** they keep running. *(FR-025)*
3. **Given** the owner answers through an allowed channel, **When** the answer is recorded, **Then** it becomes an event that resumes the waiting work in a fresh session with the answer included. *(FR-027, FR-019)*
4. **Given** a decision request has been pending for 24 hours, **When** the reminder comes due, **Then** the owner receives one reminder, and the request then appears in every daily digest until it is answered. *(FR-027, FR-028)*
5. **Given** a pending request concerns an irreversible action, **When** any amount of time passes without an answer, **Then** the action is never taken by default. *(FR-027)*

---

### User Story 5 - Few, deduplicated, outcome-level messages (Priority: P5)

The owner hears about outcomes and decisions, not step-by-step progress. Urgent things arrive at once; everything else waits for the daily digest or the weekly report. The owner is never told the same thing twice.

**Why this priority**: REV K's failure modes include "coverage gate floods you with judgment PRs" and "ratification moves to the exposure gate". Notification volume is part of keeping review real. The source article's advice is the same: start quiet and let the agent earn attention.

**Independent test**: Replay one week of recorded loop outcomes through the outbox, then count immediate messages, duplicates and missed escalations.

**Acceptance scenarios**:

1. **Given** a handling ends, **When** its ending is recorded, **Then** it ended in exactly one of: an outcome record, nothing to report, or a decision request. *(FR-025)*
2. **Given** a production rollback, a poller stall, or a judgment-class PR ready for review, **When** it occurs, **Then** the owner is notified immediately. *(FR-026)*
3. **Given** the owner was notified about subject S in state X, **When** S is reported in state X again within 24 hours, **Then** no second notification is sent. *(FR-029)*
4. **Given** delivery of a notification fails, **When** the channel recovers, **Then** the notification is delivered then, and is not lost. *(FR-030)*
5. **Given** the number of judgment PRs waiting for the owner reaches the queue limit, **When** a new task would be admitted, **Then** admission pauses until the queue drops below the limit. *(FR-031)*

---

### User Story 6 - Memory stays accurate over months (Priority: P6)

Once a week, a curation pass reviews recent run records and memory. It proposes removing stale entries and promoting repeated patterns. It never edits standing instructions by itself.

**Why this priority**: This is the article's "dreaming". In ASDI it is the input to the compounding ladder and rule retirement, which are Pass 2 work (P2-6). It is useful, but nothing in Pass 1 depends on it.

**Independent test**: Seed memory with one stale entry and one correction that appears 3 times across runs, run curation, and check its proposals.

**Acceptance scenarios**:

1. **Given** a correction recorded in 2 or more runs, **When** weekly curation runs, **Then** it proposes the correction as a candidate for the compounding ladder. *(FR-032)*
2. **Given** a memory entry that points to a subject that no longer exists, **When** curation runs, **Then** it proposes removing the entry. *(FR-032)*
3. **Given** any curation output that would change standing instructions, **When** it is produced, **Then** it is opened as a PR, never applied directly. *(FR-032, FR-021)*

### Edge Cases

- **Events for a subject that disappears**, for example a PR closed while its gate is pending: the pending events are marked done with reason "subject closed", and no handling starts.
- **A burst of events** across more subjects than the WIP limit allows: the extra subjects wait as pending, in arrival order. Gate and post-merge events are not limited by WIP; only build runs are.
- **A clock jump or host reboot during a sweep**: firing is idempotent per timer occurrence, so a repeated sweep produces no second event.
- **An owner answer that arrives after the task was dropped**: it is recorded, and the owner is told in the next digest that the task is no longer active.
- **An answer from a login that is not the owner's**: it is stored as data and resumes nothing (FR-007).
- **Memory that fails to load**: the handling does not start. The event returns to pending and counts as a failed attempt.
- **The notification channel down for a long time**: messages queue without limit on age, and the outage itself is reported once the channel returns.

## Requirements *(mandatory)*

### Functional Requirements

**Event inbox**

- **FR-001**: The system MUST record every relevant GitHub change as an event before any work on it begins. That means new PRs, new PR heads, comments, and new commits on `main`. Events come only from ASDI polling outward; nothing outside calls in.
- **FR-002**: The system MUST record each event at most once, identified by its source and the source's own identifier. For a PR head, that is the repository, PR number and commit.
- **FR-003**: The system MUST start handling a GitHub event within 120 seconds of the change becoming visible on GitHub, while GitHub is reachable.
- **FR-004**: The system MUST allow at most one active handling per subject at a time. **(new)**
- **FR-005**: When a new PR head arrives during a gate evaluation of an older head, the system MUST abandon the older evaluation, discard its results, and evaluate the new head.
- **FR-006**: The system MUST hold allowlisted comments that arrive during a handling, and deliver all of them together to the next handling of that subject. **(new)**
- **FR-007**: The system MUST record comments from logins that are not allowlisted as data only, and MUST NOT start or resume work because of them.
- **FR-008**: The system MUST return an in-progress event to pending when its handling records no progress for 15 minutes. **(new)** For build runs, the run's own guardrails apply instead.
- **FR-009**: The system MUST stop retrying an event after 3 failed attempts, mark it failed, and report it. **(new)**
- **FR-010**: After an outage of GitHub or of ASDI itself, the system MUST reconcile against the current state on GitHub and record every missed change within 2 poll cycles of recovery. Each change is recorded exactly once.
- **FR-011**: The system MUST alert the owner when no poll has succeeded for 300 seconds.

**Timers**

- **FR-012**: The system MUST support two kinds of timer: follow-ups (one-off due dates) and schedules (recurring). Both must survive restarts.
- **FR-013**: The system MUST fire each due timer occurrence within 60 minutes of its due time. A fired follow-up is marked done; a schedule moves to its next occurrence.
- **FR-014**: A firing timer MUST only record an event. It MUST NOT start work directly.
- **FR-015**: After downtime, the system MUST fire each missed follow-up once. It MUST coalesce each schedule's missed occurrences into one catch-up event. **(new: coalescing)**
- **FR-016**: The system MUST provide, at minimum, these timers, with REV K's values:
  - Production verification: 72 hours after a fix deploys.
  - Experiment expiry: 14 days.
  - Flag expiry.
  - Waiver expiry.
  - Evidence retention: 30 days after PR close.
  - Daily triage.
  - Daily digest.
  - Weekly report and system loop.
  - Weekly drift sweep.
  - Nightly board-to-pipeline reconciliation.
- **FR-017**: A handling MUST be able to set a follow-up on its own subject. **(new)**

**Memory**

- **FR-018**: The system MUST keep four kinds of memory, and all of them MUST outlive any run container:
  - Standing instructions.
  - Task progress, per task.
  - A record of what the owner has been told.
  - Learned corrections.
- **FR-019**: Every handling MUST start in a fresh session, loaded with the standing instructions, its subject's task progress, and any new events. Resumes MUST carry over guardrail use. Resets MUST use the revised contract and recorded lessons, never an earlier transcript.
- **FR-020**: The system MUST treat task progress, past outputs and learned corrections written by agents as agent-authored data. Such content MUST NOT change a gate result, class decision or verifier outcome.
- **FR-021**: Runs and handlings MUST NOT change standing instructions directly. Changes go through a reviewed PR, with the skill evaluation REV K requires for instruction changes.
- **FR-022**: Memory MUST store a pointer, not a copy, for anything held by the board, GitHub or the evidence store. **(new)**
- **FR-023**: Memory loaded in full at every session start MUST stay within 8,000 tokens. Beyond that, an index is loaded and detail is read on demand. **(new)**
- **FR-024**: The system MUST scrub memory content before storing it, using the same rules as evidence. It MUST archive a task's progress memory 30 days after the task closes.

**Decisions and outbox**

- **FR-025**: Every handling MUST end in exactly one recorded way:
  - **An outcome**: a status, PR, issue, close or reopen.
  - **Nothing to report.**
  - **A decision request.** Raising one ends the handling and saves progress, and other tasks continue. **(new: three-way ending)**
- **FR-026**: The system MUST notify the owner immediately for these, and nothing else:
  - Decision requests.
  - Judgment-class PRs ready for review.
  - Production rollbacks.
  - Poller staleness.
  - External probe failure.

  Everything else MUST go into the daily digest or the weekly report.
- **FR-027**: An owner's answer through an allowed channel MUST become an event that resumes the waiting work. Allowed channels are an allowlisted PR comment, the board, or the exposure command. A request unanswered after 24 hours MUST trigger one reminder. A pending request MUST NOT be resolved by default, ever.
- **FR-028**: The daily digest MUST list:
  - Failed events.
  - Overdue timers.
  - Pending decision requests.
  - Answers that arrived for dropped tasks.
- **FR-029**: The system MUST NOT notify the owner twice about the same subject in the same state within 24 hours. **(new)**
- **FR-030**: The system MUST hold undelivered notifications until they are delivered, and MUST NOT drop any.
- **FR-031**: The system MUST pause admission of new tasks while the judgment-review queue is at its limit. The default limit is 5 PRs.

**Curation**

- **FR-032**: Once a week, the system MUST review run records and memory and propose two kinds of change: corrections seen in 2 or more runs, as candidates for the compounding ladder; and entries pointing at subjects that no longer exist, for removal. Any proposed change to standing instructions MUST be opened as a PR. **(new; Pass 2)**

**Audit**

- **FR-033**: The system MUST record each of these in the append-only audit trail:
  - Event recorded, deduplicated, completed or failed.
  - Timer fired.
  - Handling ending.
  - Decision requested or answered.
  - Notification sent.

### Key Entities

- **Event**: something to react to. It has a source, the source's identifier, a subject, a status (pending, in progress, done or failed), an attempt count and an arrival time.
- **Subject**: what events are about: a PR, board task, defect cluster or experiment. At most one active handling at a time.
- **Timer**: a follow-up or a schedule, with a due time, a subject and, for schedules, a recurrence.
- **Memory entry**: a standing instruction, task progress note, reported-message record or learned correction. Each is labelled by who wrote it: owner, ASDI or agent.
- **Decision request**: a question for the owner with its options, the subject it blocks, when it was raised, and its answer.
- **Notification**: a message to the owner, with its urgency (immediate, digest or weekly), subject, state and delivery status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the 100-event crash-and-outage test (Story 1), 0 events are lost and 0 events complete twice.
- **SC-002**: 95% of GitHub events begin handling within 2 minutes of appearing on GitHub, measured over one week of probation.
- **SC-003**: 100% of due timers fire within 60 minutes of their due time. After a 6-hour stop, every missed timer produces exactly one event within 60 minutes of restart.
- **SC-004**: In a seeded test of 20 paused-and-resumed and 10 reset tasks, the owner is asked 0 questions they had already answered on the same task.
- **SC-005**: A seeded instruction planted in memory, or in a comment that is not allowlisted, changes 0 gate outcomes across the seeded-injection suite.
- **SC-006**: While a decision request is pending, the other admitted tasks that are within the WIP limit continue, with 0 of them blocked.
- **SC-007**: During probation, the median is at most 3 immediate notifications per day, with 0 missed escalations in the seeded escalation test. This pairs a volume measure with a quality countermeasure, as REV K §10 requires.
- **SC-008**: 0 duplicate notifications for the same subject and state within 24 hours, over one week of probation.

## Scope *(mandatory)*

### Out of Scope

- Any inbound path into ASDI: webhooks, GitHub Actions, hosted relays or tunnels to the agent side (C-1, D-8).
- A separate durable workflow engine for timers. Timers stay as due dates swept hourly (Stack doc §04).
- Timer precision finer than 60 minutes. The 60-second poller is an event source, not a timer.
- Resuming an earlier session transcript. Continuity comes only from memory (FR-019).
- Automated risk classifiers that approve actions. They may advise a run, but they never replace a hard rule, class check or verifier result (C-5).
- Streaming step-by-step progress to the owner.
- More than one owner, or one inbox per user.
- Interactive approval cards inside chat tools. Answers come through allowed channels (FR-027).
- Replacing the review pass itself. The local REV K reviewer (`docs/asdi/PR_REVIEWER.md`) is one handler that uses these primitives.

## Assumptions

- REV K values are used where REV K gives one:
  - 60 s poll interval and 300 s staleness (`config/defaults.yaml`).
  - 72 h production verification.
  - 14-day experiment expiry.
  - 30-day evidence retention.
- New numbers are provisional defaults, and each is proposed as a register row in `crosswalk.md` §5:
  - 120 s handling start.
  - 15 min no-progress lease.
  - 3 attempts per event before it is marked failed.
  - 8,000-token always-loaded memory.
  - 24 h dedup window and reminder.
  - Judgment-queue limit of 5.
- The owner is the single login in `config/identities.yaml` `allowed_comment_resumers` (DD-37).
- Pass placement follows REV K: the inbox and timers are needed in Pass 1 (Phases 4, 6, 8, 9). Pause/resume memory and curation are Pass 2 (P2-7, P2-6). Pass 1 notifications are a log file (DD-15). See `crosswalk.md` §3.
- Prompt caching for API-hosted models is an implementation choice for the plan, not a requirement. Local models through vllm-mlx are the default.
