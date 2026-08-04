from __future__ import annotations

import json
import math
import re
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence, cast

from .errors import ProjectDataError
from .math_schema import MATH_CONSTANT_NAMES
from .model import (
    CapStyle,
    FontInfo,
    FontMeta,
    GlyphAdjustment,
    GlyphAdjustmentGroup,
    GlyphAdjustmentSelector,
    GlyphParameters,
    GlyphSource,
    GlyphSpacingAdjustment,
    KerningData,
    KerningPair,
    MathAssemblyPartData,
    MathTableConfig,
    MathTableData,
    MathGlyphAssemblyData,
    MathGlyphKernData,
    MathKernTableData,
    Point,
    SourceRule,
    SstyData,
    StrokeRecord,
    UnicodeRange,
)


_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_FULL_UNICODE_RANGE: tuple[UnicodeRange, ...] = ((0, 0x10FFFF),)

META_FIELD_ORDER = (
    "family",
    "style",
    "output_stem",
    "units_per_em",
    "ascender",
    "descender",
    "cap_height",
    "x_height",
    "grid",
    "thickness",
    "point_radius_scale",
    "y_shift",
    "use_scaled_edge_thickness",
    "monospace_width",
    "left_spacing",
    "right_spacing",
    "source_rules",
    "glyph_generators",
    "glyph_config_file",
    "accent_file",
    "kerning_file",
    "ssty_file",
    "math_table",
)
_META_FIELDS = set(META_FIELD_ORDER)
_REQUIRED_META_FIELDS = {
    "family",
    "style",
    "units_per_em",
    "ascender",
    "descender",
    "cap_height",
    "x_height",
    "grid",
    "thickness",
    "source_rules",
}

_SOURCE_RULE_FIELDS = {
    "source_directory",
    "unicode_ranges",
    "include_unencoded",
    "replace_existing",
    "mapping_name",
    "thickness_scale",
}

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
    "monospace_x_offset",
    "y_offset",
}

_STROKE_FIELDS = {
    "centerline",
    "thickness_scale",
    "start_cap",
    "end_cap",
    "filled",
}

_MATH_TABLE_FIELDS = {
    "constants_file",
    "variants_file",
    "italics_correction_file",
    "accent_attachment_file",
    "kern_file",
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

_KERNING_FIELDS = {
    "groups",
    "pairs",
}

_MATH_VARIANTS_FIELDS = {
    "min_connector_overlap",
    "vertical",
    "horizontal",
}

_MATH_CONSTRUCTION_FIELDS = {
    "variant_glyphs",
    "italic_correction",
    "parts",
}

_MATH_KERN_CORNERS = {
    "top_right",
    "top_left",
    "bottom_right",
    "bottom_left",
}

_MATH_KERN_TABLE_FIELDS = {
    "correction_height",
    "kern_values",
}

_VERTICAL_ASSEMBLY_PART_FIELDS = {
    "glyph",
    "start_connector_extent",
    "end_connector_extent",
    "bottom_scale",
    "top_scale",
    "extender",
}

_HORIZONTAL_ASSEMBLY_PART_FIELDS = {
    "glyph",
    "start_connector_extent",
    "end_connector_extent",
    "left_scale",
    "right_scale",
    "extender",
}


def read_json(path: Path) -> object:
    """Read JSON and attach its path to decoding and I/O errors."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ProjectDataError(
            f"Cannot read {path}: {error}"
        ) from error

    try:
        return json.loads(text)
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
    positive: bool = False,
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ProjectDataError(
            f"{location} must be a finite number."
        )

    result = float(value)
    if positive and result <= 0:
        raise ProjectDataError(
            f"{location} must be positive."
        )
    if minimum is not None and result < minimum:
        raise ProjectDataError(
            f"{location} must be at least {minimum}."
        )
    return result


def _positive_integer(value: object, *, location: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ProjectDataError(
            f"{location} must be a positive integer."
        )
    return value


def _integer(value: object, *, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProjectDataError(f"{location} must be an integer.")
    return value


def _nonnegative_integer(value: object, *, location: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ProjectDataError(
            f"{location} must be a non-negative integer."
        )
    return value


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
        name = name[:-5]
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


def _parse_unicode_ranges(
    raw: object | None,
    *,
    location: str,
) -> tuple[UnicodeRange, ...]:
    if raw is None:
        return _FULL_UNICODE_RANGE

    ranges: list[UnicodeRange] = []
    for index, item in enumerate(
        _array(raw, location=location)
    ):
        pair = _array(
            item,
            location=f"{location}[{index}]",
        )
        if len(pair) != 2:
            raise ProjectDataError(
                f"{location}[{index}] must contain [start, end]."
            )
        start = parse_codepoint(
            pair[0],
            location=f"{location}[{index}][0]",
        )
        end = parse_codepoint(
            pair[1],
            location=f"{location}[{index}][1]",
        )
        if start is None or end is None:
            raise ProjectDataError(
                f"{location}[{index}] endpoints cannot be null."
            )
        if start > end:
            raise ProjectDataError(
                f"{location}[{index}] descends from "
                f"U+{start:04X} to U+{end:04X}."
            )
        ranges.append((start, end))

    if not ranges:
        raise ProjectDataError(
            f"{location} cannot be empty."
        )
    return tuple(ranges)


def _parse_source_rule(
    value: object,
    *,
    location: str,
) -> SourceRule:
    data = _object(value, location=location)
    _reject_unknown_fields(
        data,
        _SOURCE_RULE_FIELDS,
        location=location,
    )

    mapping_value = data.get("mapping_name")
    mapping_name = (
        None
        if mapping_value is None
        else _safe_name(
            mapping_value,
            location=f"{location}.mapping_name",
        )
    )
    return SourceRule(
        source_directory=_relative_directory(
            data.get("source_directory"),
            location=f"{location}.source_directory",
        ),
        unicode_ranges=_parse_unicode_ranges(
            data.get("unicode_ranges"),
            location=f"{location}.unicode_ranges",
        ),
        include_unencoded=_boolean(
            data.get("include_unencoded", False),
            location=f"{location}.include_unencoded",
        ),
        replace_existing=_boolean(
            data.get("replace_existing", False),
            location=f"{location}.replace_existing",
        ),
        mapping_name=mapping_name,
        thickness_scale=_number(
            data.get("thickness_scale", 1),
            location=f"{location}.thickness_scale",
            positive=True,
        ),
    )


def _optional_json_filename(
    value: object | None,
    *,
    location: str,
) -> str | None:
    if value is None:
        return None
    return normalize_json_filename(value, location=location)


def _parse_math_table_config(
    value: object | None,
    *,
    build_name: str,
    location: str,
) -> MathTableConfig | None:
    if value is None:
        return None

    data = _object(value, location=location)
    _reject_unknown_fields(data, _MATH_TABLE_FIELDS, location=location)
    if not data:
        return None

    return MathTableConfig(
        constants_file=normalize_json_filename(
            data.get("constants_file", build_name),
            location=f"{location}.constants_file",
        ),
        variants_file=_optional_json_filename(
            data.get("variants_file"),
            location=f"{location}.variants_file",
        ),
        italics_correction_file=_optional_json_filename(
            data.get("italics_correction_file"),
            location=f"{location}.italics_correction_file",
        ),
        accent_attachment_file=_optional_json_filename(
            data.get("accent_attachment_file"),
            location=f"{location}.accent_attachment_file",
        ),
        kern_file=_optional_json_filename(
            data.get("kern_file"),
            location=f"{location}.kern_file",
        ),
    )


def parse_font_meta(
    value: object,
    *,
    build_name: str,
    meta_path: Path,
) -> FontMeta:
    location = str(meta_path)
    data = _object(value, location=location)
    _reject_unknown_fields(data, _META_FIELDS, location=location)

    missing = _REQUIRED_META_FIELDS - set(data)
    if missing:
        raise ProjectDataError(
            f"{location} is missing required fields: {sorted(missing)}"
        )

    raw_source_rules = _array(
        data["source_rules"],
        location=f"{location}.source_rules",
    )
    if not raw_source_rules:
        raise ProjectDataError(
            f"{location}.source_rules cannot be empty."
        )
    source_rules = tuple(
        _parse_source_rule(
            rule,
            location=f"{location}.source_rules[{index}]",
        )
        for index, rule in enumerate(raw_source_rules)
    )

    glyph_generators_value = data.get("glyph_generators")
    raw_glyph_generators = (
        ()
        if glyph_generators_value is None
        else _array(
            glyph_generators_value,
            location=f"{location}.glyph_generators",
        )
    )
    glyph_generators = tuple(
        _safe_name(
            item,
            location=f"{location}.glyph_generators[{index}]",
        )
        for index, item in enumerate(raw_glyph_generators)
    )

    family = _string(data["family"], location=f"{location}.family")
    style = _string(data["style"], location=f"{location}.style")
    output_value = data.get("output_stem")
    raw_output_stem = (
        f"{family}-{style}"
        if output_value is None
        else _string(
            output_value,
            location=f"{location}.output_stem",
        )
    )
    output_stem = re.sub(
        r"[^A-Za-z0-9_.-]+", "-", raw_output_stem
    ).strip("-") or build_name

    thickness = _number(
        data["thickness"],
        location=f"{location}.thickness",
        positive=True,
    )

    return FontMeta(
        build_name=build_name,
        meta_path=meta_path,
        info=FontInfo(
            family=family,
            style=style,
            units_per_em=_positive_integer(
                data["units_per_em"],
                location=f"{location}.units_per_em",
            ),
            ascender=_number(
                data["ascender"], location=f"{location}.ascender"
            ),
            descender=_number(
                data["descender"], location=f"{location}.descender"
            ),
            cap_height=_number(
                data["cap_height"], location=f"{location}.cap_height"
            ),
            x_height=_number(
                data["x_height"], location=f"{location}.x_height"
            ),
        ),
        glyph_parameters=GlyphParameters(
            radius=thickness / 2,
            grid=_number(
                data["grid"],
                location=f"{location}.grid",
                positive=True,
            ),
            y_shift=_number(
                data.get("y_shift", 0),
                location=f"{location}.y_shift",
            ),
            monospace_width=(
                None
                if "monospace_width" not in data
                else _number(
                    data["monospace_width"],
                    location=f"{location}.monospace_width",
                    positive=True,
                )
            ),
            left_spacing=_number(
                data.get("left_spacing", 0),
                location=f"{location}.left_spacing",
            ),
            right_spacing=_number(
                data.get("right_spacing", 0),
                location=f"{location}.right_spacing",
            ),
            use_scaled_edge_thickness=_boolean(
                data.get("use_scaled_edge_thickness", False),
                location=f"{location}.use_scaled_edge_thickness",
            ),
        ),
        point_radius_scale=_number(
            data.get("point_radius_scale", 1.6),
            location=f"{location}.point_radius_scale",
            positive=True,
        ),
        source_rules=source_rules,
        glyph_generators=glyph_generators,
        glyph_config_file=_optional_json_filename(
            data.get("glyph_config_file"),
            location=f"{location}.glyph_config_file",
        ),
        accent_file=_optional_json_filename(
            data.get("accent_file"),
            location=f"{location}.accent_file",
        ),
        kerning_file=_optional_json_filename(
            data.get("kerning_file"),
            location=f"{location}.kerning_file",
        ),
        ssty_file=_optional_json_filename(
            data.get("ssty_file"),
            location=f"{location}.ssty_file",
        ),
        output_stem=output_stem,
        math_table=_parse_math_table_config(
            data.get("math_table"),
            build_name=build_name,
            location=f"{location}.math_table",
        ),
    )


def load_font_meta(project_directory: Path, meta_name: object) -> FontMeta:
    name = normalize_meta_name(meta_name)
    path = project_directory / "meta" / f"{name}.json"
    return parse_font_meta(
        read_json(path),
        build_name=name,
        meta_path=path,
    )


def parse_math_constants(
    value: object,
    *,
    source_path: Path,
) -> Mapping[str, int]:
    """Parse a complete OpenType MathConstants object."""

    data = _object(value, location=str(source_path))
    expected = set(MATH_CONSTANT_NAMES)
    actual = set(data)
    if actual != expected:
        raise ProjectDataError(
            f"{source_path} MathConstants mismatch. Missing: "
            f"{sorted(expected - actual)}; extra: {sorted(actual - expected)}"
        )

    constants: dict[str, int] = {}
    for name in MATH_CONSTANT_NAMES:
        value = data[name]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ProjectDataError(
                f"{source_path}.{name} must be an integer."
            )
        constants[name] = value
    return MappingProxyType(constants)


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


def parse_math_italics_correction(
    value: object,
    *,
    source_path: Path,
) -> Mapping[str, int]:
    """Parse per-glyph OpenType MATH italic corrections."""

    data = _object(value, location=str(source_path))
    if not data:
        raise ProjectDataError(f"{source_path} cannot be empty.")

    result: dict[str, int] = {}
    for raw_name, raw_correction in data.items():
        name = _safe_name(raw_name, location=f"{source_path} glyph name")
        result[name] = _nonnegative_integer(
            raw_correction,
            location=f"{source_path}.{name}",
        )
    return MappingProxyType(result)


def parse_math_accent_attachments(
    value: object,
    *,
    source_path: Path,
) -> Mapping[str, float]:
    """Parse exact-glyph top accent points in authored grid coordinates."""

    data = _object(value, location=str(source_path))
    if not data:
        raise ProjectDataError(f"{source_path} cannot be empty.")

    result: dict[str, float] = {}
    for raw_name, raw_attachment in data.items():
        name = _safe_name(raw_name, location=f"{source_path} glyph name")
        result[name] = _number(
            raw_attachment,
            location=f"{source_path}.{name}",
        )
    return MappingProxyType(result)


def _parse_math_kern_table(
    value: object,
    *,
    location: str,
) -> MathKernTableData:
    data = _object(value, location=location)
    _reject_unknown_fields(
        data,
        _MATH_KERN_TABLE_FIELDS,
        location=location,
    )
    missing = _MATH_KERN_TABLE_FIELDS - set(data)
    if missing:
        raise ProjectDataError(
            f"{location} is missing required fields: {sorted(missing)}"
        )
    correction_height = tuple(
        _integer(item, location=f"{location}.correction_height[{index}]")
        for index, item in enumerate(
            _array(
                data["correction_height"],
                location=f"{location}.correction_height",
            )
        )
    )
    if any(
        first >= second
        for first, second in zip(
            correction_height,
            correction_height[1:],
        )
    ):
        raise ProjectDataError(
            f"{location}.correction_height must be strictly increasing."
        )
    kern_values = tuple(
        _integer(item, location=f"{location}.kern_values[{index}]")
        for index, item in enumerate(
            _array(
                data["kern_values"],
                location=f"{location}.kern_values",
            )
        )
    )
    if len(kern_values) != len(correction_height) + 1:
        raise ProjectDataError(
            f"{location}.kern_values must contain exactly one more value "
            "than correction_height."
        )
    return MathKernTableData(correction_height, kern_values)


def parse_math_kerns(
    value: object,
    *,
    source_path: Path,
) -> Mapping[str, MathGlyphKernData]:
    """Parse mathematical kern tables keyed by exact glyph names."""

    data = _object(value, location=str(source_path))
    if not data:
        raise ProjectDataError(f"{source_path} cannot be empty.")

    result: dict[str, MathGlyphKernData] = {}
    for raw_name, raw_glyph_kern in data.items():
        name = _safe_name(raw_name, location=f"{source_path} glyph name")
        location = f"{source_path}.{name}"
        glyph_kern = _object(raw_glyph_kern, location=location)
        _reject_unknown_fields(
            glyph_kern,
            _MATH_KERN_CORNERS,
            location=location,
        )
        if not glyph_kern:
            raise ProjectDataError(
                f"{location} must define at least one math-kern corner."
            )
        corners = {
            corner: _parse_math_kern_table(
                table,
                location=f"{location}.{corner}",
            )
            for corner, table in glyph_kern.items()
        }
        result[name] = MathGlyphKernData(
            top_right=corners.get("top_right"),
            top_left=corners.get("top_left"),
            bottom_right=corners.get("bottom_right"),
            bottom_left=corners.get("bottom_left"),
        )
    return MappingProxyType(result)


def _parse_math_variant_glyph_names(
    value: object,
    *,
    base: str,
    location: str,
) -> tuple[str, ...]:
    """Parse one construction's ordered non-assembly variants."""

    items = _array(value, location=location)
    names = tuple(
        _safe_name(item, location=f"{location}[{index}]")
        for index, item in enumerate(items)
    )
    if base in names:
        raise ProjectDataError(f"{location} must not repeat its base glyph.")
    if len(names) != len(set(names)):
        raise ProjectDataError(
            f"{location} contains duplicate variant glyphs."
        )
    return names


def _parse_optional_math_scale(
    raw: Mapping[str, object],
    field_name: str,
    *,
    location: str,
) -> float | None:
    value = raw.get(field_name)
    if value is None:
        return None
    return _number(
        value,
        location=f"{location}.{field_name}",
        minimum=0,
    )


def _parse_math_assembly_parts(
    value: object,
    *,
    axis: str,
    location: str,
) -> tuple[MathAssemblyPartData, ...]:
    """Parse parts and normalize axis-specific scales to start/end."""

    raw_parts = _array(value, location=location)
    if not raw_parts:
        raise ProjectDataError(f"{location} cannot be empty.")

    if axis == "vertical":
        allowed_fields = _VERTICAL_ASSEMBLY_PART_FIELDS
        start_scale_name = "bottom_scale"
        end_scale_name = "top_scale"
    else:
        allowed_fields = _HORIZONTAL_ASSEMBLY_PART_FIELDS
        start_scale_name = "left_scale"
        end_scale_name = "right_scale"

    parts: list[MathAssemblyPartData] = []
    for index, raw_part in enumerate(raw_parts):
        part_location = f"{location}[{index}]"
        part = _object(raw_part, location=part_location)
        _reject_unknown_fields(
            part,
            allowed_fields,
            location=part_location,
        )
        missing = {
            "glyph",
            "start_connector_extent",
            "end_connector_extent",
            "extender",
        } - set(part)
        if missing:
            raise ProjectDataError(
                f"{part_location} is missing required fields: "
                f"{sorted(missing)}"
            )
        parts.append(
            MathAssemblyPartData(
                glyph_name=_safe_name(
                    part["glyph"],
                    location=f"{part_location}.glyph",
                ),
                start_connector_extent=_number(
                    part["start_connector_extent"],
                    location=f"{part_location}.start_connector_extent",
                    minimum=0,
                ),
                end_connector_extent=_number(
                    part["end_connector_extent"],
                    location=f"{part_location}.end_connector_extent",
                    minimum=0,
                ),
                start_scale=_parse_optional_math_scale(
                    part,
                    start_scale_name,
                    location=part_location,
                ),
                end_scale=_parse_optional_math_scale(
                    part,
                    end_scale_name,
                    location=part_location,
                ),
                extender=_boolean(
                    part["extender"],
                    location=f"{part_location}.extender",
                ),
            )
        )
    return tuple(parts)


def _parse_math_variants_axis(
    value: object,
    *,
    axis: str,
    source_path: Path,
) -> tuple[
    Mapping[str, tuple[str, ...]],
    Mapping[str, MathGlyphAssemblyData],
]:
    """Parse one axis into variant-glyph and assembly mappings."""

    axis_location = f"{source_path}.{axis}"
    raw_constructions = _object(value, location=axis_location)
    variant_glyphs: dict[str, tuple[str, ...]] = {}
    assemblies: dict[str, MathGlyphAssemblyData] = {}

    for raw_base, raw_construction in raw_constructions.items():
        base = _safe_name(
            raw_base,
            location=f"{axis_location} glyph name",
        )
        location = f"{axis_location}.{base}"
        construction = _object(raw_construction, location=location)
        _reject_unknown_fields(
            construction,
            _MATH_CONSTRUCTION_FIELDS,
            location=location,
        )

        variant_glyphs[base] = _parse_math_variant_glyph_names(
            construction.get("variant_glyphs", []),
            base=base,
            location=f"{location}.variant_glyphs",
        )

        if "parts" not in construction:
            if "italic_correction" in construction:
                raise ProjectDataError(
                    f"{location}.italic_correction requires parts."
                )
            continue

        assemblies[base] = MathGlyphAssemblyData(
            italic_correction=_integer(
                construction.get("italic_correction", 0),
                location=f"{location}.italic_correction",
            ),
            parts=_parse_math_assembly_parts(
                construction["parts"],
                axis=axis,
                location=f"{location}.parts",
            ),
        )

    return MappingProxyType(variant_glyphs), MappingProxyType(assemblies)


def load_ssty_data(
    project_directory: Path,
    filename: str,
) -> SstyData:
    """Load explicit GSUB ssty substitutions."""

    source_path = project_directory / "ssty" / filename
    return SstyData(
        source_path=source_path,
        substitutions=parse_ssty(
            read_json(source_path),
            source_path=source_path,
        ),
    )


def load_math_table_data(
    project_directory: Path,
    config: MathTableConfig,
) -> MathTableData:
    """Load all OpenType MATH-table inputs declared by one meta file."""

    constants_path = (
        project_directory / "math_table" / "constants" / config.constants_file
    )
    constants = parse_math_constants(
        read_json(constants_path),
        source_path=constants_path,
    )

    italics_correction_path = (
        None
        if config.italics_correction_file is None
        else project_directory
        / "math_table"
        / "italics_correction"
        / config.italics_correction_file
    )
    italic_corrections = (
        MappingProxyType({})
        if italics_correction_path is None
        else parse_math_italics_correction(
            read_json(italics_correction_path),
            source_path=italics_correction_path,
        )
    )

    accent_attachment_path = (
        None
        if config.accent_attachment_file is None
        else project_directory
        / "math_table"
        / "accent_attachment"
        / config.accent_attachment_file
    )
    accent_attachments = (
        MappingProxyType({})
        if accent_attachment_path is None
        else parse_math_accent_attachments(
            read_json(accent_attachment_path),
            source_path=accent_attachment_path,
        )
    )

    kern_path = (
        None
        if config.kern_file is None
        else project_directory / "math_table" / "kern" / config.kern_file
    )
    kerns = (
        MappingProxyType({})
        if kern_path is None
        else parse_math_kerns(
            read_json(kern_path),
            source_path=kern_path,
        )
    )

    variants_path = (
        None
        if config.variants_file is None
        else project_directory
        / "math_table"
        / "variants"
        / config.variants_file
    )
    min_connector_overlap = 0
    vertical_variant_glyphs: Mapping[str, tuple[str, ...]] = (
        MappingProxyType({})
    )
    horizontal_variant_glyphs: Mapping[str, tuple[str, ...]] = (
        MappingProxyType({})
    )
    vertical_assemblies: Mapping[str, MathGlyphAssemblyData] = (
        MappingProxyType({})
    )
    horizontal_assemblies: Mapping[str, MathGlyphAssemblyData] = (
        MappingProxyType({})
    )
    if variants_path is not None:
        variants = _object(
            read_json(variants_path),
            location=str(variants_path),
        )
        _reject_unknown_fields(
            variants,
            _MATH_VARIANTS_FIELDS,
            location=str(variants_path),
        )
        if "min_connector_overlap" not in variants:
            raise ProjectDataError(
                f"{variants_path} is missing min_connector_overlap."
            )
        min_connector_overlap = _nonnegative_integer(
            variants["min_connector_overlap"],
            location=f"{variants_path}.min_connector_overlap",
        )
        (
            vertical_variant_glyphs,
            vertical_assemblies,
        ) = _parse_math_variants_axis(
            variants.get("vertical", {}),
            axis="vertical",
            source_path=variants_path,
        )
        (
            horizontal_variant_glyphs,
            horizontal_assemblies,
        ) = _parse_math_variants_axis(
            variants.get("horizontal", {}),
            axis="horizontal",
            source_path=variants_path,
        )

    return MathTableData(
        constants_source_path=constants_path,
        constants=constants,
        italics_correction_source_path=italics_correction_path,
        italic_corrections=italic_corrections,
        accent_attachment_source_path=accent_attachment_path,
        accent_attachments=accent_attachments,
        kern_source_path=kern_path,
        kerns=kerns,
        min_connector_overlap=min_connector_overlap,
        vertical_variant_glyphs=vertical_variant_glyphs,
        horizontal_variant_glyphs=horizontal_variant_glyphs,
        vertical_assemblies=vertical_assemblies,
        horizontal_assemblies=horizontal_assemblies,
    )


def load_build_list(project_directory: Path) -> tuple[str, ...]:
    path = project_directory / "build_list.json"
    raw = _array(read_json(path), location=str(path))
    names = tuple(normalize_meta_name(item) for item in raw)
    if not names:
        raise ProjectDataError(f"{path} cannot be empty.")
    if len(names) != len(set(names)):
        raise ProjectDataError(f"{path} contains duplicate meta names.")
    return names


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
    for raw_name, raw_members in raw_groups.items():
        name = _safe_name(
            raw_name,
            location=f"{location}.groups key",
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
    path = project_directory / "kerning" / name
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
    path = project_directory / "accent" / filename
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
    path = project_directory / "config" / normalized_filename
    return parse_glyph_config(
        read_json(path),
        source_path=path,
    )


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
    else:
        skeleton = ()
        x_extent = _number(
            data["x_extent"],
            location=f"{location}.x_extent",
            minimum=0,
        )
        y_extent = None

    return GlyphSource(
        name=_string(data.get("name"), location=f"{location}.name"),
        codepoint=parse_codepoint(
            data["unicode"],
            location=f"{location}.unicode",
        ),
        monospace_x_offset=_number(
            data["monospace_x_offset"],
            location=f"{location}.monospace_x_offset",
        ),
        y_offset=_number(
            data["y_offset"],
            location=f"{location}.y_offset",
        ),
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
