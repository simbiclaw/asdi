#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
    re.compile(r"https?://(?!127\.0\.0\.1|localhost)[^\s\"')]+"),
]
SCANNED_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".txt"}


def main() -> int:
    findings: list[str] = []
    scanned = 0
    for directory in ("src", "verify"):
        base = ROOT / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                continue
            if path.name == "verify" or "__pycache__" in path.parts:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), start=1):
                for pattern in PATTERNS:
                    if pattern.search(line):
                        findings.append(f"{path.relative_to(ROOT)}:{number}: {pattern.pattern}")
    if findings:
        for finding in findings:
            print(f"SECRET: {finding}", file=sys.stderr)
        return 1
    print(f"secret-scan: clean ({scanned} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
