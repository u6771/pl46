from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from ..errors import ProjectDataError
from ..model import (
    FontInfo,
    FontMeta,
    GlyphParameters,
    MathTableConfig,
    SourceRule,
    SstyGenerator,
)
from ..opentype import (
    FWORD_MAX,
    FWORD_MIN,
    UNITS_PER_EM_MAX,
    UNITS_PER_EM_MIN,
)
from ._json import (
    _array,
    _boolean,
    _bounded_integer,
    _number,
    _object,
    _parse_unicode_domain,
    _relative_directory,
    _reject_unknown_fields,
    _safe_name,
    _string,
    normalize_json_filename,
    normalize_meta_name,
    read_json,
)


META_FIELD_ORDER = (
    "output_stem",
    "family",
    "style",
    "weight_class",
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
    "glyph_alias_generators",
    "ssty_generators",
    "accent_file",
    "ssty_file",
    "math_table",
    "glyph_config_file",
    "kerning_file",
    "release_info_file",
)

_META_FIELDS = set(META_FIELD_ORDER)
_REQUIRED_META_FIELDS = {
    "family",
    "style",
    "weight_class",
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
    "unicode_domain",
    "include_unencoded",
    "replace_existing",
    "mapping_name",
    "thickness_scale",
}

_SSTY_GENERATOR_FIELDS = {
    "unicode_domain",
    "ssty_alternate_name",
    "thickness_scale",
}
_REQUIRED_SSTY_GENERATOR_FIELDS = set(_SSTY_GENERATOR_FIELDS)

_MATH_TABLE_FIELDS = {
    "constants_file",
    "variants_file",
    "italics_correction_file",
    "accent_attachment_file",
    "kern_file",
}
_REQUIRED_MATH_TABLE_FIELDS = {"constants_file"}


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

    mapping_name = (
        None
        if "mapping_name" not in data
        else _safe_name(
            data["mapping_name"],
            location=f"{location}.mapping_name",
        )
    )
    return SourceRule(
        source_directory=_relative_directory(
            data.get("source_directory"),
            location=f"{location}.source_directory",
        ),
        unicode_domain=(
            None
            if "unicode_domain" not in data
            else _parse_unicode_domain(
                data["unicode_domain"],
                location=f"{location}.unicode_domain",
            )
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


def _parse_ssty_generator(
    value: object,
    *,
    location: str,
) -> SstyGenerator:
    data = _object(value, location=location)
    _reject_unknown_fields(data, _SSTY_GENERATOR_FIELDS, location=location)
    missing = _REQUIRED_SSTY_GENERATOR_FIELDS - set(data)
    if missing:
        raise ProjectDataError(
            f"{location} is missing required fields: {sorted(missing)}"
        )
    return SstyGenerator(
        unicode_domain=_parse_unicode_domain(
            data["unicode_domain"],
            location=f"{location}.unicode_domain",
        ),
        ssty_alternate_name=_safe_name(
            data["ssty_alternate_name"],
            location=f"{location}.ssty_alternate_name",
        ),
        thickness_scale=_number(
            data["thickness_scale"],
            location=f"{location}.thickness_scale",
            positive=True,
        ),
    )


def _optional_json_filename(
    data: Mapping[str, object],
    field_name: str,
    *,
    location: str,
) -> str | None:
    if field_name not in data:
        return None
    return normalize_json_filename(data[field_name], location=location)


def _parse_math_table_config(
    value: object,
    *,
    location: str,
) -> MathTableConfig:
    data = _object(value, location=location)
    _reject_unknown_fields(data, _MATH_TABLE_FIELDS, location=location)
    missing = _REQUIRED_MATH_TABLE_FIELDS - set(data)
    if missing:
        raise ProjectDataError(
            f"{location} is missing required fields: {sorted(missing)}"
        )

    return MathTableConfig(
        constants_file=normalize_json_filename(
            data["constants_file"],
            location=f"{location}.constants_file",
        ),
        variants_file=_optional_json_filename(
            data,
            "variants_file",
            location=f"{location}.variants_file",
        ),
        italics_correction_file=_optional_json_filename(
            data,
            "italics_correction_file",
            location=f"{location}.italics_correction_file",
        ),
        accent_attachment_file=_optional_json_filename(
            data,
            "accent_attachment_file",
            location=f"{location}.accent_attachment_file",
        ),
        kern_file=_optional_json_filename(
            data,
            "kern_file",
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

    raw_glyph_alias_generators = (
        ()
        if "glyph_alias_generators" not in data
        else _array(
            data["glyph_alias_generators"],
            location=f"{location}.glyph_alias_generators",
        )
    )
    glyph_alias_generators = tuple(
        _safe_name(
            item,
            location=f"{location}.glyph_alias_generators[{index}]",
        )
        for index, item in enumerate(raw_glyph_alias_generators)
    )
    raw_ssty_generators = (
        ()
        if "ssty_generators" not in data
        else _array(
            data["ssty_generators"],
            location=f"{location}.ssty_generators",
        )
    )
    ssty_generators = tuple(
        _parse_ssty_generator(
            item,
            location=f"{location}.ssty_generators[{index}]",
        )
        for index, item in enumerate(raw_ssty_generators)
    )

    family = _string(data["family"], location=f"{location}.family")
    style = _string(data["style"], location=f"{location}.style")
    raw_output_stem = (
        f"{family}-{style}"
        if "output_stem" not in data
        else _string(
            data["output_stem"],
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
    monospace_width = (
        None
        if "monospace_width" not in data
        else _number(
            data["monospace_width"],
            location=f"{location}.monospace_width",
            positive=True,
        )
    )
    math_table = (
        None
        if "math_table" not in data
        else _parse_math_table_config(
            data["math_table"],
            location=f"{location}.math_table",
        )
    )

    return FontMeta(
        build_name=build_name,
        meta_path=meta_path,
        info=FontInfo(
            family=family,
            style=style,
            weight_class=_bounded_integer(
                data["weight_class"],
                location=f"{location}.weight_class",
                minimum=1,
                maximum=1000,
            ),
            is_fixed_pitch=(
                monospace_width is not None and math_table is None
            ),
            units_per_em=_bounded_integer(
                data["units_per_em"],
                location=f"{location}.units_per_em",
                minimum=UNITS_PER_EM_MIN,
                maximum=UNITS_PER_EM_MAX,
            ),
            ascender=_number(
                data["ascender"],
                location=f"{location}.ascender",
                minimum=FWORD_MIN,
                maximum=FWORD_MAX,
            ),
            descender=_number(
                data["descender"],
                location=f"{location}.descender",
                minimum=FWORD_MIN,
                maximum=FWORD_MAX,
            ),
            cap_height=_number(
                data["cap_height"],
                location=f"{location}.cap_height",
                minimum=FWORD_MIN,
                maximum=FWORD_MAX,
            ),
            x_height=_number(
                data["x_height"],
                location=f"{location}.x_height",
                minimum=FWORD_MIN,
                maximum=FWORD_MAX,
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
            monospace_width=monospace_width,
            left_spacing=_number(
                data.get("left_spacing", 0),
                location=f"{location}.left_spacing",
            ),
            right_spacing=_number(
                data.get("right_spacing", 0),
                location=f"{location}.right_spacing",
            ),
            use_scaled_edge_thickness=_boolean(
                data.get("use_scaled_edge_thickness", True),
                location=f"{location}.use_scaled_edge_thickness",
            ),
        ),
        point_radius_scale=_number(
            data.get("point_radius_scale", 1.6),
            location=f"{location}.point_radius_scale",
            positive=True,
        ),
        source_rules=source_rules,
        glyph_alias_generators=glyph_alias_generators,
        ssty_generators=ssty_generators,
        glyph_config_file=_optional_json_filename(
            data,
            "glyph_config_file",
            location=f"{location}.glyph_config_file",
        ),
        accent_file=_optional_json_filename(
            data,
            "accent_file",
            location=f"{location}.accent_file",
        ),
        kerning_file=_optional_json_filename(
            data,
            "kerning_file",
            location=f"{location}.kerning_file",
        ),
        ssty_file=_optional_json_filename(
            data,
            "ssty_file",
            location=f"{location}.ssty_file",
        ),
        release_info_file=_optional_json_filename(
            data,
            "release_info_file",
            location=f"{location}.release_info_file",
        ),
        output_stem=output_stem,
        math_table=math_table,
    )


def load_font_meta(project_directory: Path, meta_name: object) -> FontMeta:
    name = normalize_meta_name(meta_name)
    path = project_directory / "meta" / f"{name}.json"
    return parse_font_meta(
        read_json(path),
        build_name=name,
        meta_path=path,
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
