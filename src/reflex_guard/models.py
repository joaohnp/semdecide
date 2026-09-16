from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        return asdict(self)


@dataclass(frozen=True)
class PredicateResult:
    probability: float
    model: str | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class ChoiceResult:
    choice: str
    probabilities: Mapping[str, float]
    confidence: float
    model: str | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class ScoreResult:
    score: float
    probabilities: tuple[float, ...]
    confidence: float
    model: str | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class GuardResult:
    route: str
    reason: str
    signals: Mapping[str, Any]
    model: str | None = None
    latency_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
