from __future__ import annotations

import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence, cast

from ..errors import ProjectDataError
from ..model import UnicodeDomain, UnicodeRange
from ..opentype import FWORD_MAX, FWORD_MIN, UFWORD_MAX
from ..unicode_domains import UNICODE_DOMAINS, normalize_unicode_ranges


_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")


class _DuplicateJsonKeyError(ValueError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


def read_json(path: Path) -> object:
    """Read JSON and attach its path to decoding and I/O errors."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ProjectDataError(
            f"Cannot read {path}: {error}"
        ) from error

    try:
        return json.loads(text, object_pairs_hook=_unique_json_object)
    except _DuplicateJsonKeyError as error:
        raise ProjectDataError(
            f"Invalid JSON in {path}: duplicate object key "
            f"{error.key!r}."
        ) from error
    except json.JSONDecodeError as error:
        raise ProjectDataError(
            f"Invalid JSON in {path} at "
            f"line {error.lineno}, column {error.colno}: "
            f"{error.msg}"
        ) from error


def _object(value: object, *, location: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ProjectDataError(
            f"{location} must be a JSON object."
        )
    return cast(Mapping[str, object], value)


def _array(value: object, *, location: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ProjectDataError(
            f"{location} must be a JSON array."
        )
    return cast(Sequence[object], value)


def _reject_unknown_fields(
    data: Mapping[str, object],
    allowed: set[str],
    *,
    location: str,
) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ProjectDataError(
            f"{location} has unknown fields: "
            f"{sorted(unknown)}"
        )


def _string(value: object, *, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectDataError(
            f"{location} must be a non-empty string."
        )
    return value.strip()


def _boolean(value: object, *, location: str) -> bool:
    if not isinstance(value, bool):
        raise ProjectDataError(
            f"{location} must be true or false."
        )
    return value


def _number(
    value: object,
    *,
    location: str,
    minimum: float | None = None,
    maximum: float | None = None,
    positive: bool = False,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProjectDataError(
            f"{location} must be a finite number."
        )

    try:
        result = float(value)
    except OverflowError as error:
        raise ProjectDataError(
            f"{location} must be a finite number."
        ) from error
    if not math.isfinite(result):
        raise ProjectDataError(
            f"{location} must be a finite number."
        )
    if positive and result <= 0:
        raise ProjectDataError(
            f"{location} must be positive."
        )
    if minimum is not None and result < minimum:
        raise ProjectDataError(
            f"{location} must be at least {minimum}."
        )
    if maximum is not None and result > maximum:
        raise ProjectDataError(
            f"{location} must be at most {maximum}."
        )
    return result


def _integer(value: object, *, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProjectDataError(f"{location} must be an integer.")
    return value


def _bounded_integer(
    value: object,
    *,
    location: str,
    minimum: int,
    maximum: int,
) -> int:
    result = _integer(value, location=location)
    if not minimum <= result <= maximum:
        raise ProjectDataError(
            f"{location} must be between {minimum} and {maximum}."
        )
    return result


def _fword_integer(value: object, *, location: str) -> int:
    return _bounded_integer(
        value,
        location=location,
        minimum=FWORD_MIN,
        maximum=FWORD_MAX,
    )


def _ufword_integer(value: object, *, location: str) -> int:
    return _bounded_integer(
        value,
        location=location,
        minimum=0,
        maximum=UFWORD_MAX,
    )


def _safe_name(value: object, *, location: str) -> str:
    name = _string(value, location=location)
    if _SAFE_NAME_RE.fullmatch(name) is None:
        raise ProjectDataError(
            f"{location} contains unsupported characters: {name!r}."
        )
    return name


def _relative_directory(value: object, *, location: str) -> str:
    raw = _string(value, location=location).replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") for part in path.parts)
        or any(_SAFE_NAME_RE.fullmatch(part) is None for part in path.parts)
    ):
        raise ProjectDataError(
            f"{location} must be a safe relative directory: {raw!r}."
        )
    return path.as_posix()


def normalize_json_filename(value: object, *, location: str) -> str:
    name = _safe_name(value, location=location)
    if not name.lower().endswith(".json"):
        name += ".json"
    return name


def normalize_meta_name(value: object) -> str:
    name = _safe_name(value, location="Meta name")
    if name.lower().endswith(".json"):
        name = _safe_name(name[:-5], location="Meta name")
    return name


def parse_codepoint(value: object, *, location: str) -> int | None:
    if value is None:
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        codepoint = value
    elif isinstance(value, str):
        text = value.strip()
        if text.upper().startswith("U+"):
            text = text[2:]
        if not text:
            raise ProjectDataError(
                f"{location} cannot be empty."
            )
        try:
            codepoint = int(text, 16)
        except ValueError as error:
            raise ProjectDataError(
                f"{location} is not a hexadecimal Unicode value: "
                f"{value!r}."
            ) from error
    else:
        raise ProjectDataError(
            f"{location} must be a hexadecimal string, integer, or null."
        )

    if not 0 <= codepoint <= 0x10FFFF:
        raise ProjectDataError(
            f"{location} U+{codepoint:X} is outside Unicode."
        )
    if 0xD800 <= codepoint <= 0xDFFF:
        raise ProjectDataError(
            f"{location} U+{codepoint:04X} is a surrogate."
        )
    return codepoint


def _named_unicode_domain(
    value: object,
    *,
    location: str,
) -> UnicodeDomain:
    name = _safe_name(value, location=location)
    domain = UNICODE_DOMAINS.get(name)
    if domain is None:
        raise ProjectDataError(
            f"{location} references unknown Unicode domain {name!r}. "
            f"Known domains: {sorted(UNICODE_DOMAINS)}"
        )
    return domain


def _parse_unicode_domain(
    raw: object | None,
    *,
    location: str,
) -> UnicodeDomain | None:
    if raw is None:
        return None

    if isinstance(raw, str):
        return _named_unicode_domain(raw, location=location)

    ranges: list[UnicodeRange] = []
    for index, item in enumerate(_array(raw, location=location)):
        item_location = f"{location}[{index}]"
        if isinstance(item, str):
            ranges.extend(
                _named_unicode_domain(
                    item,
                    location=item_location,
                ).ranges
            )
            continue

        endpoints = _array(
            item,
            location=item_location,
        )
        if len(endpoints) not in (1, 2):
            raise ProjectDataError(
                f"{item_location} must contain [codepoint] or "
                "[start, end]."
            )
        start = parse_codepoint(
            endpoints[0],
            location=f"{item_location}[0]",
        )
        end = (
            start
            if len(endpoints) == 1
            else parse_codepoint(
                endpoints[1],
                location=f"{item_location}[1]",
            )
        )
        if start is None or end is None:
            raise ProjectDataError(
                f"{item_location} endpoints cannot be null."
            )
        if start > end:
            raise ProjectDataError(
                f"{item_location} descends from "
                f"U+{start:04X} to U+{end:04X}."
            )
        ranges.append((start, end))

    return normalize_unicode_ranges(ranges)
