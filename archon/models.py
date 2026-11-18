"""Reviewer model adapter (DD-6 seam: ``review.passes[].model``).

The reviewer gets text in and text out. It has no tools, so it has no side
effects (Guide section 10.4). The provisional default is a local model served
by vllm-mlx through an OpenAI-compatible endpoint; any provider key is added by
the egress proxy, never held here (hard rule 4).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Protocol


class ModelUnavailable(RuntimeError):
    pass


class ReviewModel(Protocol):
    name: str
    family: str

    def complete(self, system: str, user: str) -> str: ...


FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concern": {"type": "string", "enum": ["contract", "correctness", "security"]},
                    "bucket": {"type": "string", "enum": ["act", "consider", "noted"]},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "claim": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["concern", "bucket", "file", "line", "claim", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


@dataclass
class AnthropicModel:
    """Claude via the official SDK, for the GitHub-hosted gate (owner override of D-8).

    Structured outputs constrain the reply to the findings schema; the reviewer
    still has no tools. A refusal is retried server-side on a fallback model;
    if the whole chain refuses, the pass is blocked, never passed.
    """

    name: str
    family: str = "anthropic"
    effort: str = "high"
    client: Any = None

    def complete(self, system: str, user: str) -> str:
        import anthropic  # imported lazily: the local Studio path stays stdlib-only (ADR-0005)

        client = self.client or anthropic.Anthropic()
        try:
            with client.beta.messages.stream(
                model=self.name,
                max_tokens=64000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": FINDINGS_SCHEMA},
                },
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                message = stream.get_final_message()
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
            raise ModelUnavailable(f"{self.name}: {type(error).__name__}: {error}") from error
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None) if message.stop_details else None
            raise ModelUnavailable(f"{self.name}: refused ({category})")
        if message.stop_reason == "max_tokens":
            raise ValueError("reviewer output truncated at max_tokens")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise ValueError("reviewer returned no text block")
        return text


@dataclass
class OpenAICompatibleModel:
    name: str
    family: str
    base_url: str
    timeout_seconds: float = 600
    opener: Callable[[urllib.request.Request], Any] | None = None

    def complete(self, system: str, user: str) -> str:
        body = {
            "model": self.name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        opener = self.opener or (lambda r: urllib.request.urlopen(r, timeout=self.timeout_seconds))
        try:
            with opener(request) as response:
                payload = json.loads(response.read())
            return payload["choices"][0]["message"]["content"]
        except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as error:
            raise ModelUnavailable(f"{self.name}: {error}") from error
