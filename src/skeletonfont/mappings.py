from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from .errors import AssemblyError
from .model import UnicodeDomain
from .unicode_domains import UNICODE_DOMAINS


UnicodePair = tuple[int, int | None]
NameMapper = Callable[["GlyphIdentity"], str]


@dataclass(frozen=True, slots=True)
class GlyphIdentity:
    """One glyph's name and optional Unicode identity."""

    name: str
    codepoint: int | None


@dataclass(frozen=True, slots=True)
class GlyphMapping:
    """Map source glyph identities to renamed, optionally encoded targets."""

    codepoints: Mapping[int, int | None]
    rename: NameMapper
    source_domain: str | None = None
    target_domain: str | None = None

    def apply(self, source: GlyphIdentity) -> GlyphIdentity | None:
        codepoint = source.codepoint
        if codepoint is None or codepoint not in self.codepoints:
            return None
        return GlyphIdentity(
            name=self.rename(source),
            codepoint=self.codepoints[codepoint],
        )


def _paired_ranges(
    source_start: int,
    source_end: int,
    target_start: int,
) -> Iterable[UnicodePair]:
    return zip(
        range(source_start, source_end),
        range(target_start, target_start + source_end - source_start),
    )


def _upright_latin_to_italic_latin() -> Iterable[UnicodePair]:
    yield from _paired_ranges(0x0041, 0x005B, 0x1D434)
    yield from _paired_ranges(0x0061, 0x0068, 0x1D44E)
    yield 0x0068, 0x210E
    yield from _paired_ranges(0x0069, 0x007B, 0x1D456)


def _upright_greek_to_italic_greek() -> Iterable[UnicodePair]:
    yield from _paired_ranges(0x0391, 0x03A2, 0x1D6E2)
    yield 0x03F4, 0x1D6F3
    yield from _paired_ranges(0x03A3, 0x03AA, 0x1D6F4)
    yield 0x2207, 0x1D6FB
    yield from _paired_ranges(0x03B1, 0x03CA, 0x1D6FC)
    yield 0x2202, 0x1D715
    yield 0x03F5, 0x1D716
    yield 0x03D1, 0x1D717
    yield 0x03F0, 0x1D718
    yield 0x03D5, 0x1D719
    yield 0x03F1, 0x1D71A
    yield 0x03D6, 0x1D71B


def _upright_latin_to_script_latin() -> Iterable[UnicodePair]:
    yield 0x0041, 0x1D49C
    yield 0x0042, 0x212C
    yield from _paired_ranges(0x0043, 0x0045, 0x1D49E)
    yield 0x0045, 0x2130
    yield 0x0046, 0x2131
    yield 0x0047, 0x1D4A2
    yield 0x0048, 0x210B
    yield 0x0049, 0x2110
    yield from _paired_ranges(0x004A, 0x004C, 0x1D4A5)
    yield 0x004C, 0x2112
    yield 0x004D, 0x2133
    yield from _paired_ranges(0x004E, 0x0052, 0x1D4A9)
    yield 0x0052, 0x211B
    yield from _paired_ranges(0x0053, 0x005B, 0x1D4AE)
    yield from _paired_ranges(0x0061, 0x0065, 0x1D4B6)
    yield 0x0065, 0x212F
    yield 0x0066, 0x1D4BB
    yield 0x0067, 0x210A
    yield from _paired_ranges(0x0068, 0x006E, 0x1D4BD)
    yield 0x006E, 0x1D4C3
    yield 0x006F, 0x2134
    yield from _paired_ranges(0x0070, 0x007B, 0x1D4C5)


def _upright_latin_to_fraktur_latin() -> Iterable[UnicodePair]:
    yield from _paired_ranges(0x0041, 0x0043, 0x1D504)
    yield 0x0043, 0x212D
    yield from _paired_ranges(0x0044, 0x0048, 0x1D507)
    yield 0x0048, 0x210C
    yield 0x0049, 0x2111
    yield from _paired_ranges(0x004A, 0x0052, 0x1D50D)
    yield 0x0052, 0x211C
    yield from _paired_ranges(0x0053, 0x005A, 0x1D516)
    yield 0x005A, 0x2128
    yield from _paired_ranges(0x0061, 0x007B, 0x1D51E)


def _upright_latin_to_blackboard_latin() -> Iterable[UnicodePair]:
    yield from _paired_ranges(0x0041, 0x0043, 0x1D538)
    yield 0x0043, 0x2102
    yield from _paired_ranges(0x0044, 0x0048, 0x1D53B)
    yield 0x0048, 0x210D
    yield from _paired_ranges(0x0049, 0x004E, 0x1D540)
    yield 0x004E, 0x2115
    yield 0x004F, 0x1D546
    yield 0x0050, 0x2119
    yield 0x0051, 0x211A
    yield 0x0052, 0x211D
    yield from _paired_ranges(0x0053, 0x005A, 0x1D54A)
    yield 0x005A, 0x2124
    yield from _paired_ranges(0x0061, 0x007B, 0x1D552)


def _upright_latin_to_bold_latin() -> Iterable[UnicodePair]:
    yield from _paired_ranges(0x0041, 0x005B, 0x1D400)
    yield from _paired_ranges(0x0061, 0x007B, 0x1D41A)


def _upright_greek_to_bold_greek() -> Iterable[UnicodePair]:
    yield from _paired_ranges(0x0391, 0x03A2, 0x1D6A8)
    yield 0x03F4, 0x1D6B9
    yield from _paired_ranges(0x03A3, 0x03AA, 0x1D6BA)
    yield 0x2207, 0x1D6C1
    yield from _paired_ranges(0x03B1, 0x03CA, 0x1D6C2)
    yield 0x2202, 0x1D6DB
    yield 0x03F5, 0x1D6DC
    yield 0x03D1, 0x1D6DD
    yield 0x03F0, 0x1D6DE
    yield 0x03D5, 0x1D6DF
    yield 0x03F1, 0x1D6E0
    yield 0x03D6, 0x1D6E1
    yield 0x03DC, 0x1D7CA
    yield 0x03DD, 0x1D7CB


def _styled_name(style: str) -> NameMapper:
    def rename(source: GlyphIdentity) -> str:
        return f"{source.name}.{style}"

    return rename


_MAPPING_DEFINITIONS = {
    "upright_latin_to_italic_latin": (
        _upright_latin_to_italic_latin,
        _styled_name("italic"),
        "upright_latin",
        "italic_latin",
    ),
    "upright_greek_to_italic_greek": (
        _upright_greek_to_italic_greek,
        _styled_name("italic"),
        "upright_greek",
        "italic_greek",
    ),
    "upright_latin_to_script_latin": (
        _upright_latin_to_script_latin,
        _styled_name("script"),
        "upright_latin",
        "script_latin",
    ),
    "upright_latin_to_fraktur_latin": (
        _upright_latin_to_fraktur_latin,
        _styled_name("fraktur"),
        "upright_latin",
        "fraktur_latin",
    ),
    "upright_latin_to_blackboard_latin": (
        _upright_latin_to_blackboard_latin,
        _styled_name("blackboard"),
        "upright_latin",
        "blackboard_latin",
    ),
    "upright_latin_to_bold_latin": (
        _upright_latin_to_bold_latin,
        _styled_name("bold"),
        "upright_latin",
        "bold_latin",
    ),
    "upright_greek_to_bold_greek": (
        _upright_greek_to_bold_greek,
        _styled_name("bold"),
        "upright_greek",
        "bold_greek",
    ),
}


def _domain_for_mapping(
    mapping_name: str,
    domain_name: str,
    *,
    side: str,
) -> UnicodeDomain:
    domain = UNICODE_DOMAINS.get(domain_name)
    if domain is None:
        raise ValueError(
            f"Mapping {mapping_name!r} references unknown {side} "
            f"domain {domain_name!r}."
        )
    return domain


def _format_codepoints(codepoints: Iterable[int]) -> list[str]:
    return [f"U+{value:04X}" for value in sorted(codepoints)]


def _validate_mapping_domains(
    name: str,
    mapping: GlyphMapping,
) -> None:
    if mapping.source_domain is not None:
        source_domain = _domain_for_mapping(
            name,
            mapping.source_domain,
            side="source",
        )
        invalid_sources = [
            codepoint
            for codepoint in mapping.codepoints
            if codepoint not in source_domain
        ]
        if invalid_sources:
            raise ValueError(
                f"Mapping {name!r} has source codepoints outside domain "
                f"{mapping.source_domain!r}: "
                f"{_format_codepoints(invalid_sources)}"
            )

    if mapping.target_domain is not None:
        target_domain = _domain_for_mapping(
            name,
            mapping.target_domain,
            side="target",
        )
        invalid_targets = [
            codepoint
            for codepoint in mapping.codepoints.values()
            if codepoint is not None and codepoint not in target_domain
        ]
        if invalid_targets:
            raise ValueError(
                f"Mapping {name!r} has target codepoints outside domain "
                f"{mapping.target_domain!r}: "
                f"{_format_codepoints(invalid_targets)}"
            )


def _build_mappings() -> Mapping[str, GlyphMapping]:
    mappings: dict[str, GlyphMapping] = {}
    for name, (
        builder,
        rename,
        source_domain,
        target_domain,
    ) in _MAPPING_DEFINITIONS.items():
        mapping = GlyphMapping(
            codepoints=MappingProxyType(dict(builder())),
            rename=rename,
            source_domain=source_domain,
            target_domain=target_domain,
        )
        _validate_mapping_domains(name, mapping)
        mappings[name] = mapping
    return MappingProxyType(mappings)


MAPPINGS = _build_mappings()


def get_mapping(name: str) -> GlyphMapping:
    """Return one shared, immutable glyph-identity mapping."""

    mapping = MAPPINGS.get(name)
    if mapping is None:
        raise AssemblyError(
            f"Unknown glyph mapping {name!r}. Known mappings: "
            f"{sorted(MAPPINGS)}"
        )
    return mapping
