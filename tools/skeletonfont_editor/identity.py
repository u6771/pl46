from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from skeletonfont.errors import ProjectDataError
from skeletonfont.model import GlyphSource


_SAFE_GLYPH_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_UNICODE_NAME_RE = re.compile(r"uni([0-9A-Fa-f]{4,6})")
_BARE_UNICODE_RE = re.compile(r"([0-9A-Fa-f]{4,6})")


@dataclass(frozen=True, slots=True)
class GlyphIdentity:
    name: str
    codepoint: int | None


def glyph_filename(name: str, codepoint: int | None) -> str:
    if _SAFE_GLYPH_NAME_RE.fullmatch(name) is None:
        raise ProjectDataError(f"Unsupported glyph name: {name!r}.")
    if codepoint is None:
        return f"{name}.json"
    return f"{name}_{codepoint:04X}.json"


class GlyphIdentityMap:
    """Resolve immutable glyph names and Unicode values from an identity map."""

    def __init__(self, identities: Mapping[str, int | None]) -> None:
        self.identities = MappingProxyType(dict(identities))
        names_by_codepoint: dict[int, str] = {}
        for name, codepoint in self.identities.items():
            if codepoint is not None:
                names_by_codepoint.setdefault(codepoint, name)
        self.names_by_codepoint = MappingProxyType(names_by_codepoint)

    @classmethod
    def load(cls, path: Path) -> GlyphIdentityMap:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ProjectDataError(f"Cannot read glyph-name map {path}: {error}") from error
        except json.JSONDecodeError as error:
            raise ProjectDataError(
                f"Invalid JSON in glyph-name map {path}: {error}"
            ) from error
        if not isinstance(raw, dict):
            raise ProjectDataError(f"{path} must contain a JSON object.")

        identities: dict[str, int | None] = {}
        for name, unicode_value in raw.items():
            if (
                not isinstance(name, str)
                or _SAFE_GLYPH_NAME_RE.fullmatch(name) is None
            ):
                raise ProjectDataError(
                    f"{path} contains an invalid glyph name: {name!r}."
                )
            if unicode_value is None:
                codepoint = None
            elif isinstance(unicode_value, str):
                try:
                    codepoint = int(unicode_value, 16)
                except ValueError as error:
                    raise ProjectDataError(
                        f"{path} maps {name!r} to invalid Unicode "
                        f"{unicode_value!r}."
                    ) from error
                if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                    raise ProjectDataError(
                        f"{path} maps {name!r} outside Unicode."
                    )
            else:
                raise ProjectDataError(
                    f"{path} maps {name!r} to a non-string Unicode value."
                )
            identities[name] = codepoint
        return cls(identities)

    def resolve(self, raw_name: str) -> GlyphIdentity | None:
        name = raw_name.strip()
        if name in self.identities:
            return GlyphIdentity(name, self.identities[name])

        match = _UNICODE_NAME_RE.fullmatch(name)
        if match is None:
            match = _BARE_UNICODE_RE.fullmatch(name)
        if match is None:
            return None

        codepoint = int(match.group(1), 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            return None
        canonical_name = self.names_by_codepoint.get(
            codepoint,
            f"uni{codepoint:04X}",
        )
        return GlyphIdentity(canonical_name, codepoint)

    def validate_source(self, source: GlyphSource, path: Path) -> None:
        identity = self.resolve(source.name)
        if identity is None:
            raise ProjectDataError(
                f"Glyph name {source.name!r} is not in the glyph identity map "
                "and is not a valid uniXXXX name."
            )
        if (source.name, source.codepoint) != (
            identity.name,
            identity.codepoint,
        ):
            expected = (
                "unencoded"
                if identity.codepoint is None
                else f"U+{identity.codepoint:04X}"
            )
            raise ProjectDataError(
                f"Glyph {source.name!r} must use {expected} according to the "
                "glyph identity map."
            )
        expected_filename = glyph_filename(identity.name, identity.codepoint)
        if path.name != expected_filename:
            raise ProjectDataError(
                f"Glyph {source.name!r} must be stored as "
                f"{expected_filename!r}, not {path.name!r}."
            )
