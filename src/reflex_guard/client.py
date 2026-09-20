"""Compatibility wrapper for the v0.1 action-guard client API."""

from __future__ import annotations

from typing import Any

from .evaluation import evaluate as evaluate_questions
from .providers.base import ProviderError
from .providers.typesafe import TypeSafeProvider, load_api_key
from .recipes.guard import QUESTIONS as GUARD_QUESTIONS

# Preserve the historical dictionary-shaped public constant.
QUESTIONS: dict[str, Any] = {
    name: question.model_dump(mode="json") for name, question in GUARD_QUESTIONS.items()
}
ReflexAPIError = ProviderError


def evaluate(
    action: str, context: str, *, timeout: float = 10.0
) -> tuple[dict[str, Any], int]:
    """Compatibility wrapper retaining the original TypeSafe default."""
    result = evaluate_questions(
        state={"proposed_action": action, "authorization_context": context},
        questions=GUARD_QUESTIONS,
        evaluator=TypeSafeProvider(timeout=timeout).evaluate,
    )
    return result.model_dump(mode="json", exclude={"latency_ms"}), result.latency_ms
