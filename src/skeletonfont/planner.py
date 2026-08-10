"""Stable public facade for font planning."""

from __future__ import annotations

from .planning.core import plan_font
from .planning.math_info import (
    _inherited_top_accent_attachments,
    _with_ssty_top_accent_attachments,
)
from .planning.glyphs import (
    _measure_glyph_axis,
    _plan_variant_glyph,
    _transform_stroke,
    _transformed_strokes,
)


__all__ = ["plan_font"]
