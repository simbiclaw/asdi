#!/usr/bin/env python3
"""Fail-closed changed-path and feature-coverage classifier for REV K."""

from __future__ import annotations

from pathlib import PurePath
from typing import Any


PROTECTED_PATH_PATTERNS = (
    ".asdi/**",
    "verify/**",
    "evals/**",
    "tests/rules/**",
    "ci/**",
    "config/classes.yaml",
    "config/coverage.yaml",
    "config/waivers.yaml",
)


def _matches(path: str, patterns: list[str]) -> bool:
    pure = PurePath(path)
    return any(pure.full_match(PurePath(pattern)) for pattern in patterns)


def load_mapping(value: dict[str, Any]) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("feature map must be an object")
    result: dict[str, list[str]] = {}
    for feature, patterns in value.items():
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(f"feature {feature} must map to at least one path")
        result[str(feature)] = [str(pattern) for pattern in patterns]
    return result


def classify_changed_paths(
    *,
    paths: list[str],
    feature_map: dict[str, list[str]],
    class_config: dict[str, Any],
) -> dict[str, Any]:
    if not paths:
        raise ValueError("changed paths are required")
    judgment_patterns = [
        str(item) for item in class_config.get("judgment_paths", [])
    ]
    agent_patterns = [
        str(item) for item in class_config.get("agent_mergeable_paths", [])
    ]
    protected = sorted(
        path for path in paths if _matches(path, list(PROTECTED_PATH_PATTERNS))
    )
    explicit_judgment = sorted(
        path for path in paths if _matches(path, judgment_patterns)
    )
    mapped_features: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for path in paths:
        features = [
            feature
            for feature, patterns in feature_map.items()
            if _matches(path, patterns)
        ]
        if features:
            mapped_features[path] = features
        else:
            unmapped.append(path)

    rules_fired: list[str] = []
    split_required = False
    if protected:
        rules_fired.append("protected-path-human-review")
    if protected and any(path not in protected for path in paths):
        split_required = True
        rules_fired.append("verification-path-product-mix")
    if explicit_judgment:
        rules_fired.append("explicit-judgment-path")
    if unmapped:
        rules_fired.append("uncovered-product-path")

    if split_required:
        decision = "split_required"
        change_class = "blocked"
    elif protected or explicit_judgment or unmapped:
        decision = "human_required"
        change_class = "judgment"
    else:
        decision = "agent_mergeable"
        change_class = "agent_mergeable"

    return {
        "decision": decision,
        "change_class": change_class,
        "paths": sorted(paths),
        "protected_paths": protected,
        "explicit_judgment_paths": explicit_judgment,
        "uncovered_paths": sorted(unmapped),
        "mapped_features": mapped_features,
        "rules_fired": rules_fired,
        "split_required": split_required,
        "human_required": decision == "human_required",
    }
