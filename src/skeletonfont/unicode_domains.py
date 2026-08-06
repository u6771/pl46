from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType
from typing import Mapping

from .model import UnicodeDomain, UnicodeRange


def normalize_unicode_ranges(
    ranges: Iterable[UnicodeRange],
) -> UnicodeDomain:
    """Return the unique minimal closed-range representation of a domain."""

    ordered = sorted(ranges)
    if not ordered:
        return UnicodeDomain(())

    merged: list[UnicodeRange] = []
    current_start, current_end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= current_end + 1:
            current_end = max(current_end, next_end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = next_start, next_end
    merged.append((current_start, current_end))
    return UnicodeDomain(tuple(merged))


_DOMAIN_RANGES: Mapping[str, tuple[UnicodeRange, ...]] = MappingProxyType({
    "ascii_digits": (
        (0x0030, 0x0039),
    ),
    "upright_latin": (
        (0x0041, 0x005A),
        (0x0061, 0x007A),
    ),
    "upright_greek": (
        (0x0391, 0x03A1),
        (0x03A3, 0x03A9),
        (0x03B1, 0x03C9),
        (0x03D1, 0x03D1),
        (0x03D5, 0x03D6),
        (0x03DC, 0x03DD),
        (0x03F0, 0x03F1),
        (0x03F4, 0x03F5),
        (0x2202, 0x2202),
        (0x2207, 0x2207),
    ),
    "italic_latin": (
        (0x210E, 0x210E),
        (0x1D434, 0x1D454),
        (0x1D456, 0x1D467),
    ),
    "italic_greek": (
        (0x1D6E2, 0x1D71B),
    ),
    "script_latin": (
        (0x210A, 0x210B),
        (0x2110, 0x2110),
        (0x2112, 0x2112),
        (0x211B, 0x211B),
        (0x212C, 0x212C),
        (0x212F, 0x2131),
        (0x2133, 0x2134),
        (0x1D49C, 0x1D49C),
        (0x1D49E, 0x1D49F),
        (0x1D4A2, 0x1D4A2),
        (0x1D4A5, 0x1D4A6),
        (0x1D4A9, 0x1D4AC),
        (0x1D4AE, 0x1D4B9),
        (0x1D4BB, 0x1D4BB),
        (0x1D4BD, 0x1D4C3),
        (0x1D4C5, 0x1D4CF),
    ),
    "fraktur_latin": (
        (0x210C, 0x210C),
        (0x2111, 0x2111),
        (0x211C, 0x211C),
        (0x2128, 0x2128),
        (0x212D, 0x212D),
        (0x1D504, 0x1D505),
        (0x1D507, 0x1D50A),
        (0x1D50D, 0x1D514),
        (0x1D516, 0x1D51C),
        (0x1D51E, 0x1D537),
    ),
    "blackboard_latin": (
        (0x2102, 0x2102),
        (0x210D, 0x210D),
        (0x2115, 0x2115),
        (0x2119, 0x211A),
        (0x211D, 0x211D),
        (0x2124, 0x2124),
        (0x1D538, 0x1D539),
        (0x1D53B, 0x1D53E),
        (0x1D540, 0x1D544),
        (0x1D546, 0x1D546),
        (0x1D54A, 0x1D550),
        (0x1D552, 0x1D58B),
    ),
    "bold_latin": (
        (0x1D400, 0x1D433),
    ),
    "bold_greek": (
        (0x1D6A8, 0x1D6E1),
        (0x1D7CA, 0x1D7CB),
    ),
})


UNICODE_DOMAINS: Mapping[str, UnicodeDomain] = MappingProxyType({
    name: normalize_unicode_ranges(ranges)
    for name, ranges in _DOMAIN_RANGES.items()
})
