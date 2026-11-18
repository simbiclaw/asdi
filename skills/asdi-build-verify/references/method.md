# Methods, controls and safety

Read this before your first `run` or `negative` row.

## The three methods

**inspect.** Read files, config or API output and compare them with the requirement. Evidence is a path and line, or saved API output. Quote the line that decides it. Reading the builder's description of a file is not inspecting the file.

**run.** Execute something and look at what it does. Save the command and its output under `evidence/`. If a builder-supplied test script exists, you may run it, but read it first: a test that asserts nothing passes every time. Prefer the plainest command that shows the behaviour directly.

**negative.** Try the thing that must not be possible and expect to be refused. This is how the hard rules are checked, because "nothing bad happened" is only meaningful if something bad was attempted.

## Controls

A check that cannot fail tells you nothing. Many rows carry a control: a second observation showing the check reacts when it should.

- For a negative test, the control is the allowed case. If an agent-network container cannot reach prod, show that a prod-network container can. Otherwise the probe may simply be broken.
- For a run test, the control is a deliberately wrong input. If hashes match, alter a copy of one file and see the comparison fail.

Record `control: caught` when the control behaved as expected and `missed` when it did not. Record it whenever you ran one, on failing rows too; it is required only to support a pass. A pass whose control was missed is not a pass: record `fail`, since the build's check or yours cannot tell good from bad. If you could not run the control, the row is `blocked`.

## What each row needs

Rows list what they need. If it is absent, the row is `blocked`. Say exactly what was missing so the next run can supply it.

| Need | Means |
|---|---|
| `docker` | A Docker daemon you can use, with the ASDI Compose project available |
| `launcher` | A launcher that actually starts runs |
| `github` | The sandbox repository and its throwaway identities |
| `product` | The toy product repo with its `verify/` harness |
| `git` | The ASDI repo is a git repository with history |

Do not stand in for a missing part. If the launcher cannot start a run, do not reason about what it would do from its source and record `pass`. Reading the source can produce a `fail` (the code plainly never calls the verifier) but not a `pass` for a behavioural row.

The same goes for a simulated mode. If the launcher offers a local simulation, use it: a simulated run that ends green when it must end red is a real `fail`. A simulated run that behaves correctly supports nothing more than `blocked`, because the requirement is about real containers. Say in `observed` that the run was simulated.

So for a row whose need is absent: a counter-example in source or config gives `fail`; no counter-example gives `blocked`.

## Safety rules for negative tests

Negative tests attempt forbidden actions, so where you run them matters.

1. **Sandbox only.** GitHub tests use the sandbox repository and throwaway identities named in the ASDI config. Never the real product repo, never a real token.
2. **Local prod only.** Rollback and deploy tests run against the prototype's local `prod` network. If real users or real domains are attached, stop and record `blocked`.
3. **Scratch copies for anything that writes.** Running the builder's code, breaking a feature, weakening a proof or corrupting evidence happens in a copy outside the repo: `git archive HEAD | tar -x -C "$(mktemp -d)"`. Do not use `git worktree`, which writes into `.git`. Confirm the working tree is unchanged afterwards with `git status`.
4. **Clean up what you start.** Remove scratch containers, networks, branches and PRs you created. List in `notes` anything you could not remove.
5. **Nothing irreversible.** If a test would need a real secret, a paid action, or an external side effect, do not run it. Record `blocked`.
6. **Never print a secret.** If you find one, record its location and kind, not its value.

## Recipes for common live checks

Adapt names to the repo. These show the shape of a sound check.

**Network isolation (HR-3, P0-3, P7-4).** Start a scratch container on the `agent` network and try to open a connection to a service on `prod` by name and by IP. Expect failure. Control: the same connection from a scratch container on `prod` succeeds. Also try the Docker socket path and a host off the egress allowlist.

**Secrets in containers (HR-4, P1-7).** During a real run, list the environment and search the filesystem of the run and verifier containers for token shapes and for the names of the configured secrets. Control: plant a marker variable in a scratch container and confirm the same search finds it.

**Claim versus verifier (HR-2, P1-4).** Use a contract whose product check fails, with an agent that reports success (a stub agent is fine if the adapter allows one). The run must end red. Control: a passing check ends green.

**Base-branch proofs (C-5, P1-5).** On a scratch branch, change an existing proof or a static-gate command so it always passes, and break the feature. The run must still end red, because the verifier reads proofs from the base branch.

**Guardrails (HR-5, P1-6).** Set one limit very low and start a run that would exceed it. The launcher, not the agent, must stop it, and the record must say why. Repeat for each limit: turns or tokens, spend, minutes. One unenforced limit fails the row.

**Evidence integrity (P1-9).** After a run is torn down, recompute SHA-256 for each stored file and compare with the statement. Control: alter a copy of one file and see the mismatch reported.

**Merge authority (HR-1, P0-4).** In the sandbox, attempt a merge through the API with the agent token and with the status token. Both must be refused. Read the ruleset for the required statuses and the up-to-date-branch setting.

**Post-merge check (P4-5).** Merge a sandbox change that passes on its branch and fails on `main`. Expect a result with source `main` that is not a pass, an auto-revert PR, and no image build.

## Reading STATUS.md

`STATUS.md` is the builder's account. Use it to find the claimed phase and the list of exit tests said to pass. Do not copy its statuses. Read it after your own checks where you can, so it does not shape what you look for.

## Spec lookups

Rows cite their source, for example "Guide §13.3 Phase 1 exit" or "Design §02 rule 4". The Design and Stack docs are HTML and large; search them for the section number or a phrase from the row and read only that part. When a row and the spec disagree, the spec wins.
