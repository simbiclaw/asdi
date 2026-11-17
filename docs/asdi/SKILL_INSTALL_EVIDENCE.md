# ASDI Build Conformance skill installation

**Date:** 2026-11-17  
**Scope:** ASDI repository implementation/build slices only  
**Result:** Installed

## Source

* Archive: [`reference/asdi-build-conformance.zip`](../../reference/asdi-build-conformance.zip)
* SHA-256: `e0f144b2a2a403c8f946b1eff10c99f6bc875ff5391c9553baada771993bdcd7`
* Integrity: `unzip -t` passed

## Installed path

[`skills/asdi-build-conformance/SKILL.md`](../../skills/asdi-build-conformance/SKILL.md)

The archive contains only the skill folder and `SKILL.md`; no executable payload was installed.

## Scope

This is an ASDI-native conformance auditor for implementation work, infrastructure, launcher/verifier behavior, policies, evidence, deployment, and phase exit tests.

It is **not** the REV K toy-product `verify/SKILL.md` and does not produce H-1 product verification evidence.

## Project configuration

[`project.json`](../../skills/asdi-build-conformance/project.json) pins the four supplied REV K sources and records that the skill is read-only. It explicitly excludes toy-product runtime verification.
