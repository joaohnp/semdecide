"""Optional recipes built on the public evaluation API.

JSON recipes are reusable question sets, not executable plugins. Applications
with custom policy can compose evaluate() in Python, as the guard recipe does.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from ..evaluation import evaluate
from ..inputs import DEFAULT_MAX_INPUT_BYTES, InputError, read_input
from ..models import EvaluationResult, ResultModel
from ..providers.base import Evaluate
from ..questions import NonEmptyText, Questions


class Recipe(ResultModel):
    schema_version: Literal["1"] = "1"
    name: NonEmptyText
    description: str = ""
    questions: Questions

    def run(
        self, state: JsonValue, *, evaluator: Evaluate | None = None
    ) -> EvaluationResult:
        return evaluate(state=state, questions=self.questions, evaluator=evaluator)


def resolve_recipe(target: str) -> Path:
    """Explicit paths, then project-local names, then user-installed names."""
    path = Path(target).expanduser()
    if path.is_absolute() or "/" in target or "\\" in target or path.suffix == ".json":
        return path
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", target):
        raise InputError("recipe must be a name or an explicit JSON file path")
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    candidates = (
        Path.cwd() / ".semdecide" / "recipes" / f"{target}.json",
        config_home / "semdecide" / "recipes" / f"{target}.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise InputError(
        f"recipe {target!r} was not found locally or in the user configuration"
    )


def load_recipe(target: str, *, max_bytes: int = DEFAULT_MAX_INPUT_BYTES) -> Recipe:
    text = read_input(
        text=None,
        file=str(resolve_recipe(target)),
        stdin=io.BytesIO(),
        max_bytes=max_bytes,
    )
    return Recipe.model_validate_json(text)


__all__ = ["Recipe", "load_recipe", "resolve_recipe"]
