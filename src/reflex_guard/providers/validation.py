"""Shared validation for Jev answers, regardless of API gateway."""

from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from pydantic import ValidationError

from .base import Evaluate, ProviderError


@contextmanager
def provider_validation() -> Iterator[None]:
    """Keep provider-derived model errors out of local-input diagnostics."""
    try:
        yield
    except ValidationError as exc:
        raise ProviderError("invalid semantic provider response") from exc


def evaluate_validated(
    evaluate: Evaluate, state: Any, questions: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], int]:
    """Validate before consumption, including for injected evaluators."""
    with provider_validation():
        response, latency = evaluate(state, questions)
        return validate_response(response, questions), latency


def _number(
    value: Any, path: str, *, low: float | None = None, high: float | None = None
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(f"invalid Jev response: {path} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ProviderError(f"invalid Jev response: {path} must be finite")
    if low is not None and result < low or high is not None and result > high:
        raise ProviderError(f"invalid Jev response: {path} is out of range")
    return result


def _usage(value: Any) -> dict[str, int | None]:
    if value is None:
        return {"input_tokens": None, "output_tokens": None}
    if not isinstance(value, dict):
        raise ProviderError("invalid Jev response: usage must be an object")
    result: dict[str, int | None] = {}
    for name in ("input_tokens", "output_tokens"):
        item = value.get(name)
        if item is not None and (
            isinstance(item, bool) or not isinstance(item, int) or item < 0
        ):
            raise ProviderError(
                f"invalid Jev response: usage.{name} must be a non-negative integer"
            )
        result[name] = item
    return result


def validate_response(
    value: Any, questions: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderError("invalid Jev response: root must be an object")
    answers = value.get("answers")
    if not isinstance(answers, dict):
        raise ProviderError("invalid Jev response: missing answers object")
    if set(answers) != set(questions):
        missing = sorted(set(questions) - set(answers))
        extra = sorted(set(answers) - set(questions))
        detail = (
            f"missing answers {missing}" if missing else f"unexpected answers {extra}"
        )
        raise ProviderError(f"invalid Jev response: {detail}")
    clean: dict[str, Any] = {}
    for key, question in questions.items():
        answer = answers[key]
        if not isinstance(answer, dict):
            raise ProviderError(
                f"invalid Jev response: answers.{key} must be an object"
            )
        kind = question.get("type")
        if kind == "noul":
            clean[key] = {
                "noul": _number(
                    answer.get("noul"), f"answers.{key}.noul", low=0, high=1
                )
            }
        elif kind == "choice":
            criteria = question.get("criteria")
            names = list(criteria) if isinstance(criteria, dict) else []
            choice = answer.get("choice")
            probs = answer.get("probabilities")
            if not isinstance(choice, str) or choice not in names:
                raise ProviderError(
                    f"invalid Jev response: answers.{key}.choice is not an option"
                )
            if not isinstance(probs, dict) or set(probs) != set(names):
                raise ProviderError(
                    f"invalid Jev response: answers.{key}.probabilities must cover every option"
                )
            clean_probs = {
                name: _number(
                    probs[name], f"answers.{key}.probabilities.{name}", low=0, high=1
                )
                for name in names
            }
            if abs(sum(clean_probs.values()) - 1.0) > 0.02:
                raise ProviderError(
                    f"invalid Jev response: answers.{key}.probabilities must sum to 1"
                )
            clean[key] = {
                "choice": choice,
                "probabilities": clean_probs,
                "confidence": _number(
                    answer.get("confidence"), f"answers.{key}.confidence", low=0, high=1
                ),
            }
        elif kind == "score":
            criteria = question.get("criteria")
            count = len(criteria) if isinstance(criteria, list) else 0
            probabilities = answer.get("probabilities")
            if isinstance(probabilities, dict):
                probabilities = [probabilities.get(str(i)) for i in range(count)]
            if not isinstance(probabilities, list) or len(probabilities) != count:
                raise ProviderError(
                    f"invalid Jev response: answers.{key}.probabilities must have {count} values"
                )
            clean_probs = [
                _number(item, f"answers.{key}.probabilities", low=0, high=1)
                for item in probabilities
            ]
            if abs(sum(clean_probs) - 1.0) > 0.02:
                raise ProviderError(
                    f"invalid Jev response: answers.{key}.probabilities must sum to 1"
                )
            clean[key] = {
                "score": _number(
                    answer.get("score"), f"answers.{key}.score", low=0, high=count - 1
                ),
                "probabilities": clean_probs,
                "confidence": _number(
                    answer.get("confidence"), f"answers.{key}.confidence", low=0, high=1
                ),
            }
        else:
            raise ProviderError(f"unsupported question type: {kind}")
    model = value.get("model")
    if model is not None and not isinstance(model, str):
        raise ProviderError("invalid Jev response: model must be a string")
    return {"answers": clean, "model": model, "usage": _usage(value.get("usage"))}
