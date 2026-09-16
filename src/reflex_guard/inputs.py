from __future__ import annotations

import json
from pathlib import Path
from typing import Any, BinaryIO

DEFAULT_MAX_INPUT_BYTES = 1_000_000
DEFAULT_MAX_RECORDS = 1_000


class InputError(ValueError):
    pass


def read_bytes(stream: BinaryIO, *, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        raise InputError("--max-input-bytes must be positive")
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise InputError(f"input exceeds --max-input-bytes ({max_bytes})")
    if b"\x00" in data:
        raise InputError("binary input is not supported")
    return data


def read_input(*, text: str | None, file: str | None, stdin: BinaryIO, max_bytes: int) -> str:
    if max_bytes <= 0:
        raise InputError("--max-input-bytes must be positive")
    if text is not None and file is not None:
        raise InputError("--text and --file cannot be combined")
    if text is not None:
        data = text.encode("utf-8")
        if len(data) > max_bytes:
            raise InputError(f"input exceeds --max-input-bytes ({max_bytes})")
        if "\x00" in text:
            raise InputError("binary input is not supported")
        value = text
    elif file is not None:
        try:
            with Path(file).open("rb") as handle:
                value = read_bytes(handle, max_bytes=max_bytes).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError("input must be valid UTF-8 text") from exc
        except OSError as exc:
            raise InputError(f"cannot read input file: {exc}") from exc
    else:
        try:
            value = read_bytes(stdin, max_bytes=max_bytes).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError("input must be valid UTF-8 text") from exc
    if not value.strip():
        raise InputError("input is empty")
    return value


def parse_jsonl(text: str, *, max_records: int) -> list[dict[str, Any]]:
    if max_records <= 0:
        raise InputError("--max-records must be positive")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if len(records) >= max_records:
            raise InputError(f"input exceeds --max-records ({max_records})")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"line {line_number} is not valid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise InputError(f"line {line_number} must be a JSON object")
        records.append(value)
    if not records:
        raise InputError("input contains no JSONL records")
    return records
