from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .errors import ProjectDataError
from .loader import load_glyph_source, parse_glyph_source
from .model import GlyphSource, StrokeRecord


def _normalized_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _stroke_data(stroke: StrokeRecord) -> dict[str, object]:
    data: dict[str, object] = {
        "centerline": [
            [_normalized_number(x), _normalized_number(y)]
            for x, y in stroke.centerline
        ]
    }
    if stroke.thickness_scale != 1:
        data["thickness_scale"] = _normalized_number(
            stroke.thickness_scale
        )
    if stroke.start_cap != "round":
        data["start_cap"] = stroke.start_cap
    if stroke.end_cap != "round":
        data["end_cap"] = stroke.end_cap
    if stroke.filled:
        data["filled"] = True
    return data


def glyph_source_data(source: GlyphSource) -> dict[str, object]:
    """Return one glyph source in canonical field order."""

    has_skeleton = bool(source.skeleton)
    if has_skeleton != (source.y_extent is not None):
        raise ProjectDataError(
            f"Glyph source {source.name!r} has inconsistent skeleton and "
            "y_extent data."
        )

    data: dict[str, object] = {
        "name": source.name,
        "unicode": (
            None
            if source.codepoint is None
            else f"{source.codepoint:04X}"
        ),
        "monospace_x_offset": _normalized_number(
            source.monospace_x_offset
        ),
        "y_offset": _normalized_number(source.y_offset),
    }
    if has_skeleton:
        data["skeleton"] = [_stroke_data(stroke) for stroke in source.skeleton]
    else:
        data["x_extent"] = _normalized_number(source.x_extent)
    return data


def serialize_glyph_source(source: GlyphSource) -> str:
    """Serialize a validated glyph source using the project JSON style."""

    data = glyph_source_data(source)
    skeleton = data.pop("skeleton", None)
    assert skeleton is None or isinstance(skeleton, list)

    lines = ["{"]
    items = tuple(data.items())
    for index, (key, value) in enumerate(items):
        comma = "," if index < len(items) - 1 or skeleton is not None else ""
        lines.append(
            f"  {json.dumps(key)}: "
            f"{json.dumps(value, ensure_ascii=False)}{comma}"
        )

    if skeleton is not None:
        lines.append('  "skeleton": [')
        for record_index, record in enumerate(skeleton):
            assert isinstance(record, dict)
            lines.append("    {")
            items = tuple(record.items())
            for item_index, (key, value) in enumerate(items):
                comma = "," if item_index < len(items) - 1 else ""
                lines.append(
                    f"      {json.dumps(key)}: "
                    f"{json.dumps(value, ensure_ascii=False, separators=(', ', ': '))}"
                    f"{comma}"
                )
            record_comma = "," if record_index < len(skeleton) - 1 else ""
            lines.append(f"    }}{record_comma}")
        lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_glyph_source(source: GlyphSource, path: Path) -> GlyphSource:
    """Validate and atomically write one glyph source."""

    target = path.resolve()
    validated = parse_glyph_source(
        glyph_source_data(source),
        source_path=target,
    )
    text = serialize_glyph_source(validated)
    target.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return validated


__all__ = [
    "glyph_source_data",
    "load_glyph_source",
    "parse_glyph_source",
    "serialize_glyph_source",
    "write_glyph_source",
]
