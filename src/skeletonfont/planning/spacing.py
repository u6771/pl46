from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from ..errors import PlanError
from ..model import (
    AssembledGlyph,
    GlyphAdjustmentSelector,
    GlyphParameters,
    GlyphSpacingAdjustment,
    MathGlyphAssemblyData,
)


_GlyphRole = Literal[
    "ordinary",
    "accent",
    "vertical_variant_glyph",
    "horizontal_variant_glyph",
    "vertical_part",
    "horizontal_part",
]
_Axis = Literal[0, 1]


@dataclass(frozen=True, slots=True)
class _SpacingAdjustmentSource:
    adjustment: GlyphSpacingAdjustment
    selector: GlyphAdjustmentSelector


@dataclass(frozen=True, slots=True)
class _ResolvedGlyphSpacingAdjustments:
    glyph_spacing_by_name: Mapping[str, GlyphSpacingAdjustment]
    vertical_part_spacing_by_base: Mapping[str, GlyphSpacingAdjustment]


_EMPTY_SPACING_ADJUSTMENT = GlyphSpacingAdjustment()


def _effective_spacing_adjustment(
    adjustment: GlyphSpacingAdjustment,
) -> tuple[float, float]:
    return (
        0.0 if adjustment.left is None else adjustment.left,
        0.0 if adjustment.right is None else adjustment.right,
    )


def _adjusted_spacing(
    parameters: GlyphParameters,
    adjustment: GlyphSpacingAdjustment,
) -> tuple[float, float]:
    left_adjustment, right_adjustment = _effective_spacing_adjustment(
        adjustment
    )
    return (
        parameters.left_spacing + left_adjustment,
        parameters.right_spacing + right_adjustment,
    )

def _resolve_glyph_spacing_adjustments(
    spacing_config: Mapping[GlyphAdjustmentSelector, GlyphSpacingAdjustment],
    glyphs_by_role: Mapping[_GlyphRole, Mapping[str, AssembledGlyph]],
    parameters: GlyphParameters,
    vertical_variant_glyphs: Mapping[str, tuple[str, ...]],
    horizontal_variant_glyphs: Mapping[str, tuple[str, ...]],
    vertical_assemblies: Mapping[str, MathGlyphAssemblyData],
    horizontal_assemblies: Mapping[str, MathGlyphAssemblyData],
) -> _ResolvedGlyphSpacingAdjustments:
    """Resolve order-independent spacing adjustments by glyph and layout."""

    role_by_name = {
        name: role
        for role, glyphs in glyphs_by_role.items()
        for name in glyphs
    }
    exact_entries: dict[str, _SpacingAdjustmentSource] = {}
    variant_group_spacing_by_construction: dict[
        tuple[_Axis, str],
        _SpacingAdjustmentSource,
    ] = {}
    part_group_spacing_by_construction: dict[
        tuple[_Axis, str],
        _SpacingAdjustmentSource,
    ] = {}

    def assign_variant(
        key: tuple[_Axis, str],
        source: _SpacingAdjustmentSource,
    ) -> None:
        previous = variant_group_spacing_by_construction.get(key)
        if previous is not None:
            raise PlanError(
                f"Math construction {key[1]!r} receives overlapping variant "
                f"spacing adjustments from {previous.selector.text!r} and "
                f"{source.selector.text!r}."
            )
        variant_group_spacing_by_construction[key] = source

    def assign_parts(
        key: tuple[_Axis, str],
        source: _SpacingAdjustmentSource,
    ) -> None:
        previous = part_group_spacing_by_construction.get(key)
        if previous is not None:
            raise PlanError(
                f"Math assembly {key[1]!r} receives overlapping part "
                f"spacing adjustments from {previous.selector.text!r} and "
                f"{source.selector.text!r}."
            )
        part_group_spacing_by_construction[key] = source

    for selector in sorted(spacing_config, key=lambda item: item.text):
        adjustment = spacing_config[selector]
        source = _SpacingAdjustmentSource(adjustment, selector)
        if selector.group is None:
            exact_entries[selector.base_name] = source
            continue
        base = selector.base_name
        group_kind = selector.group

        construction_keys: list[tuple[_Axis, str]] = []
        if base in vertical_variant_glyphs:
            construction_keys.append((1, base))
        if base in horizontal_variant_glyphs:
            construction_keys.append((0, base))
        if not construction_keys:
            raise PlanError(
                f"Glyph selector {selector.text!r} references no MATH "
                "construction."
            )
        if len(construction_keys) > 1:
            raise PlanError(
                f"Glyph selector {selector.text!r} has an ambiguous MATH "
                "axis."
            )
        key = construction_keys[0]
        axis, _base = key

        if group_kind in ("parts", "variants"):
            if axis == 0:
                raise PlanError(
                    "Spacing adjustments cannot target horizontal assembly "
                    f"parts selected by {selector.text!r}."
                )
            if base not in vertical_assemblies:
    
                raise PlanError(
                    f"Glyph selector {selector.text!r} requires a "
                    f"vertical assembly with parts."
                )
            assign_parts(key, source)
        if group_kind in ("variant_glyphs", "variants"):
            constructions = (
                vertical_variant_glyphs
                if axis == 1
                else horizontal_variant_glyphs
            )
            accent_members = sorted(
                glyph_name
                for glyph_name in (base, *constructions[base])
                if role_by_name[glyph_name] == "accent"
            )
            if accent_members:
                raise PlanError(
                    f"Glyph selector {selector.text!r} includes combining "
                    f"accent glyphs {accent_members}, which cannot receive "
                    "spacing adjustments; configure discrete variant glyphs "
                    "individually."
                )
            assign_variant(key, source)

    variant_owners: dict[str, set[tuple[_Axis, str]]] = {}
    for axis, constructions in (
        (1, vertical_variant_glyphs),
        (0, horizontal_variant_glyphs),
    ):
        for base, alternates in constructions.items():
            key = (axis, base)
            for glyph_name in (base, *alternates):
                variant_owners.setdefault(glyph_name, set()).add(key)

    part_owners: dict[str, set[str]] = {}
    for base, construction in vertical_assemblies.items():
        for part in construction.parts:
            part_owners.setdefault(part.glyph_name, set()).add(base)

    for key, source in variant_group_spacing_by_construction.items():
        axis, base = key
        constructions = (
            vertical_variant_glyphs
            if axis == 1
            else horizontal_variant_glyphs
        )
        for glyph_name in (base, *constructions[base]):
            for owner_key in sorted(variant_owners[glyph_name]):
                owner = variant_group_spacing_by_construction.get(owner_key)
                if owner is None:
                    raise PlanError(
                        f"Glyph selector {source.selector.text!r} contains "
                        f"shared variant glyph {glyph_name!r}; owner "
                        f"construction {owner_key[1]!r} must receive the "
                        "same spacing adjustment."
                    )
                if _effective_spacing_adjustment(owner.adjustment) != (
                    _effective_spacing_adjustment(source.adjustment)
                ):
                    raise PlanError(
                        f"Shared variant glyph {glyph_name!r} receives "
                        "incompatible spacing adjustments from "
                        f"{source.selector.text!r} and "
                        f"{owner.selector.text!r}."
                    )

    for (axis, base), source in part_group_spacing_by_construction.items():
        assert axis == 1
        for part in vertical_assemblies[base].parts:
            for owner_base in sorted(part_owners[part.glyph_name]):
                owner = part_group_spacing_by_construction.get(
                    (1, owner_base)
                )
                if owner is None:
                    raise PlanError(
                        f"Glyph selector {source.selector.text!r} contains "
                        f"shared part {part.glyph_name!r}; owner assembly "
                        f"{owner_base!r} must receive the same spacing "
                        "adjustment."
                    )
                if _effective_spacing_adjustment(owner.adjustment) != (
                    _effective_spacing_adjustment(source.adjustment)
                ):
                    raise PlanError(
                        f"Shared assembly part {part.glyph_name!r} receives "
                        "incompatible spacing adjustments from "
                        f"{source.selector.text!r} and "
                        f"{owner.selector.text!r}."
                    )

    adjustment_by_name: dict[str, GlyphSpacingAdjustment] = {}
    source_by_name: dict[str, str] = {}
    for (axis, base), source in (
        variant_group_spacing_by_construction.items()
    ):
        constructions = (
            vertical_variant_glyphs
            if axis == 1
            else horizontal_variant_glyphs
        )
        for glyph_name in (base, *constructions[base]):
            previous = adjustment_by_name.get(glyph_name)
            if previous is not None:
                if _effective_spacing_adjustment(
                    previous
                ) != _effective_spacing_adjustment(source.adjustment):
                    raise PlanError(
                        f"Shared variant glyph {glyph_name!r} receives "
                        "incompatible spacing adjustments from "
                        f"{source_by_name[glyph_name]!r} and "
                        f"{source.selector.text!r}."
                    )
                continue
            adjustment_by_name[glyph_name] = source.adjustment
            source_by_name[glyph_name] = source.selector.text

    for glyph_name, source in exact_entries.items():
        role = role_by_name.get(glyph_name)
        if role is None:
            raise PlanError(
                f"Glyph config references a name not planned as an "
                f"assembled glyph: {glyph_name!r}."
            )
        if role == "vertical_part":
            owners = sorted(part_owners.get(glyph_name, ()))
            raise PlanError(
                f"Glyph {glyph_name!r} is a vertical assembly part and "
                "cannot receive an independent spacing adjustment; "
                "configure its "
                f"owner assemblies instead: {owners}."
            )
        if role == "horizontal_part":
            raise PlanError(
                f"Glyph {glyph_name!r} is a horizontal assembly part and "
                "cannot receive spacing adjustments."
            )
        if role == "accent":
            raise PlanError(
                f"Combining accent glyph {glyph_name!r} cannot receive "
                "left or right spacing adjustments."
            )
        ordinary_glyph = glyphs_by_role["ordinary"].get(glyph_name)
        if ordinary_glyph is not None and (
            parameters.monospace_width is not None
            or ordinary_glyph.ordinary_monospace_width is not None
        ):
            raise PlanError(
                f"Monospace ordinary glyph {glyph_name!r} cannot receive "
                "left or right spacing adjustments."
            )
        if glyph_name in adjustment_by_name:
            raise PlanError(
                f"Glyph {glyph_name!r} is configured both directly and "
                f"through {source_by_name[glyph_name]!r}."
            )
        adjustment_by_name[glyph_name] = source.adjustment

    return _ResolvedGlyphSpacingAdjustments(
        glyph_spacing_by_name=MappingProxyType(adjustment_by_name),
        vertical_part_spacing_by_base=MappingProxyType(
            {
                base: source.adjustment
                for (axis, base), source in (
                    part_group_spacing_by_construction.items()
                )
                if axis == 1
            }
        ),
    )
