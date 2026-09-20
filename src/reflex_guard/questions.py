"""Caller-defined Jev questions; no application-specific prompts or policy."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue

from .models import ResultModel

NonEmptyText = Annotated[str, Field(min_length=1, pattern=r"\S")]


class NoulQuestion(ResultModel):
    type: Literal["noul"] = "noul"
    instructions: NonEmptyText


class ChoiceQuestion(ResultModel):
    type: Literal["choice"] = "choice"
    instructions: NonEmptyText
    criteria: Annotated[
        dict[NonEmptyText, NonEmptyText], Field(min_length=2, max_length=255)
    ]


class ScoreQuestion(ResultModel):
    type: Literal["score"] = "score"
    instructions: NonEmptyText
    criteria: Annotated[list[NonEmptyText], Field(min_length=2, max_length=255)]


Question = Annotated[
    NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")
]
Questions = Annotated[dict[NonEmptyText, Question], Field(min_length=1)]


class EvaluationRequest(ResultModel):
    """A complete, JSON-compatible request, also accepted by the CLI."""

    schema_version: Literal["1"] = "1"
    state: JsonValue
    questions: Questions
