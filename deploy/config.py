"""Read the REV K prod resource envelope without adding a YAML dependency."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIMITS_PATH = REPO_ROOT / "config" / "limits.yaml"


@dataclass(frozen=True)
class ProdLimits:
    cpus: str
    memory: str
    oom_score_adj: int

    def to_run_args(self) -> list[str]:
        return [
            "--cpus",
            self.cpus,
            "--memory",
            self.memory,
            "--oom-score-adj",
            str(self.oom_score_adj),
        ]


DEFAULT_PROD_LIMITS = ProdLimits(cpus="4", memory="8g", oom_score_adj=-500)


def load_prod_limits(path: str | Path | None = None) -> ProdLimits:
    if path is None:
        return DEFAULT_PROD_LIMITS
    limits_path = Path(path).resolve()
    if not limits_path.is_file():
        raise FileNotFoundError(f"limits file is missing: {limits_path}")
    lines = limits_path.read_text(encoding="utf-8").splitlines()
    prod_index = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"  prod:\s*", line)),
        None,
    )
    if prod_index is None:
        raise ValueError(f"limits file has no prod zone: {limits_path}")
    values: dict[str, str] = {}
    for line in lines[prod_index + 1 :]:
        if not line.strip():
            continue
        if not line.startswith("    "):
            break
        match = re.fullmatch(r"    (cpus|memory|oom_score_adj):\s*(.+?)\s*", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    if set(values) != {"cpus", "memory", "oom_score_adj"}:
        raise ValueError("prod limits must define cpus, memory and oom_score_adj")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", values["cpus"]):
        raise ValueError("prod cpus must be numeric")
    if not re.fullmatch(r"[0-9]+[gmk]", values["memory"]):
        raise ValueError("prod memory must be a Docker memory quantity")
    try:
        oom_score_adj = int(values["oom_score_adj"])
    except ValueError as error:
        raise ValueError("prod oom_score_adj must be an integer") from error
    if oom_score_adj >= 0:
        raise ValueError("prod oom_score_adj must protect the process from OOM kills")
    return ProdLimits(values["cpus"], values["memory"], oom_score_adj)
