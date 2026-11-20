"""Build a toy-notes image from an exact, approved main commit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from .approval import (
    ApprovalError,
    load_deployment_approval,
    sha256_file,
    utc_now,
    validate_commit,
    validate_ops_registry,
    write_json_atomic,
)
from .docker import CliDockerRunner, DockerError, DockerRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCKERFILE = REPO_ROOT / "pilots" / "toy_notes" / "Dockerfile"
DEFAULT_CONTEXT = REPO_ROOT / "pilots" / "toy_notes"
def _parse_digest(stdout: str) -> str:
    candidate = stdout.strip().strip('"').strip("'")
    if not candidate.startswith("sha256:"):
        candidate = "sha256:" + candidate
    from .approval import validate_digest

    return validate_digest(candidate)


def build_image(
    *,
    commit: str,
    decision_file: str | Path,
    registry: str,
    artifact_path: str | Path,
    record_path: str | Path,
    dockerfile: str | Path = DEFAULT_DOCKERFILE,
    context: str | Path = DEFAULT_CONTEXT,
    runner: DockerRunner | None = None,
    max_age_seconds: int | None = None,
    built_at: str | None = None,
) -> dict[str, Any]:
    exact_commit = validate_commit(commit)
    registry_ref = validate_ops_registry(registry)
    approval = load_deployment_approval(
        decision_file, exact_commit, max_age_seconds=max_age_seconds
    )
    dockerfile_path = Path(dockerfile).resolve()
    context_path = Path(context).resolve()
    if not dockerfile_path.is_file():
        raise FileNotFoundError(f"Dockerfile is missing: {dockerfile_path}")
    if not context_path.is_dir():
        raise NotADirectoryError(f"build context is missing: {context_path}")
    artifact = Path(artifact_path).resolve()
    artifact.parent.mkdir(parents=True, exist_ok=True)

    docker = runner or CliDockerRunner()
    image_tag = f"{registry_ref}:{exact_commit}"
    docker.run(
        [
            "buildx",
            "build",
            "--network=none",
            "--file",
            str(dockerfile_path),
            "--tag",
            image_tag,
            "--push",
            str(context_path),
        ]
    )
    inspected = docker.run(
        [
            "buildx",
            "imagetools",
            "inspect",
            image_tag,
            "--format",
            "{{.Manifest.Digest}}",
        ]
    )
    digest = _parse_digest(inspected.stdout)
    by_digest = f"{registry_ref}@{digest}"
    docker.run(["pull", by_digest])
    docker.run(["image", "save", by_digest, "--output", str(artifact)])
    if not artifact.is_file():
        raise RuntimeError(f"Docker save did not create the image artifact: {artifact}")

    record = {
        "schema_version": "asdi.phase7-build-record/v1",
        "commit": exact_commit,
        "digest": digest,
        "artifact_digest": sha256_file(artifact),
        "artifact_path": str(artifact),
        "registry": registry_ref,
        "dockerfile": str(dockerfile_path),
        "context": str(context_path),
        "approval": approval,
        "built_at": built_at or utc_now(),
    }
    path = Path(record_path).resolve()
    record["record_path"] = str(path)
    write_json_atomic(path, record)
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asdi-phase7-build")
    parser.add_argument("--commit", required=True, help="exact 40-character main commit")
    parser.add_argument("--decision-file", required=True, help="durable passing deployment decision")
    parser.add_argument("--registry", required=True, help="ops registry repository reference")
    parser.add_argument("--artifact", required=True, help="path for the saved image archive")
    parser.add_argument("--record", required=True, help="path for the build record JSON")
    parser.add_argument("--dockerfile", default=str(DEFAULT_DOCKERFILE))
    parser.add_argument("--context", default=str(DEFAULT_CONTEXT))
    parser.add_argument("--max-age-seconds", type=int, default=None)
    parser.add_argument("--docker", default="docker", help="Docker CLI executable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        record = build_image(
            commit=arguments.commit,
            decision_file=arguments.decision_file,
            registry=arguments.registry,
            artifact_path=arguments.artifact,
            record_path=arguments.record,
            dockerfile=arguments.dockerfile,
            context=arguments.context,
            runner=CliDockerRunner(arguments.docker),
            max_age_seconds=arguments.max_age_seconds,
        )
    except (ApprovalError, DockerError, OSError, ValueError) as error:
        print(f"build refused: {error}", file=sys.stderr)
        return 2
    print(
        f"build record={record['record_path']} commit={record['commit']} "
        f"digest={record['digest']} artifact_digest={record['artifact_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
