"""Public, provider-independent evaluation of typed Jev questions."""

from __future__ import annotations

from typing import Mapping

from pydantic import JsonValue

from .models import (
    Answer,
    ChoiceAnswer,
    EvaluationResult,
    NoulAnswer,
    ScoreAnswer,
    Usage,
)
from .providers.base import Evaluate
from .providers.openrouter import evaluate as evaluate_openrouter
from .providers.validation import evaluate_validated, provider_validation
from .questions import EvaluationRequest, Question


def evaluate(
    *,
    state: JsonValue,
    questions: Mapping[str, Question],
    evaluator: Evaluate | None = None,
) -> EvaluationResult:
    """Validate a request, evaluate it, and return typed answers without policy.

    Defaults to OpenRouter using the caller's environment. Pass an evaluator
    callable (e.g. TypeSafeProvider(...).evaluate) to select another adapter.
    This library API does not load .env files or render output.
    """
    request = EvaluationRequest(state=state, questions=dict(questions))
    wire_questions = {
        name: question.model_dump(mode="json")
        for name, question in request.questions.items()
    }
    response, latency = evaluate_validated(
        evaluator if evaluator is not None else evaluate_openrouter,
        request.state,
        wire_questions,
    )
    with provider_validation():
        answers: dict[str, Answer] = {}
        for name, question in request.questions.items():
            answer = response["answers"][name]
            if question.type == "noul":
                answers[name] = NoulAnswer(**answer)
            elif question.type == "choice":
                answers[name] = ChoiceAnswer(**answer)
            else:
                answers[name] = ScoreAnswer(
                    score=answer["score"],
                    probabilities=tuple(answer["probabilities"]),
                    confidence=answer["confidence"],
                )
        return EvaluationResult(
            answers=answers,
            model=response["model"],
            usage=Usage(**response["usage"]),
            latency_ms=latency,
        )
