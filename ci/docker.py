"""Injectable Docker CLI runner used by the Phase 7 build seam."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol, Sequence


class DockerError(RuntimeError):
    """Raised when a Docker CLI command fails."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class DockerRunner(Protocol):
    def run(self, args: Sequence[str], *, check: bool = True) -> CommandResult: ...


class CliDockerRunner:
    """Run the Docker CLI without a shell and capture all output."""

    def __init__(self, executable: str = "docker") -> None:
        self.executable = executable

    def run(self, args: Sequence[str], *, check: bool = True) -> CommandResult:
        arguments = tuple(str(arg) for arg in args)
        completed = subprocess.run(
            [self.executable, *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        result = CommandResult(arguments, completed.returncode, completed.stdout, completed.stderr)
        if check and result.returncode != 0:
            raise DockerError(
                f"docker {' '.join(arguments)} failed ({result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result
