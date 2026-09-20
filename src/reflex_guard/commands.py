"""CLI-oriented operations composed from the public Jev primitive API."""

from __future__ import annotations

from typing import Any, Mapping

from .evaluation import evaluate as evaluate_questions
from .models import (
    ChoiceAnswer,
    ChoiceResult,
    NoulAnswer,
    PredicateResult,
    ScoreAnswer,
    ScoreResult,
    Usage,
)
from .providers.base import Evaluate
from .questions import ChoiceQuestion, NoulQuestion, Question, ScoreQuestion


def predicate(
    evaluate: Evaluate, state: Any, criterion: str
) -> tuple[PredicateResult, int]:
    result = evaluate_questions(
        state=state,
        questions={"result": NoulQuestion(instructions=criterion)},
        evaluator=evaluate,
    )
    answer = result.answers["result"]
    assert isinstance(answer, NoulAnswer)
    return PredicateResult(
        probability=answer.noul,
        model=result.model,
        usage=result.usage,
    ), result.latency_ms


def choose(
    evaluate: Evaluate, state: Any, criterion: str, options: Mapping[str, str]
) -> tuple[ChoiceResult, int]:
    result = evaluate_questions(
        state=state,
        questions={
            "result": ChoiceQuestion(instructions=criterion, criteria=dict(options))
        },
        evaluator=evaluate,
    )
    answer = result.answers["result"]
    assert isinstance(answer, ChoiceAnswer)
    return ChoiceResult(
        choice=answer.choice,
        probabilities=answer.probabilities,
        confidence=answer.confidence,
        model=result.model,
        usage=result.usage,
    ), result.latency_ms


def score(
    evaluate: Evaluate, state: Any, criterion: str, levels: list[str]
) -> tuple[ScoreResult, int]:
    result = evaluate_questions(
        state=state,
        questions={"result": ScoreQuestion(instructions=criterion, criteria=levels)},
        evaluator=evaluate,
    )
    answer = result.answers["result"]
    assert isinstance(answer, ScoreAnswer)
    return ScoreResult(
        score=answer.score,
        probabilities=answer.probabilities,
        confidence=answer.confidence,
        model=result.model,
        usage=result.usage,
    ), result.latency_ms


def filter_records(
    evaluate: Evaluate, records: list[dict[str, Any]], criterion: str, field: str | None
) -> tuple[list[tuple[dict[str, Any], float]], str | None, Usage, int]:
    questions: dict[str, Question] = {}
    state: dict[str, Any] = {}
    for index, record in enumerate(records):
        if field is not None:
            if field not in record:
                raise ValueError(f"record {index + 1} is missing field {field!r}")
            value = record[field]
        else:
            value = record
        key = f"record_{index}"
        state[key] = value
        questions[key] = NoulQuestion(
            instructions=f"For state field {key}: {criterion}"
        )
    result = evaluate_questions(state=state, questions=questions, evaluator=evaluate)
    matches = []
    for index, record in enumerate(records):
        answer = result.answers[f"record_{index}"]
        assert isinstance(answer, NoulAnswer)
        matches.append((record, answer.noul))
    return matches, result.model, result.usage, result.latency_ms
