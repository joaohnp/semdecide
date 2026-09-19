from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

Evaluate = Callable[[Any, Mapping[str, Mapping[str, Any]]], tuple[dict[str, Any], int]]


class ProviderError(RuntimeError):
    """Provider unavailable, rejected the request, or returned invalid data."""


class Provider(Protocol):
    def evaluate(
        self, state: Any, questions: Mapping[str, Mapping[str, Any]]
    ) -> tuple[dict[str, Any], int]: ...
