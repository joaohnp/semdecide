"""Typed Jev primitives for Python, Unix pipelines, and optional recipes."""

from typing import TYPE_CHECKING, Any

from .evaluation import evaluate
from .models import ChoiceAnswer, EvaluationResult, NoulAnswer, ScoreAnswer, Usage
from .questions import (
    ChoiceQuestion,
    EvaluationRequest,
    NoulQuestion,
    Question,
    ScoreQuestion,
)

if TYPE_CHECKING:
    from .recipes.guard import Decision as Decision, decide as decide

__all__ = [
    "evaluate",
    "EvaluationRequest",
    "EvaluationResult",
    "Question",
    "NoulQuestion",
    "ChoiceQuestion",
    "ScoreQuestion",
    "NoulAnswer",
    "ChoiceAnswer",
    "ScoreAnswer",
    "Usage",
    "Decision",
    "decide",
]
__version__ = "0.2.1"


def __getattr__(name: str) -> Any:
    # Legacy exports remain available; primitive users need not load guard.
    if name in {"Decision", "decide"}:
        from .recipes import guard

        return getattr(guard, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
