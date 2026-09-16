from __future__ import annotations

import json
import math
import os
import random
import shlex
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from .base import ProviderError

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
Transport = Callable[[urllib.request.Request, float], bytes]
Sleep = Callable[[float], None]


def load_api_key() -> str:
    if key := os.environ.get("TYPESAFE_API_KEY"):
        return key
    path = Path(os.environ.get("TYPESAFE_CREDENTIALS_FILE", "~/.config/typesafe/credentials.env")).expanduser()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProviderError(f"cannot read credentials file {path}: {exc}") from exc
    for line in lines:
        if line.startswith("export TYPESAFE_API_KEY="):
            parsed = shlex.split(line.split("=", 1)[1])
            if len(parsed) == 1 and parsed[0]:
                return parsed[0]
    raise ProviderError(f"TYPESAFE_API_KEY not found in {path}")


def _default_transport(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _number(value: Any, path: str, *, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(f"invalid TypeSafe response: {path} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ProviderError(f"invalid TypeSafe response: {path} must be finite")
    if low is not None and result < low or high is not None and result > high:
        raise ProviderError(f"invalid TypeSafe response: {path} is out of range")
    return result


def _usage(value: Any) -> dict[str, int | None]:
    if value is None:
        return {"input_tokens": None, "output_tokens": None}
    if not isinstance(value, dict):
        raise ProviderError("invalid TypeSafe response: usage must be an object")
    result: dict[str, int | None] = {}
    for name in ("input_tokens", "output_tokens"):
        item = value.get(name)
        if item is not None and (isinstance(item, bool) or not isinstance(item, int) or item < 0):
            raise ProviderError(f"invalid TypeSafe response: usage.{name} must be a non-negative integer")
        result[name] = item
    return result


def validate_response(value: Any, questions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderError("invalid TypeSafe response: root must be an object")
    answers = value.get("answers")
    if not isinstance(answers, dict):
        raise ProviderError("invalid TypeSafe response: missing answers object")
    if set(answers) != set(questions):
        missing = sorted(set(questions) - set(answers))
        extra = sorted(set(answers) - set(questions))
        detail = f"missing answers {missing}" if missing else f"unexpected answers {extra}"
        raise ProviderError(f"invalid TypeSafe response: {detail}")
    clean: dict[str, Any] = {}
    for key, question in questions.items():
        answer = answers[key]
        if not isinstance(answer, dict):
            raise ProviderError(f"invalid TypeSafe response: answers.{key} must be an object")
        kind = question.get("type")
        if kind == "noul":
            clean[key] = {"noul": _number(answer.get("noul"), f"answers.{key}.noul", low=0, high=1)}
        elif kind == "choice":
            criteria = question.get("criteria")
            names = list(criteria) if isinstance(criteria, dict) else []
            choice = answer.get("choice")
            probs = answer.get("probabilities")
            if not isinstance(choice, str) or choice not in names:
                raise ProviderError(f"invalid TypeSafe response: answers.{key}.choice is not an option")
            if not isinstance(probs, dict) or set(probs) != set(names):
                raise ProviderError(f"invalid TypeSafe response: answers.{key}.probabilities must cover every option")
            clean_probs = {name: _number(probs[name], f"answers.{key}.probabilities.{name}", low=0, high=1) for name in names}
            if abs(sum(clean_probs.values()) - 1.0) > 0.02:
                raise ProviderError(f"invalid TypeSafe response: answers.{key}.probabilities must sum to 1")
            clean[key] = {"choice": choice, "probabilities": clean_probs, "confidence": _number(answer.get("confidence"), f"answers.{key}.confidence", low=0, high=1)}
        elif kind == "score":
            criteria = question.get("criteria")
            count = len(criteria) if isinstance(criteria, list) else 0
            probabilities = answer.get("probabilities")
            if isinstance(probabilities, dict):
                probabilities = [probabilities.get(str(i)) for i in range(count)]
            if not isinstance(probabilities, list) or len(probabilities) != count:
                raise ProviderError(f"invalid TypeSafe response: answers.{key}.probabilities must have {count} values")
            clean_probs = [_number(item, f"answers.{key}.probabilities", low=0, high=1) for item in probabilities]
            if abs(sum(clean_probs) - 1.0) > 0.02:
                raise ProviderError(f"invalid TypeSafe response: answers.{key}.probabilities must sum to 1")
            clean[key] = {"score": _number(answer.get("score"), f"answers.{key}.score", low=0, high=count), "probabilities": clean_probs, "confidence": _number(answer.get("confidence"), f"answers.{key}.confidence", low=0, high=1)}
        else:
            raise ProviderError(f"unsupported question type: {kind}")
    model = value.get("model")
    if model is not None and not isinstance(model, str):
        raise ProviderError("invalid TypeSafe response: model must be a string")
    return {"answers": clean, "model": model, "usage": _usage(value.get("usage"))}


class TypeSafeProvider:
    def __init__(self, *, api_key: str | None = None, url: str | None = None, timeout: float = 10.0, retries: int = 2, transport: Transport | None = None, sleep: Sleep = time.sleep, random_fn: Callable[[], float] = random.random):
        if timeout <= 0 or retries < 0 or retries > 5:
            raise ValueError("timeout must be positive and retries must be between 0 and 5")
        self.api_key = api_key
        self.url = url or os.environ.get("REFLEX_API_URL", DEFAULT_URL)
        self.timeout = timeout
        self.retries = retries
        self.transport = transport or _default_transport
        self.sleep = sleep
        self.random_fn = random_fn

    def evaluate(self, state: Any, questions: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], int]:
        key = self.api_key or load_api_key()
        payload = json.dumps({"state": state, "model": "jev-latest", "questions": questions}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(self.url, data=payload, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
        started = time.perf_counter()
        for attempt in range(self.retries + 1):
            try:
                body = self.transport(request, self.timeout)
                try:
                    decoded = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ProviderError(f"invalid TypeSafe response: invalid JSON: {exc}") from exc
                return validate_response(decoded, questions), round((time.perf_counter() - started) * 1000)
            except urllib.error.HTTPError as exc:
                transient = exc.code == 429 or 500 <= exc.code <= 599
                if transient and attempt < self.retries:
                    self._backoff(attempt)
                    continue
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                raise ProviderError(f"TypeSafe returned HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._backoff(attempt)
                    continue
                raise ProviderError(f"TypeSafe unavailable: {exc}") from exc
        raise AssertionError("retry loop exhausted")

    def _backoff(self, attempt: int) -> None:
        self.sleep(min(2.0, 0.1 * (2 ** attempt)) + self.random_fn() * 0.05)
