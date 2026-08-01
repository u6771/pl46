from __future__ import annotations

import pathops
from ufoLib2 import Font

from .errors import RenderError
from .geometry import merge_stroke_paths
from .model import FontPlan, GeneratedGlyph, RealGlyphPlan


def _set_unicodes(glyph, codepoint: int | None) -> None:
    glyph.unicodes = [] if codepoint is None else [codepoint]


def _render_real_glyph(
    font: Font,
    plan: RealGlyphPlan,
    *,
    point_radius_scale: float,
) -> None:
    glyph = font.newGlyph(plan.name)
    glyph.width = plan.width
    _set_unicodes(glyph, plan.codepoint)

    try:
        path = merge_stroke_paths(
            plan.strokes,
            point_radius_scale=point_radius_scale,
        )
    except (ValueError, pathops.PathOpsError) as error:
        source = plan.source_path
        raise RenderError(
            f"Cannot render glyph {glyph.name!r} from {source}: {error}"
        ) from error

    path.draw(glyph.getPen())


def _copy_generated_glyph(font: Font, glyph_data: GeneratedGlyph) -> None:
    source_name = glyph_data.source_name
    default_layer = font.layers.defaultLayer
    if source_name not in default_layer:
        raise RenderError(
            f"Generated glyph {glyph_data.target_name!r} cannot copy its source "
            f"{source_name!r}."
        )

    glyph = default_layer[source_name].copy(name=glyph_data.target_name)
    _set_unicodes(glyph, glyph_data.target_codepoint)
    default_layer.addGlyph(glyph)


def render_font(plan: FontPlan) -> Font:
    """Render a fully resolved font plan into an in-memory UFO font."""

    info = plan.info
    font = Font()
    font.info.familyName = info.family
    font.info.styleName = info.style
    font.info.unitsPerEm = info.units_per_em
    font.info.ascender = info.ascender
    font.info.descender = info.descender
    font.info.capHeight = info.cap_height
    font.info.xHeight = info.x_height

    for glyph_plan in plan.real_glyphs.values():
        _render_real_glyph(
            font,
            glyph_plan,
            point_radius_scale=plan.point_radius_scale,
        )

    for generated in plan.generated_glyphs:
        _copy_generated_glyph(font, generated)

    if plan.kerning is not None:
        for name, members in plan.kerning.groups.items():
            font.groups[name] = list(members)
        for pair in plan.kerning.pairs:
            font.kerning[(pair.left, pair.right)] = pair.value

    if plan.math is not None and plan.math.ssty_feature is not None:
        font.features.text = plan.math.ssty_feature

    return font
