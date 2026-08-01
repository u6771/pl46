from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .errors import PlanError
from .model import (
    AssembledFont,
    FontPlan,
    GlyphParameters,
    GlyphSource,
    GlyphSpacingOverride,
    KerningData,
    MathAssemblyPartData,
    MathAssemblyPartPlan,
    MathData,
    MathGlyphAssemblyData,
    MathGlyphAssemblyPlan,
    MathPlan,
    MathVariantRecord,
    Point,
    RealGlyphPlan,
    StrokePlan,
    StrokeRecord,
)


_EDGE_TOLERANCE = 1e-9
_POINT_TOLERANCE = 1e-9
_GlyphRole = Literal[
    "ordinary",
    "vertical_variant_glyph",
    "horizontal_variant_glyph",
    "vertical_part",
    "horizontal_part",
]
_Axis = Literal[0, 1]


@dataclass(frozen=True, slots=True)
class _AxisMeasurement:
    extent: float
    start_scale: float
    end_scale: float


@dataclass(frozen=True, slots=True)
class _VerticalLayout:
    common_x_min: float
    common_x_max: float
    common_left_scale: float
    common_right_scale: float
    left_spacing: float
    right_spacing: float


@dataclass(frozen=True, slots=True)
class _VariantGlyphPlans:
    glyph_plans: Mapping[str, RealGlyphPlan]
    full_advances: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _AssemblyPlans:
    glyph_plans: Mapping[str, RealGlyphPlan]
    assembly_plans: Mapping[str, MathGlyphAssemblyPlan]


def _rounded_width(value: float, *, glyph_name: str) -> int:
    if not math.isfinite(value) or value < 0:
        raise PlanError(
            f"Glyph {glyph_name!r} has invalid resolved width {value!r}."
        )
    return round(value)


def _measure_glyph_axis(
    glyph: GlyphSource,
    *,
    axis: _Axis,
    start_scale: float | None = None,
    end_scale: float | None = None,
) -> _AxisMeasurement:
    """Measure one axis while honoring explicitly authored edge scales."""

    if not glyph.skeleton:
        raise PlanError(f"Glyph {glyph.name!r} has no non-empty skeleton.")
    extent = glyph.x_extent if axis == 0 else glyph.y_extent
    if extent is None:
        raise PlanError(f"Glyph {glyph.name!r} has no y-axis extent.")
    if start_scale is not None and end_scale is not None:
        return _AxisMeasurement(extent, start_scale, end_scale)

    start_candidates: list[float] = []
    end_candidates: list[float] = []
    for stroke in glyph.skeleton:
        coordinates = tuple(point[axis] for point in stroke.centerline)
        if not coordinates:
            continue
        if start_scale is None and math.isclose(
            min(coordinates), 0, abs_tol=_EDGE_TOLERANCE
        ):
            start_candidates.append(stroke.thickness_scale)
        if end_scale is None and math.isclose(
            max(coordinates), extent, abs_tol=_EDGE_TOLERANCE
        ):
            end_candidates.append(stroke.thickness_scale)

    if start_scale is None:
        if not start_candidates:
            raise PlanError(
                f"Glyph {glyph.name!r} has no stroke touching its start edge."
            )
        start_scale = max(start_candidates)
    if end_scale is None:
        if not end_candidates:
            raise PlanError(
                f"Glyph {glyph.name!r} has no stroke touching its end edge."
            )
        end_scale = max(end_candidates)
    return _AxisMeasurement(extent, start_scale, end_scale)


def _axis_length(
    measurement: _AxisMeasurement,
    *,
    grid: float,
    radius: float,
) -> float:
    return (
        measurement.extent * grid
        + (measurement.start_scale + measurement.end_scale) * radius
    )


def _points_equal(first: Point, second: Point) -> bool:
    return math.hypot(first[0] - second[0], first[1] - second[1]) < (
        _POINT_TOLERANCE
    )


def _clean_centerline(points: tuple[Point, ...]) -> tuple[Point, ...]:
    cleaned: list[Point] = []
    for point in points:
        if not cleaned or not _points_equal(point, cleaned[-1]):
            cleaned.append(point)
    return tuple(cleaned)


def _transform_stroke(
    stroke: StrokeRecord,
    *,
    grid: float,
    radius: float,
    grid_x_offset: float,
    grid_y_offset: float,
    font_x_shift: float,
    font_y_shift: float,
) -> StrokePlan:
    transformed = tuple(
        (
            (x + grid_x_offset) * grid + font_x_shift,
            (y + grid_y_offset) * grid + font_y_shift,
        )
        for x, y in stroke.centerline
    )
    centerline = _clean_centerline(transformed)
    if not centerline:
        raise PlanError("Cannot plan a stroke with an empty centerline.")
    closed = (
        len(centerline) > 1
        and _points_equal(centerline[0], centerline[-1])
        and stroke.start_cap != "flat"
        and stroke.end_cap != "flat"
    )
    if closed:
        centerline = centerline[:-1]
        if len(centerline) < 3:
            raise PlanError(
                "A closed stroke needs at least three distinct points."
            )
    if stroke.filled and not closed:
        raise PlanError("filled can only be used with a closed stroke.")
    return StrokePlan(
        centerline=centerline,
        radius=radius * stroke.thickness_scale,
        start_cap=stroke.start_cap,
        end_cap=stroke.end_cap,
        closed=closed,
        filled=stroke.filled,
    )


def _transformed_strokes(
    strokes: tuple[StrokeRecord, ...],
    *,
    grid: float,
    radius: float,
    grid_x_offset: float,
    grid_y_offset: float,
    font_x_shift: float,
    font_y_shift: float,
) -> tuple[StrokePlan, ...]:
    return tuple(
        _transform_stroke(
            stroke,
            grid=grid,
            radius=radius,
            grid_x_offset=grid_x_offset,
            grid_y_offset=grid_y_offset,
            font_x_shift=font_x_shift,
            font_y_shift=font_y_shift,
        )
        for stroke in strokes
    )


def _plan_proportional_real_glyph(
    glyph: GlyphSource,
    parameters: GlyphParameters,
    spacing: GlyphSpacingOverride,
) -> RealGlyphPlan:
    left_spacing = parameters.left_spacing + spacing.left_spacing
    right_spacing = parameters.right_spacing + spacing.right_spacing
    if not glyph.skeleton:
        return RealGlyphPlan(
            name=glyph.name,
            codepoint=glyph.codepoint,
            source_path=glyph.source_path,
            width=_rounded_width(
                glyph.x_extent * parameters.grid
                + left_spacing
                + right_spacing,
                glyph_name=glyph.name,
            ),
            strokes=(),
        )

    authored_scale = None if parameters.use_scaled_edge_thickness else 1.0
    x_measurement = _measure_glyph_axis(
        glyph,
        axis=0,
        start_scale=authored_scale,
        end_scale=authored_scale,
    )
    width = _rounded_width(
        _axis_length(
            x_measurement,
            grid=parameters.grid,
            radius=parameters.radius,
        )
        + left_spacing
        + right_spacing,
        glyph_name=glyph.name,
    )
    return RealGlyphPlan(
        name=glyph.name,
        codepoint=glyph.codepoint,
        source_path=glyph.source_path,
        width=width,
        strokes=_transformed_strokes(
            glyph.skeleton,
            grid=parameters.grid,
            radius=parameters.radius,
            grid_x_offset=0.0,
            grid_y_offset=glyph.y_offset,
            font_x_shift=(
                left_spacing + x_measurement.start_scale * parameters.radius
            ),
            font_y_shift=parameters.y_shift + parameters.radius,
        ),
    )


def _plan_ordinary_glyph(
    glyph: GlyphSource,
    parameters: GlyphParameters,
    spacing: GlyphSpacingOverride,
) -> RealGlyphPlan:
    if parameters.monospace_width is None:
        return _plan_proportional_real_glyph(glyph, parameters, spacing)

    left_spacing = parameters.left_spacing
    right_spacing = parameters.right_spacing
    return RealGlyphPlan(
        name=glyph.name,
        codepoint=glyph.codepoint,
        source_path=glyph.source_path,
        width=_rounded_width(
            parameters.monospace_width + left_spacing + right_spacing,
            glyph_name=glyph.name,
        ),
        strokes=_transformed_strokes(
            glyph.skeleton,
            grid=parameters.grid,
            radius=parameters.radius,
            grid_x_offset=glyph.monospace_x_offset,
            grid_y_offset=glyph.y_offset,
            font_x_shift=left_spacing + parameters.monospace_width / 2,
            font_y_shift=parameters.y_shift + parameters.radius,
        ),
    )


def _plan_variant_glyph(
    glyph: GlyphSource,
    parameters: GlyphParameters,
    spacing: GlyphSpacingOverride,
    *,
    axis: _Axis,
) -> tuple[RealGlyphPlan, int]:
    if not glyph.skeleton:
        raise PlanError(f"Math variant glyph {glyph.name!r} has no skeleton.")

    axis_measurement = _measure_glyph_axis(glyph, axis=axis)
    axis_name = "horizontal" if axis == 0 else "vertical"
    if math.isclose(
        axis_measurement.extent,
        0,
        abs_tol=_EDGE_TOLERANCE,
    ):
        raise PlanError(
            f"Math {axis_name} variant glyph {glyph.name!r} has no positive "
            "centerline extent."
        )
    authored_x_scale = (
        None if parameters.use_scaled_edge_thickness else 1.0
    )
    x_measurement = (
        axis_measurement
        if axis == 0 and authored_x_scale is None
        else _measure_glyph_axis(
            glyph,
            axis=0,
            start_scale=authored_x_scale,
            end_scale=authored_x_scale,
        )
    )
    left_spacing = parameters.left_spacing + spacing.left_spacing
    right_spacing = parameters.right_spacing + spacing.right_spacing
    glyph_plan = RealGlyphPlan(
        name=glyph.name,
        codepoint=glyph.codepoint,
        source_path=glyph.source_path,
        width=_rounded_width(
            _axis_length(
                x_measurement,
                grid=parameters.grid,
                radius=parameters.radius,
            )
            + left_spacing
            + right_spacing,
            glyph_name=glyph.name,
        ),
        strokes=_transformed_strokes(
            glyph.skeleton,
            grid=parameters.grid,
            radius=parameters.radius,
            grid_x_offset=0.0,
            grid_y_offset=glyph.y_offset,
            font_x_shift=(
                left_spacing + x_measurement.start_scale * parameters.radius
            ),
            font_y_shift=parameters.y_shift + parameters.radius,
        ),
    )
    full_advance = _rounded_width(
        _axis_length(
            axis_measurement,
            grid=parameters.grid,
            radius=parameters.radius,
        ),
        glyph_name=glyph.name,
    )
    return glyph_plan, full_advance


def _plan_ordinary_glyphs(
    glyphs: Mapping[str, GlyphSource],
    parameters: GlyphParameters,
    spacing_by_name: Mapping[str, GlyphSpacingOverride],
) -> Mapping[str, RealGlyphPlan]:
    empty_spacing = GlyphSpacingOverride(0.0, 0.0)
    return MappingProxyType(
        {
            name: _plan_ordinary_glyph(
                glyph,
                parameters,
                spacing_by_name.get(name, empty_spacing),
            )
            for name, glyph in glyphs.items()
        }
    )


def _plan_variant_glyphs(
    glyphs: Mapping[str, GlyphSource],
    parameters: GlyphParameters,
    spacing_by_name: Mapping[str, GlyphSpacingOverride],
    *,
    axis: _Axis,
) -> _VariantGlyphPlans:
    empty_spacing = GlyphSpacingOverride(0.0, 0.0)
    planned_glyphs: dict[str, RealGlyphPlan] = {}
    full_advances: dict[str, int] = {}
    for name, glyph in glyphs.items():
        plan, full_advance = _plan_variant_glyph(
            glyph,
            parameters,
            spacing_by_name.get(name, empty_spacing),
            axis=axis,
        )
        planned_glyphs[name] = plan
        full_advances[name] = full_advance
    return _VariantGlyphPlans(
        glyph_plans=MappingProxyType(planned_glyphs),
        full_advances=MappingProxyType(full_advances),
    )


def _plan_vertical_variant_glyphs(
    glyphs: Mapping[str, GlyphSource],
    parameters: GlyphParameters,
    spacing_by_name: Mapping[str, GlyphSpacingOverride],
) -> _VariantGlyphPlans:
    return _plan_variant_glyphs(
        glyphs,
        parameters,
        spacing_by_name,
        axis=1,
    )


def _plan_horizontal_variant_glyphs(
    glyphs: Mapping[str, GlyphSource],
    parameters: GlyphParameters,
    spacing_by_name: Mapping[str, GlyphSpacingOverride],
) -> _VariantGlyphPlans:
    return _plan_variant_glyphs(
        glyphs,
        parameters,
        spacing_by_name,
        axis=0,
    )


def _ssty_feature(
    ssty: Mapping[str, tuple[str, ...]],
    glyph_names: set[str],
) -> str | None:
    if not ssty:
        return None
    rules: list[str] = []
    for base, alternates in sorted(ssty.items()):
        missing = {base, *alternates} - glyph_names
        if missing:
            raise PlanError(
                f"Math ssty rule for {base!r} references unknown glyphs: "
                f"{sorted(missing)}"
            )
        if len(alternates) == 1:
            rules.append(f"    sub {base} by {alternates[0]};")
        else:
            rules.append(
                f"    sub {base} from [{alternates[0]} {alternates[1]}];"
            )
    return (
        "feature ssty {\n"
        "    script math;\n"
        "\n"
        + "\n".join(rules)
        + "\n} ssty;\n"
    )


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
    glyphs: Mapping[str, GlyphSource],
    vertical_variant_glyphs: Mapping[str, tuple[str, ...]],
    horizontal_variant_glyphs: Mapping[str, tuple[str, ...]],
    vertical_assemblies: Mapping[str, MathGlyphAssemblyData],
    horizontal_assemblies: Mapping[str, MathGlyphAssemblyData],
) -> Mapping[_GlyphRole, Mapping[str, GlyphSource]]:
    glyph_names = set(glyphs)
    role_members: tuple[tuple[_GlyphRole, set[str]], ...] = (
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
            f"Math constructions reference unknown real glyphs: {sorted(missing)}"
        )

    grouped: dict[_GlyphRole, dict[str, GlyphSource]] = {
        "ordinary": {},
        "vertical_variant_glyph": {},
        "horizontal_variant_glyph": {},
        "vertical_part": {},
        "horizontal_part": {},
    }
    for name, glyph in glyphs.items():
        memberships = [role for role, members in role_members if name in members]
        if len(memberships) > 1:
            raise PlanError(
                f"Math glyph {name!r} belongs to multiple construction roles: "
                f"{memberships}."
            )
        role: _GlyphRole = memberships[0] if memberships else "ordinary"
        grouped[role][name] = glyph
    return MappingProxyType(
        {
            role: MappingProxyType(entries)
            for role, entries in grouped.items()
        }
    )


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
    glyphs: Mapping[str, GlyphSource],
    parameters: GlyphParameters,
    minimum_overlap: int,
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
    layouts_by_base = MappingProxyType(
        {
            base: _vertical_layout(
                construction.parts,
                bounds_by_glyph_name,
                left_spacing=parameters.left_spacing,
                right_spacing=parameters.right_spacing,
            )
            for base, construction in constructions.items()
        }
    )

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
    glyph_plans: dict[str, RealGlyphPlan] = {}
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
        glyph_plans[glyph_name] = RealGlyphPlan(
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
    glyphs: Mapping[str, GlyphSource],
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
    glyph_plans: dict[str, RealGlyphPlan] = {}
    for glyph_name, x_measurement in x_measurement_by_glyph_name.items():
        glyph = glyphs[glyph_name]
        glyph_plans[glyph_name] = RealGlyphPlan(
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


def _validate_kerning(
    glyph_names: set[str],
    kerning: KerningData | None,
) -> None:
    if kerning is None:
        return
    for group_name, members in kerning.groups.items():
        missing = set(members) - glyph_names
        if missing:
            raise PlanError(
                f"Kerning group {group_name!r} contains unknown glyphs: "
                f"{sorted(missing)}"
            )
    valid_sides = glyph_names | set(kerning.groups)
    for pair in kerning.pairs:
        missing = {pair.left, pair.right} - valid_sides
        if missing:
            raise PlanError(
                "Kerning pair contains unknown glyphs or groups: "
                f"{sorted(missing)}"
            )


def plan_font(
    assembled_font: AssembledFont,
    glyph_config: Mapping[str, GlyphSpacingOverride] | None = None,
    kerning: KerningData | None = None,
    math_data: MathData | None = None,
) -> FontPlan:
    """Resolve all glyph metrics and centerline transforms without file I/O."""

    parameters = assembled_font.glyph_parameters
    config = {} if glyph_config is None else glyph_config
    if parameters.monospace_width is not None and config:
        raise PlanError(
            "Monospace builds cannot use proportional glyph spacing overrides."
        )
    unused_names = set(config) - set(assembled_font.real_glyphs)
    if unused_names:
        raise PlanError(
            "Glyph config contains names not planned as real glyphs: "
            f"{sorted(unused_names)}"
        )
    glyph_names = set(assembled_font.real_glyphs)
    glyph_names.update(
        glyph.target_name for glyph in assembled_font.generated_glyphs
    )
    _validate_kerning(glyph_names, kerning)

    vertical_variant_glyphs = (
        {} if math_data is None else math_data.vertical_variant_glyphs
    )
    horizontal_variant_glyphs = (
        {} if math_data is None else math_data.horizontal_variant_glyphs
    )
    vertical_assemblies = (
        {} if math_data is None else math_data.vertical_assemblies
    )
    horizontal_assemblies = (
        {} if math_data is None else math_data.horizontal_assemblies
    )
    glyphs_by_role = _group_glyphs_by_role(
        assembled_font.real_glyphs,
        vertical_variant_glyphs,
        horizontal_variant_glyphs,
        vertical_assemblies,
        horizontal_assemblies,
    )
    ordinary_glyph_plans = _plan_ordinary_glyphs(
        glyphs_by_role["ordinary"],
        parameters,
        config,
    )
    vertical_variant_glyph_plans = _plan_vertical_variant_glyphs(
        glyphs_by_role["vertical_variant_glyph"],
        parameters,
        config,
    )
    horizontal_variant_glyph_plans = _plan_horizontal_variant_glyphs(
        glyphs_by_role["horizontal_variant_glyph"],
        parameters,
        config,
    )
    minimum_overlap = (
        0 if math_data is None else math_data.min_connector_overlap
    )
    vertical_assembly_plans = _plan_vertical_assemblies(
        vertical_assemblies,
        glyphs_by_role["vertical_part"],
        parameters,
        minimum_overlap,
    )
    horizontal_assembly_plans = _plan_horizontal_assemblies(
        horizontal_assemblies,
        glyphs_by_role["horizontal_part"],
        parameters,
        minimum_overlap,
    )

    real_glyph_plans: dict[str, RealGlyphPlan] = {}
    for role, plans in (
        (
            "ordinary",
            ordinary_glyph_plans,
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
        overlap = set(real_glyph_plans) & set(plans)
        if overlap:
            raise PlanError(
                f"Internal glyph-role overlap while merging {role}: "
                f"{sorted(overlap)}"
            )
        real_glyph_plans.update(plans)

    vertical_variant_records = _plan_variant_records(
        vertical_variant_glyphs,
        vertical_variant_glyph_plans.full_advances,
    )
    horizontal_variant_records = _plan_variant_records(
        horizontal_variant_glyphs,
        horizontal_variant_glyph_plans.full_advances,
    )
    math_plan: MathPlan | None = None
    if math_data is not None:
        math_plan = MathPlan(
            constants=math_data.constants,
            ssty_feature=_ssty_feature(math_data.ssty, glyph_names),
            vertical_variant_records=vertical_variant_records,
            horizontal_variant_records=horizontal_variant_records,
            min_connector_overlap=minimum_overlap,
            vertical_assemblies=vertical_assembly_plans.assembly_plans,
            horizontal_assemblies=horizontal_assembly_plans.assembly_plans,
            extended_shapes=(
                frozenset(vertical_variant_records)
                | frozenset(vertical_assembly_plans.assembly_plans)
            ),
        )

    return FontPlan(
        info=assembled_font.info,
        output_stem=assembled_font.output_stem,
        point_radius_scale=assembled_font.point_radius_scale,
        kerning=kerning,
        math=math_plan,
        real_glyphs=MappingProxyType(real_glyph_plans),
        generated_glyphs=assembled_font.generated_glyphs,
    )
