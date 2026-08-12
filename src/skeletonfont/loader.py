"""Stable public facade for project-data loading."""

from __future__ import annotations

from .loading._json import (
    normalize_json_filename,
    normalize_meta_name,
    parse_codepoint,
    read_json,
)
from .loading.glyphs import (
    load_glyph_source,
    load_glyph_source_directory,
    parse_glyph_source,
    parse_stroke_record,
)
from .loading.layout import (
    load_accent_glyphs,
    load_glyph_config,
    load_kerning_data,
    load_ssty_data,
    parse_accent_glyphs,
    parse_glyph_config,
    parse_kerning_data,
    parse_ssty,
)
from .loading.math import (
    _parse_math_variants_axis,
    load_math_table_data,
    parse_math_accent_attachments,
    parse_math_constants,
    parse_math_italics_correction,
    parse_math_kerns,
)
from .loading.meta import (
    META_FIELD_ORDER,
    load_build_list,
    load_font_meta,
    parse_font_meta,
)
from .loading.release import load_release_info, parse_release_info


__all__ = [
    "META_FIELD_ORDER",
    "load_accent_glyphs",
    "load_build_list",
    "load_font_meta",
    "load_glyph_config",
    "load_glyph_source",
    "load_glyph_source_directory",
    "load_kerning_data",
    "load_math_table_data",
    "load_release_info",
    "load_ssty_data",
    "normalize_json_filename",
    "normalize_meta_name",
    "parse_accent_glyphs",
    "parse_codepoint",
    "parse_font_meta",
    "parse_glyph_config",
    "parse_glyph_source",
    "parse_kerning_data",
    "parse_math_accent_attachments",
    "parse_math_constants",
    "parse_math_italics_correction",
    "parse_math_kerns",
    "parse_release_info",
    "parse_ssty",
    "parse_stroke_record",
    "read_json",
]
