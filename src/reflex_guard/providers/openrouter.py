"""Jev via OpenRouter's Decisions API (not chat completions)."""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from .base import ProviderError
from .validation import validate_response


def evaluate(
    state: Any,
    questions: Mapping[str, Mapping[str, Any]],
    *,
    timeout: float = 10.0,
) -> tuple[dict[str, Any], int]:
    """Make one request using the environment loaded by the caller."""
    api_key = os.environ["OPEN_ROUTER_API_KEY"]
    base_url = os.environ["OPEN_ROUTER_BASE_URL"]
    model = os.environ["OPEN_ROUTER_MODEL"]
    if not all((api_key, base_url, model)):
        raise ProviderError("OpenRouter API key, base URL, and model must not be empty")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/decisions",
        data=json.dumps(
            {
                "model": model,
                "state": state,
                "questions": questions,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "semdecide",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.load(response)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ProviderError(f"OpenRouter returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError("OpenRouter request failed") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderError("invalid OpenRouter response: invalid JSON") from exc

    result = validate_response(decoded, questions)
    return result, round((time.perf_counter() - started) * 1000)
