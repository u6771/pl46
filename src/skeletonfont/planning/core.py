from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ..errors import PlanError
from ..model import (
    AssembledFont,
    FontPlan,
    GlyphAdjustment,
    GlyphAdjustmentSelector,
    KerningData,
    MathTableData,
    MathTablePlan,
    GlyphPlan,
    SstyData,
)
from .assemblies import (
    _plan_horizontal_assemblies,
    _plan_variant_records,
    _plan_vertical_assemblies,
)
from .glyphs import (
    _plan_horizontal_accent_variant_advances,
    _plan_horizontal_variant_glyphs,
    _plan_ordinary_glyphs,
    _plan_vertical_variant_glyphs,
)
from .math_info import (
    _group_top_accent_attachments_by_role,
    _inherited_top_accent_attachments,
    _plan_accent_glyphs,
    _validate_italic_corrections,
    _validate_math_kerns_by_role,
    _with_ssty_top_accent_attachments,
)
from .roles import _group_glyphs_by_role
from .spacing import _resolve_glyph_spacing_adjustments
from .ssty import _merge_ssty_substitutions, _ssty_feature
from .validation import _validate_kerning, _validate_math_table_ranges












def plan_font(
    assembled_font: AssembledFont,
    glyph_config: Mapping[GlyphAdjustmentSelector, GlyphAdjustment]
    | None = None,
    kerning: KerningData | None = None,
    ssty_data: SstyData | None = None,
    math_table_data: MathTableData | None = None,
    accent_glyphs: frozenset[str] | None = None,
) -> FontPlan:
    """Resolve all glyph metrics and centerline transforms without file I/O."""

    parameters = assembled_font.glyph_parameters
    if math_table_data is not None:
        _validate_math_table_ranges(math_table_data)
    config = {} if glyph_config is None else glyph_config
    glyph_names = set(assembled_font.glyphs)
    glyph_names.update(
        alias.target_name for alias in assembled_font.glyph_aliases
    )
    _validate_kerning(glyph_names, kerning)

    vertical_variant_glyphs = (
        {}
        if math_table_data is None
        else math_table_data.vertical_variant_glyphs
    )
    horizontal_variant_glyphs = (
        {}
        if math_table_data is None
        else math_table_data.horizontal_variant_glyphs
    )
    vertical_assemblies = (
        {} if math_table_data is None else math_table_data.vertical_assemblies
    )
    horizontal_assemblies = (
        {}
        if math_table_data is None
        else math_table_data.horizontal_assemblies
    )
    roles = _group_glyphs_by_role(
        assembled_font.glyphs,
        frozenset() if accent_glyphs is None else accent_glyphs,
        vertical_variant_glyphs,
        horizontal_variant_glyphs,
        vertical_assemblies,
        horizontal_assemblies,
    )
    spacing_config = {
        selector: adjustment.spacing
        for selector, adjustment in config.items()
        if adjustment.spacing is not None
    }
    resolved_spacing_adjustments = _resolve_glyph_spacing_adjustments(
        spacing_config,
        roles,
        vertical_variant_glyphs,
        horizontal_variant_glyphs,
        vertical_assemblies,
        global_monospace=parameters.monospace_width is not None,
    )
    authored_top_accent_attachments = (
        {}
        if math_table_data is None
        else math_table_data.accent_attachments
    )
    top_accent_attachment_inputs = _group_top_accent_attachments_by_role(
        _with_ssty_top_accent_attachments(
            authored_top_accent_attachments,
            assembled_font.ssty_alternate_sources,
        ),
        roles,
    )
    authored_math_kerns = (
        {} if math_table_data is None else math_table_data.kerns
    )
    _validate_math_kerns_by_role(authored_math_kerns, roles)
    ordinary_glyph_plans = _plan_ordinary_glyphs(
        roles.ordinary,
        parameters,
        resolved_spacing_adjustments.glyph_spacing_by_name,
        top_accent_attachment_inputs.ordinary,
    )
    accent_glyph_plans = _plan_accent_glyphs(
        roles.accents,
        parameters,
    )
    vertical_variant_glyph_plans = _plan_vertical_variant_glyphs(
        roles.vertical_variant_glyphs,
        parameters,
        resolved_spacing_adjustments.glyph_spacing_by_name,
        top_accent_attachment_inputs.vertical_variant_glyph,
    )
    horizontal_variant_glyph_plans = _plan_horizontal_variant_glyphs(
        roles.horizontal_variant_glyphs,
        parameters,
        resolved_spacing_adjustments.glyph_spacing_by_name,
        top_accent_attachment_inputs.horizontal_variant_glyph,
    )
    horizontal_accent_variant_advances = (
        _plan_horizontal_accent_variant_advances(
            {
                name: glyph
                for name, glyph in roles.accents.items()
                if name in horizontal_variant_glyphs
            },
            parameters,
        )
    )
    minimum_overlap = (
        0
        if math_table_data is None
        else math_table_data.min_connector_overlap
    )
    vertical_assembly_plans = _plan_vertical_assemblies(
        vertical_assemblies,
        roles.vertical_parts,
        parameters,
        minimum_overlap,
        resolved_spacing_adjustments.vertical_part_spacing_by_base,
    )
    horizontal_assembly_plans = _plan_horizontal_assemblies(
        horizontal_assemblies,
        roles.horizontal_parts,
        parameters,
        minimum_overlap,
    )

    glyph_plans: dict[str, GlyphPlan] = {}
    for role, plans in (
        (
            "ordinary",
            ordinary_glyph_plans.glyph_plans,
        ),
        (
            "accent",
            accent_glyph_plans,
        ),
        (
            "vertical_variant_glyph",
            vertical_variant_glyph_plans.glyph_plans,
        ),
        (
            "horizontal_variant_glyph",
            horizontal_variant_glyph_plans.glyph_plans,
        ),
        (
            "vertical_part",
            vertical_assembly_plans.glyph_plans,
        ),
        (
            "horizontal_part",
            horizontal_assembly_plans.glyph_plans,
        ),
    ):
        overlap = set(glyph_plans) & set(plans)
        if overlap:
            raise PlanError(
                f"Internal glyph-role overlap while merging {role}: "
                f"{sorted(overlap)}"
            )
        glyph_plans.update(plans)

    vertical_variant_records = _plan_variant_records(
        vertical_variant_glyphs,
        vertical_variant_glyph_plans.full_advances,
    )
    horizontal_variant_records = _plan_variant_records(
        horizontal_variant_glyphs,
        {
            **horizontal_variant_glyph_plans.full_advances,
            **horizontal_accent_variant_advances,
        },
    )
    math_table_plan: MathTablePlan | None = None
    if math_table_data is not None:
        _validate_italic_corrections(
            math_table_data.italic_corrections,
            glyph_names,
        )
        planned_top_accent_attachments = {
            **ordinary_glyph_plans.top_accent_attachments,
            **vertical_variant_glyph_plans.top_accent_attachments,
            **horizontal_variant_glyph_plans.top_accent_attachments,
        }
        math_kerns = dict(authored_math_kerns)
        alias_top_accent_attachments = (
            _inherited_top_accent_attachments(
                planned_top_accent_attachments,
                {
                    alias.target_name: alias.source_name
                    for alias in assembled_font.glyph_aliases
                },
            )
        )
        top_accent_attachments = {
            **alias_top_accent_attachments,
            **planned_top_accent_attachments,
        }
        for alias in assembled_font.glyph_aliases:
            kern = authored_math_kerns.get(alias.source_name)
            if kern is not None:
                math_kerns[alias.target_name] = kern
        math_table_plan = MathTablePlan(
            constants=math_table_data.constants,
            vertical_variant_records=vertical_variant_records,
            horizontal_variant_records=horizontal_variant_records,
            min_connector_overlap=minimum_overlap,
            vertical_assemblies=vertical_assembly_plans.assembly_plans,
            horizontal_assemblies=horizontal_assembly_plans.assembly_plans,
            extended_shapes=(
                frozenset(vertical_variant_records)
                | frozenset(vertical_assembly_plans.assembly_plans)
            ),
            italic_corrections=math_table_data.italic_corrections,
            top_accent_attachments=MappingProxyType(
                top_accent_attachments
            ),
            kerns=MappingProxyType(math_kerns),
        )

    return FontPlan(
        info=assembled_font.info,
        output_stem=assembled_font.output_stem,
        point_radius_scale=assembled_font.point_radius_scale,
        kerning=kerning,
        ssty_feature=_ssty_feature(
            _merge_ssty_substitutions(
                assembled_font.ssty_substitutions,
                {} if ssty_data is None else ssty_data.substitutions,
            ),
            glyph_names,
        ),
        math_table=math_table_plan,
        glyphs=MappingProxyType(glyph_plans),
        glyph_aliases=assembled_font.glyph_aliases,
    )
