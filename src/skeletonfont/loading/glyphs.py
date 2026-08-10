from __future__ import annotations

import math
from pathlib import Path
from typing import cast

from ..errors import ProjectDataError
from ..model import CapStyle, GlyphSource, Point, StrokeRecord
from ._json import (
    _array,
    _boolean,
    _number,
    _object,
    _reject_unknown_fields,
    _safe_name,
    parse_codepoint,
    read_json,
)


_GLYPH_FIELDS = {
    "name",
    "unicode",
    "monospace_x_offset",
    "y_offset",
    "x_extent",
    "skeleton",
}

_REQUIRED_GLYPH_FIELDS = {
    "name",
    "unicode",
}

_STROKE_FIELDS = {
    "centerline",
    "thickness_scale",
    "start_cap",
    "end_cap",
    "filled",
}


def _parse_cap(value: object, *, location: str) -> CapStyle:
    if value not in ("round", "flat"):
        raise ProjectDataError(
            f"{location} must be 'round' or 'flat'."
        )
    return cast(CapStyle, value)


def _parse_point(value: object, *, location: str) -> Point:
    raw = _array(value, location=location)
    if len(raw) != 2:
        raise ProjectDataError(
            f"{location} must contain [x, y]."
        )
    return (
        _number(raw[0], location=f"{location}[0]"),
        _number(raw[1], location=f"{location}[1]"),
    )


def parse_stroke_record(value: object, *, location: str) -> StrokeRecord:
    data = _object(value, location=location)
    _reject_unknown_fields(data, _STROKE_FIELDS, location=location)

    raw_centerline = _array(
        data.get("centerline"),
        location=f"{location}.centerline",
    )
    if not raw_centerline:
        raise ProjectDataError(
            f"{location}.centerline cannot be empty."
        )
    centerline = tuple(
        _parse_point(point, location=f"{location}.centerline[{index}]")
        for index, point in enumerate(raw_centerline)
    )

    return StrokeRecord(
        centerline=centerline,
        thickness_scale=_number(
            data.get("thickness_scale", 1),
            location=f"{location}.thickness_scale",
            positive=True,
        ),
        start_cap=_parse_cap(
            data.get("start_cap", "round"),
            location=f"{location}.start_cap",
        ),
        end_cap=_parse_cap(
            data.get("end_cap", "round"),
            location=f"{location}.end_cap",
        ),
        filled=_boolean(
            data.get("filled", False),
            location=f"{location}.filled",
        ),
    )


def parse_glyph_source(value: object, *, source_path: Path) -> GlyphSource:
    location = str(source_path)
    data = _object(value, location=location)
    _reject_unknown_fields(data, _GLYPH_FIELDS, location=location)

    missing = _REQUIRED_GLYPH_FIELDS - set(data)
    if missing:
        raise ProjectDataError(
            f"{location} is missing required fields: {sorted(missing)}"
        )

    has_skeleton = "skeleton" in data
    has_x_extent = "x_extent" in data
    if has_skeleton == has_x_extent:
        raise ProjectDataError(
            f"{location} must define exactly one of 'skeleton' and "
            "'x_extent'."
        )

    if has_skeleton:
        missing_offsets = {
            "monospace_x_offset",
            "y_offset",
        } - set(data)
        if missing_offsets:
            raise ProjectDataError(
                f"{location} skeleton glyph is missing required fields: "
                f"{sorted(missing_offsets)}"
            )
        raw_skeleton = _array(
            data["skeleton"],
            location=f"{location}.skeleton",
        )
        if not raw_skeleton:
            raise ProjectDataError(
                f"{location}.skeleton cannot be empty; use x_extent for "
                "a glyph without strokes."
            )
        skeleton = tuple(
            parse_stroke_record(
                record,
                location=f"{location}.skeleton[{index}]",
            )
            for index, record in enumerate(raw_skeleton)
        )
        points = tuple(
            point
            for stroke in skeleton
            for point in stroke.centerline
        )
        if not points:
            raise ProjectDataError(
                f"{location} has a non-empty skeleton with no points."
            )
        x_min = min(point[0] for point in points)
        y_min = min(point[1] for point in points)
        if not math.isclose(x_min, 0, abs_tol=1e-9):
            raise ProjectDataError(
                f"{location} skeleton is not normalized: "
                f"x_min is {x_min}, expected 0."
            )
        if not math.isclose(y_min, 0, abs_tol=1e-9):
            raise ProjectDataError(
                f"{location} skeleton is not normalized: "
                f"y_min is {y_min}, expected 0."
            )
        x_extent = max(point[0] for point in points)
        y_extent: float | None = max(point[1] for point in points)
        monospace_x_offset = _number(
            data["monospace_x_offset"],
            location=f"{location}.monospace_x_offset",
        )
        y_offset = _number(
            data["y_offset"],
            location=f"{location}.y_offset",
        )
    else:
        meaningless_offsets = {
            "monospace_x_offset",
            "y_offset",
        } & set(data)
        if meaningless_offsets:
            raise ProjectDataError(
                f"{location} x_extent-only glyph cannot define fields: "
                f"{sorted(meaningless_offsets)}"
            )
        skeleton = ()
        x_extent = _number(
            data["x_extent"],
            location=f"{location}.x_extent",
            minimum=0,
        )
        y_extent = None
        monospace_x_offset = 0.0
        y_offset = 0.0

    return GlyphSource(
        name=_safe_name(data.get("name"), location=f"{location}.name"),
        codepoint=parse_codepoint(
            data["unicode"],
            location=f"{location}.unicode",
        ),
        monospace_x_offset=monospace_x_offset,
        y_offset=y_offset,
        x_extent=x_extent,
        y_extent=y_extent,
        skeleton=skeleton,
        source_path=source_path,
    )


def load_glyph_source(path: Path) -> GlyphSource:
    return parse_glyph_source(read_json(path), source_path=path)


def load_glyph_source_directory(
    source_directory: Path,
) -> dict[str, GlyphSource]:
    if not source_directory.is_dir():
        raise ProjectDataError(
            f"Glyph source directory does not exist: {source_directory}"
        )

    glyphs: dict[str, GlyphSource] = {}
    unicode_owners: dict[int, GlyphSource] = {}
    for path in sorted(source_directory.rglob("*.json")):
        glyph = load_glyph_source(path)
        if glyph.name in glyphs:
            other = glyphs[glyph.name]
            raise ProjectDataError(
                f"Duplicate glyph name {glyph.name!r} in "
                f"{other.source_path} and {glyph.source_path}."
            )
        if glyph.codepoint is not None and glyph.codepoint in unicode_owners:
            other = unicode_owners[glyph.codepoint]
            raise ProjectDataError(
                f"Unicode U+{glyph.codepoint:04X} belongs to both "
                f"{other.name!r} in {other.source_path} and "
                f"{glyph.name!r} in {glyph.source_path}."
            )
        glyphs[glyph.name] = glyph
        if glyph.codepoint is not None:
            unicode_owners[glyph.codepoint] = glyph

    return glyphs
