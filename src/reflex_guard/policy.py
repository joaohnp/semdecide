from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Decision:
    route: str
    reason: str
    signals: Mapping[str, Any]
    model: str | None = None
    latency_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _noul(answers: Mapping[str, Any], key: str) -> float:
    return float(answers[key]["noul"])


def _score(answers: Mapping[str, Any], key: str) -> float:
    return float(answers[key]["score"])


def decide(answers: Mapping[str, Any], *, model: str | None = None, latency_ms: int | None = None) -> Decision:
    """Compose Jev signals into a code-owned allow/escalate/block decision."""
    destructive = _noul(answers, "destructive")
    external = _noul(answers, "external_side_effect")
    secret = _noul(answers, "secret_exposure")
    authorized = _noul(answers, "authorized")
    clear = _noul(answers, "intent_clear")
    consequence = _score(answers, "consequence")

    signals = {
        "destructive": destructive,
        "external_side_effect": external,
        "secret_exposure": secret,
        "authorized": authorized,
        "intent_clear": clear,
        "consequence": consequence,
        "jev_advisory": answers.get("advisory_route", {}).get("choice"),
        "jev_advisory_confidence": answers.get("advisory_route", {}).get("confidence"),
    }

    if consequence < 0.50 and destructive < 0.25 and external < 0.35 and secret < 0.25 and authorized >= 0.70:
        return Decision("allow", "explicitly authorized low-risk action", signals, model, latency_ms)
    if secret >= 0.70:
        return Decision("block", "likely unauthorized secret or private-data exposure", signals, model, latency_ms)
    if destructive >= 0.80 and authorized < 0.90:
        return Decision("block", "destructive action lacks exact authorization", signals, model, latency_ms)
    if consequence >= 1.65 and authorized < 0.75:
        return Decision("block", "severe action lacks exact authorization", signals, model, latency_ms)
    if clear < 0.70:
        return Decision("escalate", "target or scope is ambiguous", signals, model, latency_ms)
    if external >= 0.60 and authorized < 0.85:
        return Decision("escalate", "external side effect requires confirmation", signals, model, latency_ms)
    if consequence >= 1.45:
        return Decision("escalate", "high-consequence action requires review", signals, model, latency_ms)
    return Decision("allow", "authorized action is within automatic-execution thresholds", signals, model, latency_ms)


def provider_failure(message: str, *, latency_ms: int | None = None) -> Decision:
    """Fail closed when semantic evaluation is unavailable."""
    return Decision("escalate", f"semantic evaluator unavailable: {message}", {}, None, latency_ms)
