# ASDI-010 Acceptance Verification

**Date:** 2026-11-13
**Scope:** Verification of committed ASDI-010 code and fixtures after ASDI-011 work began
**Result:** **PASS**

## Evidence sources inspected

- [`src/asdi/run_contract.py`](../../src/asdi/run_contract.py)
- [`fixtures/run_contracts/valid/`](../../fixtures/run_contracts/valid/) (2 files)
- [`fixtures/run_contracts/invalid/`](../../fixtures/run_contracts/invalid/) (12 files)
- [`tests/test_run_contract.py`](../../tests/test_run_contract.py)
- [`docs/asdi/GATE_010_EVIDENCE.md`](GATE_010_EVIDENCE.md)

No ASDI-010 implementation was rewritten during this verification.

## Acceptance mapping

| Criterion | Code/test evidence | Result |
|---|---|---|
| Five authored fields | Constants `AUTHORED_FIELDS`; required-field checks; builder arguments | Pass |
| Explicit empty constraints/out-of-scope | `empty_optional_lists.json`; `test_empty_optional_lists_are_explicit_and_valid` | Pass |
| Platform defaults and optional experiment reference | `build_run_contract`; `PLATFORM_DEFAULT_FIELDS`; central `RunContractConfig` | Pass |
| Types and required fields | 12 invalid fixtures; object/string/list/numeric validators | Pass |
| Command safety | `shell_command.json`, `unsafe_metacharacter.json`, `disallowed_executable.json`; argv and executable checks | Pass |
| Invalid budgets | `negative_budget.json`, `zero_wall_clock.json`; finite/positive/ceiling checks | Pass |
| Allowed output kind | `unsupported_output.json`; configured `pull_request`/`report`/`artifact` checks | Pass |
| Provenance | Valid provenance partition plus `bad_provenance.json` and `unknown_provenance_field.json` | Pass |
| Invalid contract cannot launch | `validate_run_contract` raises; ASDI-011 `create_run`/`start_runtime` both validate before launch | Pass |

## Executed verification

```sh
PYTHONPATH=src python3 -m unittest tests.test_run_contract -v
```

Result:

```text
Ran 11 tests in 0.581s
OK
```

The same suite's fixture CLI test verifies all 14 JSON fixtures through the CLI: 2 valid fixtures exit 0 and 12 invalid fixtures exit 2.

## Residual boundary

ASDI-010 proves contract validation only. Runtime execution, live guardrails, and sandbox isolation are not accepted here.
