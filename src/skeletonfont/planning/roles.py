from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from ..errors import PlanError
from ..model import AssembledGlyph, MathGlyphAssemblyData


_GlyphRole = Literal[
    "ordinary",
    "accent",
    "vertical_variant_glyph",
    "horizontal_variant_glyph",
    "vertical_part",
    "horizontal_part",
]


def _construction_members(
    constructions: Mapping[str, tuple[str, ...]],
) -> set[str]:
    result = set(constructions)
    for alternates in constructions.values():
        result.update(alternates)
    return result


def _part_members(
    constructions: Mapping[str, MathGlyphAssemblyData],
) -> set[str]:
    return {
        part_data.glyph_name
        for construction in constructions.values()
        for part_data in construction.parts
    }


def _group_glyphs_by_role(
    glyphs: Mapping[str, AssembledGlyph],
    accent_glyphs: frozenset[str],
    vertical_variant_glyphs: Mapping[str, tuple[str, ...]],
    horizontal_variant_glyphs: Mapping[str, tuple[str, ...]],
    vertical_assemblies: Mapping[str, MathGlyphAssemblyData],
    horizontal_assemblies: Mapping[str, MathGlyphAssemblyData],
) -> Mapping[_GlyphRole, Mapping[str, AssembledGlyph]]:
    glyph_names = set(glyphs)
    role_members: tuple[tuple[_GlyphRole, set[str]], ...] = (
        ("accent", set(accent_glyphs)),
        (
            "vertical_variant_glyph",
            _construction_members(vertical_variant_glyphs),
        ),
        (
            "horizontal_variant_glyph",
            _construction_members(horizontal_variant_glyphs),
        ),
        ("vertical_part", _part_members(vertical_assemblies)),
        ("horizontal_part", _part_members(horizontal_assemblies)),
    )

    referenced = set(vertical_assemblies) | set(horizontal_assemblies)
    for _role, members in role_members:
        referenced.update(members)
    missing = referenced - glyph_names
    if missing:
        raise PlanError(
            f"Glyph roles reference unknown assembled glyphs: "
            f"{sorted(missing)}"
        )

    grouped: dict[_GlyphRole, dict[str, AssembledGlyph]] = {
        "ordinary": {},
        "accent": {},
        "vertical_variant_glyph": {},
        "horizontal_variant_glyph": {},
        "vertical_part": {},
        "horizontal_part": {},
    }
    for name, glyph in glyphs.items():
        memberships = [role for role, members in role_members if name in members]
        is_horizontal_accent_base = (
            set(memberships) == {"accent", "horizontal_variant_glyph"}
            and name in horizontal_variant_glyphs
        )
        if len(memberships) > 1 and not is_horizontal_accent_base:
            raise PlanError(
                f"Glyph {name!r} belongs to multiple planning roles: "
                f"{memberships}."
            )
        role: _GlyphRole = (
            "accent"
            if is_horizontal_accent_base
            else memberships[0]
            if memberships
            else "ordinary"
        )
        grouped[role][name] = glyph
    return MappingProxyType(
        {
            role: MappingProxyType(entries)
            for role, entries in grouped.items()
        }
    )


