from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType
from typing import Mapping

from .errors import AssemblyError


UnicodePair = tuple[int, int]


def _paired_ranges(
    source_start: int,
    source_end: int,
    target_start: int,
) -> Iterable[UnicodePair]:
    return zip(
        range(source_start, source_end),
        range(target_start, target_start + source_end - source_start),
    )


def _italic_latin() -> Iterable[UnicodePair]:
    yield from _paired_ranges(0x0041, 0x005B, 0x1D434)
    yield from _paired_ranges(0x0061, 0x0068, 0x1D44E)
    yield 0x0068, 0x210E
    yield from _paired_ranges(0x0069, 0x007B, 0x1D456)


def _italic_greek() -> Iterable[UnicodePair]:
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


def _fraktur_latin() -> Iterable[UnicodePair]:
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


def _blackboard_latin() -> Iterable[UnicodePair]:
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


def _bold_latin() -> Iterable[UnicodePair]:
    yield from _paired_ranges(0x0041, 0x005B, 0x1D400)
    yield from _paired_ranges(0x0061, 0x007B, 0x1D41A)


def _bold_greek() -> Iterable[UnicodePair]:
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


_PAIR_BUILDERS = {
    "italic_latin": _italic_latin,
    "italic_greek": _italic_greek,
    "fraktur_latin": _fraktur_latin,
    "blackboard_latin": _blackboard_latin,
    "bold_latin": _bold_latin,
    "bold_greek": _bold_greek,
}


def _build_mappings() -> Mapping[str, Mapping[int, int]]:
    mappings: dict[str, Mapping[int, int]] = {}
    for name, builder in _PAIR_BUILDERS.items():
        pairs = dict(builder())
        mappings[name] = MappingProxyType(pairs)
    return MappingProxyType(mappings)


MAPPINGS = _build_mappings()


def get_mapping(name: str) -> Mapping[int, int]:
    """Return one shared, immutable Unicode-to-Unicode mapping."""

    mapping = MAPPINGS.get(name)
    if mapping is None:
        raise AssemblyError(
            f"Unknown glyph mapping {name!r}. Known mappings: "
            f"{sorted(MAPPINGS)}"
        )
    return mapping


def glyph_name_for_codepoint(codepoint: int) -> str:
    """Use the conventional production name for an encoded generated glyph."""

    if codepoint <= 0xFFFF:
        return f"uni{codepoint:04X}"
    return f"u{codepoint:X}"
