from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..errors import PlanError
from ..model import (
    AssembledGlyph,
    GlyphParameters,
    GlyphPlan,
    GlyphSpacingAdjustment,
    MathAssemblyPartData,
    MathAssemblyPartPlan,
    MathGlyphAssemblyData,
    MathGlyphAssemblyPlan,
    MathVariantRecord,
)
from .glyphs import (
    _axis_length,
    _measure_glyph_axis,
    _rounded_width,
    _transformed_strokes,
)
from .spacing import _EMPTY_SPACING_ADJUSTMENT, _adjusted_spacing


_EDGE_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class _VerticalLayout:
    common_x_min: float
    common_x_max: float
    common_left_scale: float
    common_right_scale: float
    left_spacing: float
    right_spacing: float

@dataclass(frozen=True, slots=True)
class _AssemblyPlans:
    glyph_plans: Mapping[str, GlyphPlan]
    assembly_plans: Mapping[str, MathGlyphAssemblyPlan]

def _plan_variant_records(
    constructions: Mapping[str, tuple[str, ...]],
    advances: Mapping[str, int],
) -> Mapping[str, tuple[MathVariantRecord, ...]]:
    result: dict[str, tuple[MathVariantRecord, ...]] = {}
    for base, alternate_glyphs in constructions.items():
        records = [
            MathVariantRecord(name, advances[name])
            for name in (base, *alternate_glyphs)
        ]
        records.sort(key=lambda record: (record.full_advance, record.glyph_name))
        result[base] = tuple(records)
    return MappingProxyType(result)


def _assembly_part_plan(
    part_data: MathAssemblyPartData,
    *,
    full_advance: int,
    grid: float,
    axis_name: str,
) -> MathAssemblyPartPlan:
    start_length = _rounded_width(
        part_data.start_connector_extent * grid,
        glyph_name=part_data.glyph_name,
    )
    end_length = _rounded_width(
        part_data.end_connector_extent * grid,
        glyph_name=part_data.glyph_name,
    )
    if start_length > full_advance or end_length > full_advance:
        raise PlanError(
            f"Math {axis_name} assembly part {part_data.glyph_name!r} has a "
            f"connector length greater than its FullAdvance {full_advance}."
        )
    return MathAssemblyPartPlan(
        glyph_name=part_data.glyph_name,
        start_connector_length=start_length,
        end_connector_length=end_length,
        full_advance=full_advance,
        extender=part_data.extender,
    )


def _validate_connector_overlaps(
    base: str,
    assembly: MathGlyphAssemblyPlan,
    minimum: int,
    *,
    axis_name: str,
) -> None:
    for first_part, second_part in zip(
        assembly.parts,
        assembly.parts[1:],
    ):
        if (
            first_part.end_connector_length < minimum
            or second_part.start_connector_length < minimum
        ):
            raise PlanError(
                f"Math {axis_name} assembly {base!r} cannot provide "
                f"min_connector_overlap {minimum} between "
                f"{first_part.glyph_name!r} and "
                f"{second_part.glyph_name!r}."
            )
    for part_plan in assembly.parts:
        if part_plan.extender and (
            part_plan.start_connector_length < minimum
            or part_plan.end_connector_length < minimum
        ):
            raise PlanError(
                f"Math {axis_name} assembly {base!r} extender "
                f"{part_plan.glyph_name!r} cannot overlap itself by {minimum}."
            )


def _collect_part_uses(
    constructions: Mapping[str, MathGlyphAssemblyData],
    *,
    axis_name: str,
) -> Mapping[str, tuple[tuple[str, MathAssemblyPartData], ...]]:
    uses_by_glyph_name: dict[
        str,
        list[tuple[str, MathAssemblyPartData]],
    ] = {}
    for base, construction in constructions.items():
        for part_data in construction.parts:
            if part_data.glyph_name == base:
                raise PlanError(
                    f"Math {axis_name} assembly {base!r} cannot use its base "
                    "glyph as a part."
                )
            uses_by_glyph_name.setdefault(
                part_data.glyph_name,
                [],
            ).append((base, part_data))
    return MappingProxyType(
        {
            glyph_name: tuple(entries)
            for glyph_name, entries in uses_by_glyph_name.items()
        }
    )


def _authored_scales_by_glyph_name(
    uses_by_glyph_name: Mapping[
        str,
        tuple[tuple[str, MathAssemblyPartData], ...],
    ],
    *,
    axis_name: str,
) -> Mapping[str, tuple[float | None, float | None]]:
    result: dict[str, tuple[float | None, float | None]] = {}
    for glyph_name, entries in uses_by_glyph_name.items():
        authored_scale_entries = tuple(
            (
                base,
                (part_data.start_scale, part_data.end_scale),
            )
            for base, part_data in entries
        )
        reference_scales = authored_scale_entries[0][1]
        if any(
            scales != reference_scales
            for _base, scales in authored_scale_entries[1:]
        ):
            details = "; ".join(
                f"{base!r}: {scales!r}"
                for base, scales in authored_scale_entries
            )
            raise PlanError(
                f"Math {axis_name} assembly part {glyph_name!r} has "
                f"inconsistent authored edge scales: {details}."
            )
        result[glyph_name] = reference_scales
    return MappingProxyType(result)


def _vertical_layout(
    part_data_sequence: tuple[MathAssemblyPartData, ...],
    bounds_by_glyph_name: Mapping[
        str,
        tuple[float, float, float, float],
    ],
    *,
    left_spacing: float,
    right_spacing: float,
) -> _VerticalLayout:
    bounds = tuple(
        bounds_by_glyph_name[part_data.glyph_name]
        for part_data in part_data_sequence
    )
    common_x_min = min(
        minimum for minimum, _maximum, _start_scale, _end_scale in bounds
    )
    common_x_max = max(
        maximum for _minimum, maximum, _start_scale, _end_scale in bounds
    )
    common_left_scale = max(
        start_scale
        for minimum, _maximum, start_scale, _end_scale in bounds
        if math.isclose(
            minimum,
            common_x_min,
            abs_tol=_EDGE_TOLERANCE,
        )
    )
    common_right_scale = max(
        end_scale
        for _minimum, maximum, _start_scale, end_scale in bounds
        if math.isclose(
            maximum,
            common_x_max,
            abs_tol=_EDGE_TOLERANCE,
        )
    )
    return _VerticalLayout(
        common_x_min=common_x_min,
        common_x_max=common_x_max,
        common_left_scale=common_left_scale,
        common_right_scale=common_right_scale,
        left_spacing=left_spacing,
        right_spacing=right_spacing,
    )


def _plan_vertical_assemblies(
    constructions: Mapping[str, MathGlyphAssemblyData],
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
    minimum_overlap: int,
    adjustment_by_base: Mapping[str, GlyphSpacingAdjustment],
) -> _AssemblyPlans:
    if not constructions:
        empty = MappingProxyType({})
        return _AssemblyPlans(glyph_plans=empty, assembly_plans=empty)
    uses_by_glyph_name = _collect_part_uses(
        constructions,
        axis_name="vertical",
    )
    authored_scales_by_glyph_name = _authored_scales_by_glyph_name(
        uses_by_glyph_name,
        axis_name="vertical",
    )
    authored_x_scale = (
        None if parameters.use_scaled_edge_thickness else 1.0
    )
    x_measurement_by_glyph_name = MappingProxyType(
        {
            glyph_name: _measure_glyph_axis(
                glyphs[glyph_name],
                axis=0,
                start_scale=authored_x_scale,
                end_scale=authored_x_scale,
            )
            for glyph_name in uses_by_glyph_name
        }
    )
    bounds_by_glyph_name = MappingProxyType(
        {
            glyph_name: (
                glyphs[glyph_name].monospace_x_offset,
                glyphs[glyph_name].monospace_x_offset
                + x_measurement_by_glyph_name[glyph_name].extent,
                x_measurement_by_glyph_name[glyph_name].start_scale,
                x_measurement_by_glyph_name[glyph_name].end_scale,
            )
            for glyph_name in uses_by_glyph_name
        }
    )
    layouts: dict[str, _VerticalLayout] = {}
    for base, construction in constructions.items():
        left_spacing, right_spacing = _adjusted_spacing(
            parameters,
            adjustment_by_base.get(base, _EMPTY_SPACING_ADJUSTMENT),
        )
        layouts[base] = _vertical_layout(
            construction.parts,
            bounds_by_glyph_name,
            left_spacing=left_spacing,
            right_spacing=right_spacing,
        )
    layouts_by_base = MappingProxyType(layouts)

    vertical_layout_by_glyph_name: dict[str, _VerticalLayout] = {}
    for glyph_name, entries in uses_by_glyph_name.items():
        owner_bases = tuple(
            dict.fromkeys(base for base, _part_data in entries)
        )
        owner_layouts = tuple(
            (base, layouts_by_base[base]) for base in owner_bases
        )
        reference_layout = owner_layouts[0][1]
        if any(
            layout != reference_layout
            for _base, layout in owner_layouts[1:]
        ):
            details = "; ".join(
                f"{base!r}: {layout!r}"
                for base, layout in owner_layouts
            )
            raise PlanError(
                f"Math vertical assembly part {glyph_name!r} has "
                f"incompatible construction layouts: {details}."
            )
        vertical_layout_by_glyph_name[glyph_name] = reference_layout

    y_measurement_by_glyph_name = MappingProxyType(
        {
            glyph_name: _measure_glyph_axis(
                glyphs[glyph_name],
                axis=1,
                start_scale=authored_scales_by_glyph_name[glyph_name][0],
                end_scale=authored_scales_by_glyph_name[glyph_name][1],
            )
            for glyph_name in uses_by_glyph_name
        }
    )
    full_advance_by_glyph_name: dict[str, int] = {}
    for glyph_name, measurement in y_measurement_by_glyph_name.items():
        if math.isclose(
            measurement.extent,
            0,
            abs_tol=_EDGE_TOLERANCE,
        ):
            raise PlanError(
                f"Math vertical assembly part {glyph_name!r} has no positive "
                "centerline extent."
            )
        full_advance_by_glyph_name[glyph_name] = _rounded_width(
            _axis_length(
                measurement,
                grid=parameters.grid,
                radius=parameters.radius,
            ),
            glyph_name=glyph_name,
        )
    glyph_plans: dict[str, GlyphPlan] = {}
    for glyph_name, layout in vertical_layout_by_glyph_name.items():
        glyph = glyphs[glyph_name]
        y_measurement = y_measurement_by_glyph_name[glyph_name]
        width = _rounded_width(
            (layout.common_x_max - layout.common_x_min) * parameters.grid
            + (layout.common_left_scale + layout.common_right_scale)
            * parameters.radius
            + layout.left_spacing
            + layout.right_spacing,
            glyph_name=glyph_name,
        )
        glyph_plans[glyph_name] = GlyphPlan(
            name=glyph.name,
            codepoint=glyph.codepoint,
            source_path=glyph.source_path,
            width=width,
            strokes=_transformed_strokes(
                glyph.skeleton,
                grid=parameters.grid,
                radius=parameters.radius,
                grid_x_offset=(
                    glyph.monospace_x_offset - layout.common_x_min
                ),
                grid_y_offset=glyph.y_offset,
                font_x_shift=(
                    layout.left_spacing
                    + layout.common_left_scale * parameters.radius
                ),
                font_y_shift=(
                    y_measurement.start_scale * parameters.radius
                ),
            ),
        )

    planned: dict[str, MathGlyphAssemblyPlan] = {}
    for base, construction in constructions.items():
        part_plans = tuple(
            _assembly_part_plan(
                part_data,
                full_advance=full_advance_by_glyph_name[
                    part_data.glyph_name
                ],
                grid=parameters.grid,
                axis_name="vertical",
            )
            for part_data in construction.parts
        )
        assembly = MathGlyphAssemblyPlan(
            italic_correction=construction.italic_correction,
            parts=part_plans,
        )
        _validate_connector_overlaps(
            base,
            assembly,
            minimum_overlap,
            axis_name="vertical",
        )
        planned[base] = assembly
    return _AssemblyPlans(
        glyph_plans=MappingProxyType(glyph_plans),
        assembly_plans=MappingProxyType(planned),
    )


def _plan_horizontal_assemblies(
    constructions: Mapping[str, MathGlyphAssemblyData],
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
    minimum_overlap: int,
) -> _AssemblyPlans:
    if not constructions:
        empty = MappingProxyType({})
        return _AssemblyPlans(glyph_plans=empty, assembly_plans=empty)
    uses_by_glyph_name = _collect_part_uses(
        constructions,
        axis_name="horizontal",
    )
    authored_scales_by_glyph_name = _authored_scales_by_glyph_name(
        uses_by_glyph_name,
        axis_name="horizontal",
    )
    x_measurement_by_glyph_name = MappingProxyType(
        {
            glyph_name: _measure_glyph_axis(
                glyphs[glyph_name],
                axis=0,
                start_scale=authored_scales_by_glyph_name[glyph_name][0],
                end_scale=authored_scales_by_glyph_name[glyph_name][1],
            )
            for glyph_name in uses_by_glyph_name
        }
    )
    full_advance_by_glyph_name: dict[str, int] = {}
    for glyph_name, measurement in x_measurement_by_glyph_name.items():
        if math.isclose(
            measurement.extent,
            0,
            abs_tol=_EDGE_TOLERANCE,
        ):
            raise PlanError(
                f"Math horizontal assembly part {glyph_name!r} has no "
                "positive centerline extent."
            )
        full_advance_by_glyph_name[glyph_name] = _rounded_width(
            _axis_length(
                measurement,
                grid=parameters.grid,
                radius=parameters.radius,
            ),
            glyph_name=glyph_name,
        )
    glyph_plans: dict[str, GlyphPlan] = {}
    for glyph_name, x_measurement in x_measurement_by_glyph_name.items():
        glyph = glyphs[glyph_name]
        glyph_plans[glyph_name] = GlyphPlan(
            name=glyph.name,
            codepoint=glyph.codepoint,
            source_path=glyph.source_path,
            width=full_advance_by_glyph_name[glyph_name],
            strokes=_transformed_strokes(
                glyph.skeleton,
                grid=parameters.grid,
                radius=parameters.radius,
                grid_x_offset=0.0,
                grid_y_offset=glyph.y_offset,
                font_x_shift=x_measurement.start_scale * parameters.radius,
                font_y_shift=parameters.y_shift + parameters.radius,
            ),
        )

    planned: dict[str, MathGlyphAssemblyPlan] = {}
    for base, construction in constructions.items():
        part_plans = tuple(
            _assembly_part_plan(
                part_data,
                full_advance=full_advance_by_glyph_name[
                    part_data.glyph_name
                ],
                grid=parameters.grid,
                axis_name="horizontal",
            )
            for part_data in construction.parts
        )
        assembly = MathGlyphAssemblyPlan(
            italic_correction=construction.italic_correction,
            parts=part_plans,
        )
        _validate_connector_overlaps(
            base,
            assembly,
            minimum_overlap,
            axis_name="horizontal",
        )
        planned[base] = assembly
    return _AssemblyPlans(
        glyph_plans=MappingProxyType(glyph_plans),
        assembly_plans=MappingProxyType(planned),
    )

