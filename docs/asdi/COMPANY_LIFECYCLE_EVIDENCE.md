# ASDI Company Lifecycle Evidence

**Date:** 2026-11-15  
**Result:** **Local integrated lifecycle PASS** — not production autonomy and not strict ASDI-012 acceptance

## Command

```sh
PYTHONPATH=src:. python3 scripts/run_company_scenarios.py
```

Latest evidence root:  
`/private/var/folders/yf/nn0v06c92fv8yc2z36cqqjw80000gn/T/asdi-company-20261115-045849-uwu6sn7n`

Report: `company-scenario-report.json`

## Product lifecycle — PASS

| Stage | Evidence |
|---|---|
| Admission/brief | Mission `mission_3a42731f-ef7f-46e5-a196-699ac418d1ef` |
| Decomposition/execution | six lifecycle tasks created; fixture implementation process exit 0 |
| Self verification | artifact `--self-check` exit 0 |
| Independent checks | correctness, security, and acceptance processes all passed |
| Classification | `T0_human`; autonomous merge false |
| Governed local merge | local commit `7b4617be0cb6f2cd849abc7043327d9a34906e31`; remote merge false |
| Deployment | release `..._31226dd9`; atomic local current release |
| Default flag | feature ran with `variant=off` before exposure |
| Controlled exposure | flag enabled with recorded owner decision reference |
| Experiment verdict | 4/4 passed; `keep_for_human_review` |

## Self-healing lifecycle — PASS

| Stage | Evidence |
|---|---|
| Defective mission | `mission_19635a73-7d38-49a4-aaa8-0498892b2599` |
| Local deployment | release `..._ed86d8da` |
| Production detection | load probe failed; exit code 1; `healthy=false` |
| Defect/triage | `defect_c183bf0b-49d2-4fb0-95fa-cf10b1d18753`; bounded repair decision |
| Repair mission | `mission_3d327be7-de26-4f48-997a-ffc0f2cc88cc` |
| Repair checks | correctness/security/acceptance all passed |
| Governed local merge | local commit `6e972f0b01205edfde234591743c5197addaf2a4`; remote merge false |
| Repair deployment | release `..._8dd65207` |
| Production verification | 4/4 local traffic outcomes passed |
| Closure | `closed_verified`; reopened false |

The run also produced a durable learning ledger containing deployment, flag change, experiment verdict, defect detection, production verification, and defect closure events.

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

Result: **51 tests, OK, 3 expected AF_UNIX skips.**

## Truthful status

| Area | Status |
|---|---|
| Integrated company loop | Implemented and verified locally |
| Agent execution | Verified with deterministic fixture agents |
| Live command-agent compatibility | Implemented and tested; live vendor CLI not invoked |
| Mission guardrails | Local turns/spend/wall clock implemented and verified |
| Work-item index and bounded reset | Implemented and verified locally |
| Durable self-healing CLI | Implemented and verified locally |
| Local deployment/rollback/flags | Implemented and verified |
| Remote merge / production deployment | Not implemented; intentionally disabled |
| Live model adapter in company loop | Local Qwen live implementation/deployment verified without exposure |
| Strict container egress | Not accepted |
| Turn/spend/wall-clock guardrails | Implemented locally; production acceptance remains unfinished |
| TRM and paired metrics | Implemented and verified locally; production promotion remains disabled |

This demonstrates a working local engineering company loop. It does not yet demonstrate production autonomy.
