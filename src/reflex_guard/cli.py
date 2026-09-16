from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .client import ReflexAPIError, evaluate
from .policy import Decision, decide, provider_failure

EXIT_CODES = {"allow": 0, "escalate": 10, "block": 20}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reflex", description="Route an agent action through Jev-backed semantic policy.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="evaluate one proposed action")
    check.add_argument("--action", help="the exact proposed action")
    check.add_argument("--context", default="", help="authorization and execution context")
    check.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    check.add_argument("--timeout", type=float, default=10.0, help="provider timeout in seconds")
    return parser


def _stdin_payload() -> dict[str, Any]:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"stdin is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("stdin JSON must be an object")
    return value


def _render(decision: Decision, machine: bool) -> None:
    if machine:
        print(json.dumps(decision.as_dict(), sort_keys=True))
        return
    icon = {"allow": "ALLOW", "escalate": "ESCALATE", "block": "BLOCK"}[decision.route]
    print(f"{icon}: {decision.reason}")
    if decision.model:
        print(f"model={decision.model} latency_ms={decision.latency_ms}")
    for key, value in decision.signals.items():
        if value is not None:
            print(f"{key}={value}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        stdin = _stdin_payload()
        action = args.action or stdin.get("action")
        context = args.context or stdin.get("context", "")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("provide --action or stdin JSON with a non-empty action")
        if not isinstance(context, str):
            raise ValueError("context must be a string")
        try:
            result, latency_ms = evaluate(action, context, timeout=args.timeout)
            decision = decide(result["answers"], model=result.get("model"), latency_ms=latency_ms)
        except ReflexAPIError as exc:
            decision = provider_failure(str(exc))
        _render(decision, args.json)
        return EXIT_CODES[decision.route]
    except ValueError as exc:
        print(f"reflex: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
