from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from typing import Any, BinaryIO, TextIO

from dotenv import load_dotenv
from pydantic import ValidationError

from .commands import choose, filter_records, predicate, score
from . import __version__
from .inputs import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_MAX_RECORDS,
    InputError,
    parse_jsonl,
    read_input,
)
from .evaluation import evaluate as evaluate_questions
from .models import SCHEMA_VERSION
from .questions import EvaluationRequest
from .recipes import Recipe, load_recipe
from .recipes.guard import EXIT_CODES as GUARD_EXIT_CODES, run as run_guard
from .providers.base import Evaluate, Provider, ProviderError
from .providers.openrouter import evaluate as evaluate_openrouter
from .providers.typesafe import TypeSafeProvider

EXIT_FALSE = 1
EXIT_USAGE = 2
EXIT_UNCERTAIN = 3
EXIT_PROVIDER = 4
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
    parser = _ArgumentParser(
        prog="semdecide", description="Semantic decisions for Unix and CI"
    )
    parser.add_argument(
        "--version", action="version", version=f"semdecide {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def provider_options(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--provider",
            choices=("openrouter", "typesafe"),
            default="openrouter",
            help="API gateway for Jev (default: openrouter)",
        )
        p.add_argument("--timeout", type=float, default=10.0)
        p.add_argument(
            "--retries",
            type=int,
            default=2,
            help="TypeSafe only; OpenRouter makes one attempt",
        )

    def common(p: argparse.ArgumentParser) -> None:
        source = p.add_mutually_exclusive_group()
        source.add_argument("--text", help="input text instead of stdin")
        source.add_argument("--file", help="read input from a UTF-8 file")
        output = p.add_mutually_exclusive_group()
        output.add_argument("--json", action="store_true", help="emit stable JSON")
        output.add_argument("--quiet", action="store_true", help="emit no output")
        p.add_argument("--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES)
        provider_options(p)

    pred = sub.add_parser("is", help="evaluate a semantic predicate")
    pred.add_argument("criterion")
    pred.add_argument("--threshold", type=_bounded_probability, default=0.70)
    pred.add_argument("--uncertainty-margin", type=_bounded_probability, default=0.05)
    common(pred)

    choice = sub.add_parser("choose", help="choose among named semantic options")
    choice.add_argument(
        "criterion", nargs="?", default="Which option best describes the input?"
    )
    choice.add_argument(
        "--option", action="append", required=True, metavar="NAME=DESCRIPTION"
    )
    choice.add_argument("--min-confidence", type=_bounded_probability, default=0.50)
    common(choice)

    scoring = sub.add_parser("score", help="score input against ordered levels")
    scoring.add_argument(
        "--criterion", default="Which ordered level best describes the input?"
    )
    scoring.add_argument("--level", action="append", required=True)
    scoring.add_argument("--min-confidence", type=_bounded_probability, default=0.50)
    common(scoring)

    filtering = sub.add_parser(
        "filter", help="filter JSONL records using a semantic predicate"
    )
    filtering.add_argument("criterion")
    filtering.add_argument("--field")
    filtering.add_argument("--threshold", type=_bounded_probability, default=0.70)
    filtering.add_argument(
        "--uncertainty-margin", type=_bounded_probability, default=0.05
    )
    filtering.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    filtering.add_argument(
        "--raw", action="store_true", help="omit _semdecide metadata"
    )
    filtering.add_argument(
        "--jsonl", action="store_true", help="emit JSONL (the default)"
    )
    common(filtering)

    evaluation = sub.add_parser(
        "evaluate", help="evaluate caller-defined questions without policy"
    )
    evaluation.add_argument(
        "--request",
        default="-",
        metavar="FILE",
        help="JSON request file, or - for stdin (default)",
    )
    evaluation.add_argument(
        "--schema",
        action="store_true",
        help="print the request JSON Schema without calling a provider",
    )
    evaluation_output = evaluation.add_mutually_exclusive_group()
    evaluation_output.add_argument(
        "--json", action="store_true", default=True, help="emit JSON (the default)"
    )
    evaluation_output.add_argument("--quiet", action="store_true")
    evaluation.add_argument(
        "--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES
    )
    provider_options(evaluation)

    recipes = sub.add_parser("recipe", help="run built-in or declarative JSON recipes")
    recipe_sub = recipes.add_subparsers(dest="recipe_command", required=True)
    recipe_run = recipe_sub.add_parser(
        "run", help="run guard, a recipe file, or a locally/user-installed name"
    )
    recipe_run.add_argument("name", help="guard, a JSON path, or a recipe name")
    common(recipe_run)
    recipe_run.set_defaults(json=True)
    recipe_run.add_argument(
        "--state-json",
        action="store_true",
        help="decode the input as a JSON value instead of text",
    )
    recipe_run.add_argument("--action", help="built-in guard only")
    recipe_run.add_argument("--context", default="", help="built-in guard only")
    recipe_schema = recipe_sub.add_parser(
        "schema", help="print the declarative recipe JSON Schema"
    )
    recipe_schema.add_argument("--quiet", action="store_true")
    recipe_schema.set_defaults(json=True)

    for name, deprecated in (("guard", False), ("check", True)):
        guard = sub.add_parser(
            name,
            help="evaluate an agent action" + (" (deprecated)" if deprecated else ""),
        )
        guard.add_argument("--action")
        guard.add_argument("--context", default="")
        guard.add_argument("--json", action="store_true")
        guard.add_argument("--quiet", action="store_true")
        guard.add_argument(
            "--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES
        )
        provider_options(guard)
    return parser


def _options(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise InputError("--option must use NAME=DESCRIPTION")
        name, description = value.split("=", 1)
        if not name or not description or name in result:
            raise InputError(
                "option names and descriptions must be non-empty and unique"
            )
        result[name] = description
    if not 2 <= len(result) <= 255:
        raise InputError("choose requires between 2 and 255 options")
    return result


def _emit(value: Any, *, machine: bool, quiet: bool, stdout: TextIO) -> None:
    if quiet:
        return
    if machine:
        print(
            json.dumps(
                value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ),
            file=stdout,
        )
    else:
        for line in value if isinstance(value, list) else [value]:
            print(line, file=stdout)


def _emit_error(
    kind: str, message: str, *, args: argparse.Namespace, stderr: TextIO
) -> None:
    if getattr(args, "quiet", False):
        return
    if getattr(args, "json", False):
        payload = {
            "schema_version": SCHEMA_VERSION,
            "command": args.command,
            "error": {"kind": kind, "message": message},
        }
        print(
            json.dumps(
                payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ),
            file=stderr,
        )
    else:
        prefix = "provider error: " if kind == "provider_error" else ""
        print(f"semdecide: {prefix}{message}", file=stderr)


def _evaluator(args: argparse.Namespace) -> Evaluate:
    if args.provider == "typesafe":
        return TypeSafeProvider(timeout=args.timeout, retries=args.retries).evaluate
    return partial(evaluate_openrouter, timeout=args.timeout)


def _read(args: argparse.Namespace, stdin: BinaryIO) -> str:
    return read_input(
        text=getattr(args, "text", None),
        file=getattr(args, "file", None),
        stdin=stdin,
        max_bytes=args.max_input_bytes,
    )


def _guard_input(args: argparse.Namespace, stdin: BinaryIO) -> tuple[str, str]:
    if args.action:
        if args.max_input_bytes <= 0:
            raise InputError("--max-input-bytes must be positive")
        submitted_bytes = len(args.action.encode("utf-8")) + len(
            args.context.encode("utf-8")
        )
        if submitted_bytes > args.max_input_bytes:
            raise InputError(
                f"combined action and context exceed --max-input-bytes ({args.max_input_bytes})"
            )
        return args.action, args.context
    text = read_input(text=None, file=None, stdin=stdin, max_bytes=args.max_input_bytes)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"stdin is not valid JSON: {exc.msg}") from exc
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("action"), str)
        or not value["action"].strip()
    ):
        raise InputError("stdin JSON must contain a non-empty string action")
    context = value.get("context", args.context)
    if not isinstance(context, str):
        raise InputError("context must be a string")
    return value["action"], context


def main(
    argv: list[str] | None = None,
    *,
    provider: Provider | None = None,
    stdin: BinaryIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    load_dotenv(".env")
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    argument_values = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = _parser().parse_args(argument_values)
    except InputError as exc:
        command = next(
            (
                value
                for value in argument_values
                if value
                in {
                    "is",
                    "choose",
                    "score",
                    "filter",
                    "guard",
                    "check",
                    "evaluate",
                    "recipe",
                }
            ),
            None,
        )
        error_args = argparse.Namespace(
            command=command,
            json="--json" in argument_values or command in {"evaluate", "recipe"},
            quiet="--quiet" in argument_values,
        )
        _emit_error("input_error", str(exc), args=error_args, stderr=stderr)
        return EXIT_USAGE
    if args.command == "check" and not args.quiet:
        print("semdecide: warning: 'check' is deprecated; use 'guard'", file=stderr)
    try:
        if args.command == "evaluate" and args.schema:
            _emit(
                EvaluationRequest.model_json_schema(),
                machine=True,
                quiet=args.quiet,
                stdout=stdout,
            )
            return 0
        if args.command == "recipe" and args.recipe_command == "schema":
            _emit(
                Recipe.model_json_schema(),
                machine=True,
                quiet=args.quiet,
                stdout=stdout,
            )
            return 0

        evaluate = provider.evaluate if provider is not None else _evaluator(args)
        is_guard_recipe = args.command == "recipe" and args.name == "guard"
        if args.command in ("guard", "check") or is_guard_recipe:
            if is_guard_recipe and (
                args.text is not None or args.file is not None or args.state_json
            ):
                raise InputError(
                    "guard accepts --action/--context or a JSON action object on stdin"
                )
            action, context = _guard_input(args, stdin)
            decision = run_guard(action, context, evaluator=evaluate)
            payload = {
                "schema_version": SCHEMA_VERSION,
                "command": "guard",
                **decision.as_dict(),
            }
            _emit(
                payload
                if args.json
                else [
                    f"{decision.route.upper()}: {decision.reason}",
                    *[f"{k}={v}" for k, v in decision.signals.items() if v is not None],
                ],
                machine=args.json,
                quiet=args.quiet,
                stdout=stdout,
            )
            return GUARD_EXIT_CODES[decision.route]

        if args.command == "evaluate":
            text = read_input(
                text=None,
                file=None if args.request == "-" else args.request,
                stdin=stdin,
                max_bytes=args.max_input_bytes,
            )
            request = EvaluationRequest.model_validate_json(text)
            result = evaluate_questions(
                state=request.state,
                questions=request.questions,
                evaluator=evaluate,
            )
            payload = {
                "schema_version": SCHEMA_VERSION,
                "command": "evaluate",
                **result.model_dump(mode="json"),
            }
            _emit(payload, machine=True, quiet=args.quiet, stdout=stdout)
            return 0

        if args.command == "recipe":
            if args.action is not None or args.context:
                raise InputError(
                    "--action and --context are only supported by the guard recipe"
                )
            recipe = load_recipe(args.name, max_bytes=args.max_input_bytes)
            text = _read(args, stdin)
            if args.state_json:
                try:
                    state = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise InputError(f"state is not valid JSON: {exc.msg}") from exc
            else:
                state = text
            result = recipe.run(state, evaluator=evaluate)
            payload = {
                "schema_version": SCHEMA_VERSION,
                "command": "recipe",
                "recipe": recipe.name,
                **result.model_dump(mode="json"),
            }
            _emit(payload, machine=True, quiet=args.quiet, stdout=stdout)
            return 0

        text = _read(args, stdin)
        if args.command == "is":
            result, _ = predicate(evaluate, text, args.criterion)
            uncertain = (
                abs(result.probability - args.threshold) < args.uncertainty_margin
            )
            verdict = (
                "uncertain"
                if uncertain
                else "true"
                if result.probability >= args.threshold
                else "false"
            )
            payload = {
                "schema_version": SCHEMA_VERSION,
                "command": "is",
                "verdict": verdict,
                "probability": result.probability,
                "confidence": None,
                "threshold": args.threshold,
                "model": result.model,
                "usage": result.usage.as_dict(),
            }
            _emit(
                payload
                if args.json
                else f"{verdict.upper()} probability={result.probability:.3f} threshold={args.threshold:.3f}",
                machine=args.json,
                quiet=args.quiet,
                stdout=stdout,
            )
            return (
                EXIT_UNCERTAIN if uncertain else 0 if verdict == "true" else EXIT_FALSE
            )

        if args.command == "choose":
            options = _options(args.option)
            result, _ = choose(evaluate, text, args.criterion, options)
            uncertain = result.confidence < args.min_confidence
            payload = {
                "schema_version": SCHEMA_VERSION,
                "command": "choose",
                "choice": result.choice,
                "probabilities": dict(result.probabilities),
                "confidence": result.confidence,
                "min_confidence": args.min_confidence,
                "uncertain": uncertain,
                "model": result.model,
                "usage": result.usage.as_dict(),
            }
            _emit(
                payload
                if args.json
                else f"{result.choice} confidence={result.confidence:.3f}"
                + (" UNCERTAIN" if uncertain else ""),
                machine=args.json,
                quiet=args.quiet,
                stdout=stdout,
            )
            return EXIT_UNCERTAIN if uncertain else 0

        if args.command == "score":
            if not 2 <= len(args.level) <= 255:
                raise InputError("score requires between 2 and 255 levels")
            result, _ = score(evaluate, text, args.criterion, args.level)
            uncertain = result.confidence < args.min_confidence
            payload = {
                "schema_version": SCHEMA_VERSION,
                "command": "score",
                "score": result.score,
                "levels": args.level,
                "probabilities": list(result.probabilities),
                "confidence": result.confidence,
                "min_confidence": args.min_confidence,
                "uncertain": uncertain,
                "model": result.model,
                "usage": result.usage.as_dict(),
            }
            _emit(
                payload
                if args.json
                else f"score={result.score:.3f} confidence={result.confidence:.3f}"
                + (" UNCERTAIN" if uncertain else ""),
                machine=args.json,
                quiet=args.quiet,
                stdout=stdout,
            )
            return EXIT_UNCERTAIN if uncertain else 0

        records = parse_jsonl(text, max_records=args.max_records)
        evaluated, model, usage, _ = filter_records(
            evaluate, records, args.criterion, args.field
        )
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
                output["_semdecide"] = {
                    "schema_version": SCHEMA_VERSION,
                    "probability": probability,
                    "threshold": args.threshold,
                    "model": model,
                }
            if not args.quiet:
                print(
                    json.dumps(
                        output,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    file=stdout,
                )
        if uncertain_count:
            return EXIT_UNCERTAIN
        return 0 if selected else EXIT_FALSE
    except ValidationError:
        # Pydantic diagnostics can contain the submitted state or instructions.
        _emit_error(
            "input_error",
            "request or question definition does not match the schema",
            args=args,
            stderr=stderr,
        )
        return EXIT_USAGE
    except (InputError, ValueError) as exc:
        _emit_error("input_error", str(exc), args=args, stderr=stderr)
        return EXIT_USAGE
    except ProviderError:
        _emit_error("provider_error", SAFE_PROVIDER_MESSAGE, args=args, stderr=stderr)
        return EXIT_PROVIDER


if __name__ == "__main__":
    raise SystemExit(main())
