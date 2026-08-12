from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from ..errors import ProjectDataError
from ..math_schema import MATH_CONSTANT_NAMES
from ..model import (
    MathAssemblyPartData,
    MathGlyphAssemblyData,
    MathGlyphKernData,
    MathKernTableData,
    MathTableConfig,
    MathTableData,
)
from ..opentype import FWORD_MAX
from ._json import (
    _array,
    _boolean,
    _bounded_integer,
    _fword_integer,
    _number,
    _object,
    _reject_unknown_fields,
    _safe_name,
    _ufword_integer,
    read_json,
)


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
        location = f"{source_path}.{name}"
        constants[name] = (
            _ufword_integer(value, location=location)
            if name in {
                "DelimitedSubFormulaMinHeight",
                "DisplayOperatorMinHeight",
            }
            else _fword_integer(value, location=location)
        )
    return MappingProxyType(constants)


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
        result[name] = _bounded_integer(
            raw_correction,
            location=f"{source_path}.{name}",
            minimum=0,
            maximum=FWORD_MAX,
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
        _fword_integer(
            item,
            location=f"{location}.correction_height[{index}]",
        )
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
        _fword_integer(
            item,
            location=f"{location}.kern_values[{index}]",
        )
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
    if field_name not in raw:
        return None
    return _number(
        raw[field_name],
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
            italic_correction=_fword_integer(
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


def load_math_table_data(
    project_directory: Path,
    config: MathTableConfig,
) -> MathTableData:
    """Load all OpenType MATH-table inputs declared by one meta file."""

    math_data_directory = project_directory / "data" / "math_table"
    constants_path = math_data_directory / "constants" / config.constants_file
    constants = parse_math_constants(
        read_json(constants_path),
        source_path=constants_path,
    )

    italics_correction_path = (
        None
        if config.italics_correction_file is None
        else math_data_directory
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
        else math_data_directory
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
        else math_data_directory / "kern" / config.kern_file
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
        else math_data_directory / "variants" / config.variants_file
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
        min_connector_overlap = _ufword_integer(
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




