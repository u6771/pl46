from __future__ import annotations

import pathops
from ufoLib2 import Font

from .errors import RenderError
from .geometry import merge_stroke_paths
from .model import FontPlan, GlyphAlias, GlyphPlan, ReleaseInfo


_EMBEDDING_PERMISSION_BITS = {
    "installable": [],
    "restricted": [1],
    "preview_and_print": [2],
    "editable": [3],
}


def _set_unicodes(glyph, codepoint: int | None) -> None:
    glyph.unicodes = [] if codepoint is None else [codepoint]


def _render_glyph(
    font: Font,
    plan: GlyphPlan,
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


def _copy_glyph_alias(font: Font, alias: GlyphAlias) -> None:
    source_name = alias.source_name
    default_layer = font.layers.defaultLayer
    if source_name not in default_layer:
        raise RenderError(
            f"Glyph alias {alias.target_name!r} cannot copy its source "
            f"{source_name!r}."
        )

    glyph = default_layer[source_name].copy(name=alias.target_name)
    _set_unicodes(glyph, alias.target_codepoint)
    default_layer.addGlyph(glyph)


def _apply_release_info(font: Font, release_info: ReleaseInfo) -> None:
    license_info = release_info.license

    info = font.info
    if release_info.version is not None:
        assert release_info.version_major is not None
        assert release_info.version_minor is not None
        info.versionMajor = release_info.version_major
        info.versionMinor = release_info.version_minor
        info.openTypeNameVersion = f"Version {release_info.version}"
    if release_info.copyright is not None:
        info.copyright = release_info.copyright
    if release_info.designer is not None:
        info.openTypeNameDesigner = release_info.designer
    if release_info.designer_url is not None:
        info.openTypeNameDesignerURL = release_info.designer_url
    if release_info.manufacturer is not None:
        info.openTypeNameManufacturer = release_info.manufacturer
    if release_info.manufacturer_url is not None:
        info.openTypeNameManufacturerURL = release_info.manufacturer_url
    if release_info.description is not None:
        info.openTypeNameDescription = release_info.description
    if release_info.trademark is not None:
        info.trademark = release_info.trademark
    if release_info.vendor_id is not None:
        info.openTypeOS2VendorID = release_info.vendor_id
    if license_info is not None:
        info.openTypeNameLicense = license_info.description
        if license_info.url is not None:
            info.openTypeNameLicenseURL = license_info.url
    if release_info.embedding_permissions is not None:
        info.openTypeOS2Type = list(
            _EMBEDDING_PERMISSION_BITS[release_info.embedding_permissions]
        )


def render_font(
    plan: FontPlan,
    *,
    release_info: ReleaseInfo | None = None,
) -> Font:
    """Render a fully resolved font plan into an in-memory UFO font."""

    info = plan.info
    font = Font()
    font.info.familyName = info.family
    font.info.styleName = info.style
    font.info.openTypeOS2WeightClass = info.weight_class
    font.info.postscriptIsFixedPitch = info.is_fixed_pitch
    font.info.unitsPerEm = info.units_per_em
    font.info.ascender = info.ascender
    font.info.descender = info.descender
    font.info.capHeight = info.cap_height
    font.info.xHeight = info.x_height
    if release_info is not None:
        _apply_release_info(font, release_info)

    for glyph_plan in plan.glyphs.values():
        _render_glyph(
            font,
            glyph_plan,
            point_radius_scale=plan.point_radius_scale,
        )

    for alias in plan.glyph_aliases:
        _copy_glyph_alias(font, alias)

    if plan.kerning is not None:
        for name, members in plan.kerning.groups.items():
            font.groups[name] = list(members)
        for pair in plan.kerning.pairs:
            font.kerning[(pair.left, pair.right)] = pair.value

    if plan.ssty_feature is not None:
        font.features.text = plan.ssty_feature

    return font
