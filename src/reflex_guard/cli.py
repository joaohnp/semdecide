from __future__ import annotations

import argparse
import json
import sys
from typing import Any, BinaryIO, TextIO

from .commands import choose, filter_records, predicate, score
from . import __version__
from .inputs import DEFAULT_MAX_INPUT_BYTES, DEFAULT_MAX_RECORDS, InputError, parse_jsonl, read_input
from .models import SCHEMA_VERSION
from .policy import decide, provider_failure
from .providers.base import Provider, ProviderError
from .providers.typesafe import TypeSafeProvider
from .client import QUESTIONS

EXIT_FALSE = 1
EXIT_USAGE = 2
EXIT_UNCERTAIN = 3
EXIT_PROVIDER = 4
GUARD_EXIT_CODES = {"allow": 0, "escalate": 10, "block": 20}
SAFE_PROVIDER_MESSAGE = "semantic provider request failed"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError(message)


def _bounded_probability(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="semdecide", description="Semantic decisions for Unix and CI")
    parser.add_argument("--version", action="version", version=f"semdecide {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        source = p.add_mutually_exclusive_group()
        source.add_argument("--text", help="input text instead of stdin")
        source.add_argument("--file", help="read input from a UTF-8 file")
        output = p.add_mutually_exclusive_group()
        output.add_argument("--json", action="store_true", help="emit stable JSON")
        output.add_argument("--quiet", action="store_true", help="emit no output")
        p.add_argument("--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES)
        p.add_argument("--timeout", type=float, default=10.0)
        p.add_argument("--retries", type=int, default=2)

    pred = sub.add_parser("is", help="evaluate a semantic predicate")
    pred.add_argument("criterion")
    pred.add_argument("--threshold", type=_bounded_probability, default=0.70)
    pred.add_argument("--uncertainty-margin", type=_bounded_probability, default=0.05)
    common(pred)

    choice = sub.add_parser("choose", help="choose among named semantic options")
    choice.add_argument("criterion", nargs="?", default="Which option best describes the input?")
    choice.add_argument("--option", action="append", required=True, metavar="NAME=DESCRIPTION")
    choice.add_argument("--min-confidence", type=_bounded_probability, default=0.50)
    common(choice)

    scoring = sub.add_parser("score", help="score input against ordered levels")
    scoring.add_argument("--criterion", default="Which ordered level best describes the input?")
    scoring.add_argument("--level", action="append", required=True)
    scoring.add_argument("--min-confidence", type=_bounded_probability, default=0.50)
    common(scoring)

    filtering = sub.add_parser("filter", help="filter JSONL records using a semantic predicate")
    filtering.add_argument("criterion")
    filtering.add_argument("--field")
    filtering.add_argument("--threshold", type=_bounded_probability, default=0.70)
    filtering.add_argument("--uncertainty-margin", type=_bounded_probability, default=0.05)
    filtering.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    filtering.add_argument("--raw", action="store_true", help="omit _semdecide metadata")
    filtering.add_argument("--jsonl", action="store_true", help="emit JSONL (the default)")
    common(filtering)

    for name, deprecated in (("guard", False), ("check", True)):
        guard = sub.add_parser(name, help="evaluate an agent action" + (" (deprecated)" if deprecated else ""))
        guard.add_argument("--action")
        guard.add_argument("--context", default="")
        guard.add_argument("--json", action="store_true")
        guard.add_argument("--quiet", action="store_true")
        guard.add_argument("--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES)
        guard.add_argument("--timeout", type=float, default=10.0)
        guard.add_argument("--retries", type=int, default=2)
    return parser


def _options(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise InputError("--option must use NAME=DESCRIPTION")
        name, description = value.split("=", 1)
        if not name or not description or name in result:
            raise InputError("option names and descriptions must be non-empty and unique")
        result[name] = description
    if not 2 <= len(result) <= 255:
        raise InputError("choose requires between 2 and 255 options")
    return result


def _emit(value: Any, *, machine: bool, quiet: bool, stdout: TextIO) -> None:
    if quiet:
        return
    if machine:
        print(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")), file=stdout)
    else:
        for line in value if isinstance(value, list) else [value]:
            print(line, file=stdout)


def _emit_error(kind: str, message: str, *, args: argparse.Namespace, stderr: TextIO) -> None:
    if getattr(args, "quiet", False):
        return
    if getattr(args, "json", False):
        payload = {
            "schema_version": SCHEMA_VERSION,
            "command": args.command,
            "error": {"kind": kind, "message": message},
        }
        print(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")), file=stderr)
    else:
        prefix = "provider error: " if kind == "provider_error" else ""
        print(f"semdecide: {prefix}{message}", file=stderr)


def _provider(args: argparse.Namespace) -> Provider:
    return TypeSafeProvider(timeout=args.timeout, retries=args.retries)


def _read(args: argparse.Namespace, stdin: BinaryIO) -> str:
    return read_input(text=getattr(args, "text", None), file=getattr(args, "file", None), stdin=stdin, max_bytes=args.max_input_bytes)


def _guard_input(args: argparse.Namespace, stdin: BinaryIO) -> tuple[str, str]:
    if args.action:
        if args.max_input_bytes <= 0:
            raise InputError("--max-input-bytes must be positive")
        submitted_bytes = len(args.action.encode("utf-8")) + len(args.context.encode("utf-8"))
        if submitted_bytes > args.max_input_bytes:
            raise InputError(f"combined action and context exceed --max-input-bytes ({args.max_input_bytes})")
        return args.action, args.context
    text = read_input(text=None, file=None, stdin=stdin, max_bytes=args.max_input_bytes)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"stdin is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("action"), str) or not value["action"].strip():
        raise InputError("stdin JSON must contain a non-empty string action")
    context = value.get("context", args.context)
    if not isinstance(context, str):
        raise InputError("context must be a string")
    return value["action"], context


def main(argv: list[str] | None = None, *, provider: Provider | None = None, stdin: BinaryIO | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    argument_values = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = _parser().parse_args(argument_values)
    except InputError as exc:
        command = next((value for value in argument_values if value in {"is", "choose", "score", "filter", "guard", "check"}), None)
        error_args = argparse.Namespace(command=command, json="--json" in argument_values, quiet="--quiet" in argument_values)
        _emit_error("input_error", str(exc), args=error_args, stderr=stderr)
        return EXIT_USAGE
    if args.command == "check" and not args.quiet:
        print("semdecide: warning: 'check' is deprecated; use 'guard'", file=stderr)
    try:
        active_provider = provider or _provider(args)
        if args.command in ("guard", "check"):
            action, context = _guard_input(args, stdin)
            try:
                response, latency = active_provider.evaluate({"proposed_action": action, "authorization_context": context}, QUESTIONS)
                decision = decide(response["answers"], model=response.get("model"), latency_ms=latency)
            except ProviderError:
                decision = provider_failure("request failed")
            payload = {"schema_version": SCHEMA_VERSION, "command": "guard", **decision.as_dict()}
            _emit(payload if args.json else [f"{decision.route.upper()}: {decision.reason}", *[f"{k}={v}" for k, v in decision.signals.items() if v is not None]], machine=args.json, quiet=args.quiet, stdout=stdout)
            return GUARD_EXIT_CODES[decision.route]

        text = _read(args, stdin)
        if args.command == "is":
            result, _ = predicate(active_provider, text, args.criterion)
            uncertain = abs(result.probability - args.threshold) < args.uncertainty_margin
            verdict = "uncertain" if uncertain else "true" if result.probability >= args.threshold else "false"
            payload = {"schema_version": SCHEMA_VERSION, "command": "is", "verdict": verdict, "probability": result.probability, "confidence": None, "threshold": args.threshold, "model": result.model, "usage": result.usage.as_dict()}
            _emit(payload if args.json else f"{verdict.upper()} probability={result.probability:.3f} threshold={args.threshold:.3f}", machine=args.json, quiet=args.quiet, stdout=stdout)
            return EXIT_UNCERTAIN if uncertain else 0 if verdict == "true" else EXIT_FALSE

        if args.command == "choose":
            options = _options(args.option)
            result, _ = choose(active_provider, text, args.criterion, options)
            uncertain = result.confidence < args.min_confidence
            payload = {"schema_version": SCHEMA_VERSION, "command": "choose", "choice": result.choice, "probabilities": dict(result.probabilities), "confidence": result.confidence, "min_confidence": args.min_confidence, "uncertain": uncertain, "model": result.model, "usage": result.usage.as_dict()}
            _emit(payload if args.json else f"{result.choice} confidence={result.confidence:.3f}" + (" UNCERTAIN" if uncertain else ""), machine=args.json, quiet=args.quiet, stdout=stdout)
            return EXIT_UNCERTAIN if uncertain else 0

        if args.command == "score":
            if not 2 <= len(args.level) <= 255:
                raise InputError("score requires between 2 and 255 levels")
            result, _ = score(active_provider, text, args.criterion, args.level)
            uncertain = result.confidence < args.min_confidence
            payload = {"schema_version": SCHEMA_VERSION, "command": "score", "score": result.score, "levels": args.level, "probabilities": list(result.probabilities), "confidence": result.confidence, "min_confidence": args.min_confidence, "uncertain": uncertain, "model": result.model, "usage": result.usage.as_dict()}
            _emit(payload if args.json else f"score={result.score:.3f} confidence={result.confidence:.3f}" + (" UNCERTAIN" if uncertain else ""), machine=args.json, quiet=args.quiet, stdout=stdout)
            return EXIT_UNCERTAIN if uncertain else 0

        records = parse_jsonl(text, max_records=args.max_records)
        evaluated, model, usage, _ = filter_records(active_provider, records, args.criterion, args.field)
        selected = 0
        uncertain_count = 0
        for record, probability in evaluated:
            uncertain = abs(probability - args.threshold) < args.uncertainty_margin
            uncertain_count += int(uncertain)
            if probability < args.threshold or uncertain:
                continue
            selected += 1
            output = dict(record)
            if not args.raw:
                output["_semdecide"] = {"schema_version": SCHEMA_VERSION, "probability": probability, "threshold": args.threshold, "model": model}
            if not args.quiet:
                print(json.dumps(output, sort_keys=True, ensure_ascii=False, separators=(",", ":")), file=stdout)
        if uncertain_count:
            return EXIT_UNCERTAIN
        return 0 if selected else EXIT_FALSE
    except (InputError, ValueError) as exc:
        _emit_error("input_error", str(exc), args=args, stderr=stderr)
        return EXIT_USAGE
    except ProviderError:
        _emit_error("provider_error", SAFE_PROVIDER_MESSAGE, args=args, stderr=stderr)
        return EXIT_PROVIDER


if __name__ == "__main__":
    raise SystemExit(main())
