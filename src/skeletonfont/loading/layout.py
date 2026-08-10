from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Mapping, cast

from ..errors import ProjectDataError
from ..model import (
    GlyphAdjustment,
    GlyphAdjustmentGroup,
    GlyphAdjustmentSelector,
    GlyphSpacingAdjustment,
    KerningData,
    KerningPair,
    SstyData,
)
from ..opentype import FWORD_MAX, FWORD_MIN
from ._json import (
    _array,
    _number,
    _object,
    _reject_unknown_fields,
    _safe_name,
    normalize_json_filename,
    read_json,
)


_KERNING_FIELDS = {
    "groups",
    "pairs",
}

_GLYPH_CONFIG_FIELDS = {
    "left_adjustment",
    "right_adjustment",
}

_GLYPH_CONFIG_GROUP_KINDS = {
    "variant_glyphs",
    "parts",
    "variants",
}


def parse_ssty(
    value: object,
    *,
    source_path: Path,
) -> Mapping[str, tuple[str, ...]]:
    """Parse one- or two-level mathematical script alternates."""

    data = _object(value, location=str(source_path))
    if not data:
        raise ProjectDataError(f"{source_path} cannot be empty.")

    result: dict[str, tuple[str, ...]] = {}
    for raw_base, raw_alternates in data.items():
        base = _safe_name(raw_base, location=f"{source_path} glyph name")
        location = f"{source_path}.{base}"
        items = _array(raw_alternates, location=location)
        if not 1 <= len(items) <= 2:
            raise ProjectDataError(
                f"{location} must contain one or two alternate glyphs."
            )
        alternates = tuple(
            _safe_name(item, location=f"{location}[{index}]")
            for index, item in enumerate(items)
        )
        if base in alternates:
            raise ProjectDataError(
                f"{location} must not repeat its base glyph."
            )
        if len(alternates) != len(set(alternates)):
            raise ProjectDataError(
                f"{location} contains duplicate alternate glyphs."
            )
        result[base] = alternates
    return MappingProxyType(result)


def load_ssty_data(
    project_directory: Path,
    filename: str,
) -> SstyData:
    """Load explicit GSUB ssty substitutions."""

    source_path = project_directory / "data" / "ssty" / filename
    return SstyData(
        source_path=source_path,
        substitutions=parse_ssty(
            read_json(source_path),
            source_path=source_path,
        ),
    )


def parse_kerning_data(
    value: object,
    *,
    source_path: Path,
) -> KerningData:
    """Parse one kerning file without resolving its glyph references."""

    location = str(source_path)
    data = _object(value, location=location)
    _reject_unknown_fields(data, _KERNING_FIELDS, location=location)

    raw_groups = _object(
        data.get("groups", {}),
        location=f"{location}.groups",
    )
    groups: dict[str, tuple[str, ...]] = {}
    group_by_member_and_side: dict[tuple[int, str], str] = {}
    for raw_name, raw_members in raw_groups.items():
        name = _safe_name(
            raw_name,
            location=f"{location}.groups key",
        )
        if name.startswith("public.kern1."):
            side = 1
        elif name.startswith("public.kern2."):
            side = 2
        else:
            raise ProjectDataError(
                f"{location}.groups.{name} must use a public.kern1.* "
                "or public.kern2.* kerning-group name."
            )
        members = tuple(
            _safe_name(
                member,
                location=f"{location}.groups.{name}[{index}]",
            )
            for index, member in enumerate(
                _array(
                    raw_members,
                    location=f"{location}.groups.{name}",
                )
            )
        )
        if len(members) != len(set(members)):
            raise ProjectDataError(
                f"{location}.groups.{name} contains duplicate glyphs."
            )
        for member in members:
            key = (side, member)
            previous = group_by_member_and_side.get(key)
            if previous is not None:
                raise ProjectDataError(
                    f"{location} places glyph {member!r} in multiple "
                    f"side-{side} kerning groups: {previous!r} and "
                    f"{name!r}."
                )
            group_by_member_and_side[key] = name
        groups[name] = members

    pairs: list[KerningPair] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, raw_pair in enumerate(
        _array(data.get("pairs", []), location=f"{location}.pairs")
    ):
        pair = _array(raw_pair, location=f"{location}.pairs[{index}]")
        if len(pair) != 3:
            raise ProjectDataError(
                f"{location}.pairs[{index}] must contain "
                "[left, right, value]."
            )
        left = _safe_name(
            pair[0],
            location=f"{location}.pairs[{index}][0]",
        )
        right = _safe_name(
            pair[1],
            location=f"{location}.pairs[{index}][1]",
        )
        if left in groups and not left.startswith("public.kern1."):
            raise ProjectDataError(
                f"{location}.pairs[{index}] uses right-side group "
                f"{left!r} on the left."
            )
        if right in groups and not right.startswith("public.kern2."):
            raise ProjectDataError(
                f"{location}.pairs[{index}] uses left-side group "
                f"{right!r} on the right."
            )
        key = (left, right)
        if key in seen_pairs:
            raise ProjectDataError(
                f"{location}.pairs contains duplicate pair {key!r}."
            )
        seen_pairs.add(key)
        pairs.append(
            KerningPair(
                left=left,
                right=right,
                value=_number(
                    pair[2],
                    location=f"{location}.pairs[{index}][2]",
                    minimum=FWORD_MIN,
                    maximum=FWORD_MAX,
                ),
            )
        )

    return KerningData(
        source_path=source_path,
        groups=MappingProxyType(groups),
        pairs=tuple(pairs),
    )


def load_kerning_data(
    project_directory: Path,
    filename: object,
) -> KerningData:
    name = normalize_json_filename(filename, location="Kerning filename")
    path = project_directory / "data" / "kerning" / name
    return parse_kerning_data(read_json(path), source_path=path)


def parse_accent_glyphs(
    value: object,
    *,
    source_path: Path,
) -> frozenset[str]:
    """Parse the glyphs that use combining-accent metrics."""

    items = _array(value, location=str(source_path))
    if not items:
        raise ProjectDataError(f"{source_path} cannot be empty.")
    names = tuple(
        _safe_name(item, location=f"{source_path}[{index}]")
        for index, item in enumerate(items)
    )
    if len(names) != len(set(names)):
        raise ProjectDataError(f"{source_path} contains duplicate glyph names.")
    return frozenset(names)


def load_accent_glyphs(
    project_directory: Path,
    filename: str,
) -> frozenset[str]:
    path = project_directory / "data" / "accent" / filename
    return parse_accent_glyphs(read_json(path), source_path=path)


def parse_glyph_config(
    value: object,
    *,
    source_path: Path,
) -> Mapping[GlyphAdjustmentSelector, GlyphAdjustment]:
    """Parse build-time adjustments selected by glyph or MATH group."""

    raw = _object(value, location=str(source_path))
    result: dict[GlyphAdjustmentSelector, GlyphAdjustment] = {}

    for raw_name, raw_adjustment in raw.items():
        if not isinstance(raw_name, str):
            raise ProjectDataError(
                f"{source_path} glyph config key must be a string."
            )
        if "@" not in raw_name:
            base_name = _safe_name(
                raw_name,
                location=f"{source_path} glyph name",
            )
            selector = GlyphAdjustmentSelector(base_name, None)
        else:
            if raw_name.count("@") != 1:
                raise ProjectDataError(
                    f"{source_path} glyph selector {raw_name!r} must contain "
                    "exactly one '@'."
                )
            base, group_kind = raw_name.split("@")
            _safe_name(base, location=f"{source_path} selector base")
            if group_kind not in _GLYPH_CONFIG_GROUP_KINDS:
                raise ProjectDataError(
                    f"{source_path} glyph selector {raw_name!r} has unknown "
                    f"group kind {group_kind!r}."
                )
            selector = GlyphAdjustmentSelector(
                base,
                cast(GlyphAdjustmentGroup, group_kind),
            )
        location = f"{source_path}.{raw_name}"
        adjustment = _object(raw_adjustment, location=location)
        _reject_unknown_fields(
            adjustment,
            _GLYPH_CONFIG_FIELDS,
            location=location,
        )
        if not adjustment:
            raise ProjectDataError(f"{location} has no adjustment.")
        result[selector] = GlyphAdjustment(
            spacing=GlyphSpacingAdjustment(
                left=(
                    None
                    if "left_adjustment" not in adjustment
                    else _number(
                        adjustment["left_adjustment"],
                        location=f"{location}.left_adjustment",
                    )
                ),
                right=(
                    None
                    if "right_adjustment" not in adjustment
                    else _number(
                        adjustment["right_adjustment"],
                        location=f"{location}.right_adjustment",
                    )
                ),
            )
        )

    return MappingProxyType(result)


def load_glyph_config(
    project_directory: Path,
    filename: str,
) -> Mapping[GlyphAdjustmentSelector, GlyphAdjustment]:
    """Load glyph adjustments from one config file."""

    normalized_filename = normalize_json_filename(
        filename,
        location="Glyph config filename",
    )
    path = project_directory / "data" / "glyph_config" / normalized_filename
    return parse_glyph_config(
        read_json(path),
        source_path=path,
    )
