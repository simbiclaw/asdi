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
