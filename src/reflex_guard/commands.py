from __future__ import annotations

from typing import Any, Mapping

from .models import ChoiceResult, PredicateResult, ScoreResult, Usage
from .providers.base import Provider


def _usage(response: Mapping[str, Any]) -> Usage:
    value = response.get("usage", {})
    return Usage(value.get("input_tokens"), value.get("output_tokens"))


def predicate(provider: Provider, state: Any, criterion: str) -> tuple[PredicateResult, int]:
    response, latency = provider.evaluate(state, {"result": {"type": "noul", "instructions": criterion}})
    return PredicateResult(response["answers"]["result"]["noul"], response.get("model"), _usage(response)), latency


def choose(provider: Provider, state: Any, criterion: str, options: Mapping[str, str]) -> tuple[ChoiceResult, int]:
    response, latency = provider.evaluate(state, {"result": {"type": "choice", "instructions": criterion, "criteria": dict(options)}})
    answer = response["answers"]["result"]
    return ChoiceResult(answer["choice"], answer["probabilities"], answer["confidence"], response.get("model"), _usage(response)), latency


def score(provider: Provider, state: Any, criterion: str, levels: list[str]) -> tuple[ScoreResult, int]:
    response, latency = provider.evaluate(state, {"result": {"type": "score", "instructions": criterion, "criteria": levels}})
    answer = response["answers"]["result"]
    return ScoreResult(answer["score"], tuple(answer["probabilities"]), answer["confidence"], response.get("model"), _usage(response)), latency


def filter_records(provider: Provider, records: list[dict[str, Any]], criterion: str, field: str | None) -> tuple[list[tuple[dict[str, Any], float]], str | None, Usage, int]:
    questions: dict[str, dict[str, str]] = {}
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
        questions[key] = {"type": "noul", "instructions": f"For state field {key}: {criterion}"}
    response, latency = provider.evaluate(state, questions)
    matches = [(record, response["answers"][f"record_{index}"]["noul"]) for index, record in enumerate(records)]
    return matches, response.get("model"), _usage(response), latency
