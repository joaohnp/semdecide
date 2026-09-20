from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from .recipes.guard import GuardResult as GuardResult, Route as Route

SCHEMA_VERSION = "1"

Probability = Annotated[float, Field(ge=0, le=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class ResultModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        revalidate_instances="always",
    )


class Usage(ResultModel):
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None

    def as_dict(self) -> dict[str, int | None]:
        return self.model_dump(mode="json")


class PredicateResult(ResultModel):
    probability: Probability
    model: str | None = None
    usage: Usage = Field(default_factory=Usage)


class ChoiceResult(ResultModel):
    choice: str
    probabilities: Mapping[str, Probability]
    confidence: Probability
    model: str | None = None
    usage: Usage = Field(default_factory=Usage)


class ScoreResult(ResultModel):
    score: NonNegativeFloat
    probabilities: tuple[Probability, ...]
    confidence: Probability
    model: str | None = None
    usage: Usage = Field(default_factory=Usage)


class NoulAnswer(ResultModel):
    noul: Probability


class ChoiceAnswer(ResultModel):
    choice: str
    probabilities: Mapping[str, Probability]
    confidence: Probability


class ScoreAnswer(ResultModel):
    score: NonNegativeFloat
    probabilities: tuple[Probability, ...]
    confidence: Probability


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


class EvaluationResult(ResultModel):
    answers: dict[str, Answer]
    model: str | None = None
    usage: Usage = Field(default_factory=Usage)
    latency_ms: NonNegativeInt


def __getattr__(name: str) -> Any:
    # Legacy imports stay available without making the core import a recipe.
    if name in {"GuardResult", "Route"}:
        from .recipes import guard

        return getattr(guard, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
