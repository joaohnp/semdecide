from __future__ import annotations

import json
import os
import random
import shlex
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from .base import ProviderError
from .validation import validate_response

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
Transport = Callable[[urllib.request.Request, float], bytes]
Sleep = Callable[[float], None]


def load_api_key() -> str:
    if key := os.environ.get("TYPESAFE_API_KEY"):
        return key
    path = Path(
        os.environ.get(
            "TYPESAFE_CREDENTIALS_FILE", "~/.config/typesafe/credentials.env"
        )
    ).expanduser()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProviderError(f"cannot read credentials file {path}: {exc}") from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if not line.startswith("TYPESAFE_API_KEY="):
            continue
        parsed = shlex.split(line.split("=", 1)[1], comments=True)
        if len(parsed) == 1 and parsed[0]:
            return parsed[0]
    raise ProviderError(f"TYPESAFE_API_KEY not found in {path}")


def _default_transport(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class TypeSafeProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        url: str | None = None,
        timeout: float = 10.0,
        retries: int = 2,
        transport: Transport | None = None,
        sleep: Sleep = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ):
        if timeout <= 0 or retries < 0 or retries > 5:
            raise ValueError(
                "timeout must be positive and retries must be between 0 and 5"
            )
        self.api_key = api_key
        self.url = (
            url
            or os.environ.get("SEMDECIDE_API_URL")
            or os.environ.get("REFLEX_API_URL", DEFAULT_URL)
        )
        self.timeout = timeout
        self.retries = retries
        self.transport = transport or _default_transport
        self.sleep = sleep
        self.random_fn = random_fn

    def evaluate(
        self, state: Any, questions: Mapping[str, Mapping[str, Any]]
    ) -> tuple[dict[str, Any], int]:
        key = self.api_key or load_api_key()
        payload = json.dumps(
            {"state": state, "model": "jev-latest", "questions": questions},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        for attempt in range(self.retries + 1):
            try:
                body = self.transport(request, self.timeout)
                try:
                    decoded = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ProviderError(
                        f"invalid TypeSafe response: invalid JSON: {exc}"
                    ) from exc
                return validate_response(decoded, questions), round(
                    (time.perf_counter() - started) * 1000
                )
            except urllib.error.HTTPError as exc:
                transient = exc.code == 429 or 500 <= exc.code <= 599
                if transient and attempt < self.retries:
                    self._backoff(attempt)
                    continue
                raise ProviderError(f"TypeSafe returned HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._backoff(attempt)
                    continue
                raise ProviderError("TypeSafe request failed") from exc
        raise AssertionError("retry loop exhausted")

    def _backoff(self, attempt: int) -> None:
        self.sleep(min(2.0, 0.1 * (2**attempt)) + self.random_fn() * 0.05)
