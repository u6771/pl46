from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .errors import PlanError
from .model import (
    AssembledFont,
    AssembledGlyph,
    FontPlan,
    GlyphParameters,
    GlyphAdjustment,
    GlyphAdjustmentSelector,
    GlyphSpacingAdjustment,
    KerningData,
    MathAssemblyPartData,
    MathAssemblyPartPlan,
    MathTableData,
    MathGlyphAssemblyData,
    MathGlyphAssemblyPlan,
    MathGlyphKernData,
    MathTablePlan,
    MathVariantRecord,
    Point,
    GlyphPlan,
    StrokePlan,
    StrokeRecord,
    SstyData,
)


_EDGE_TOLERANCE = 1e-9
_POINT_TOLERANCE = 1e-9
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
class _OrdinaryGlyphPlans:
    glyph_plans: Mapping[str, GlyphPlan]
    top_accent_attachments: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _VariantGlyphPlans:
    glyph_plans: Mapping[str, GlyphPlan]
    full_advances: Mapping[str, int]
    top_accent_attachments: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _TopAccentAttachmentInputs:
    ordinary: Mapping[str, float]
    vertical_variant_glyph: Mapping[str, float]
    horizontal_variant_glyph: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class _AssemblyPlans:
    glyph_plans: Mapping[str, GlyphPlan]
    assembly_plans: Mapping[str, MathGlyphAssemblyPlan]


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


def _top_accent_attachment(
    attachment: float | None,
    glyph: AssembledGlyph,
    parameters: GlyphParameters,
    *,
    start_scale: float,
    left_spacing: float,
) -> int | None:
    if attachment is None:
        return None
    return round(
        (attachment - glyph.monospace_x_offset) * parameters.grid
        + start_scale * parameters.radius
        + left_spacing
    )


def _rounded_width(value: float, *, glyph_name: str) -> int:
    if not math.isfinite(value) or value < 0:
        raise PlanError(
            f"Glyph {glyph_name!r} has invalid resolved width {value!r}."
        )
    return round(value)


def _measure_glyph_axis(
    glyph: AssembledGlyph,
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


def _plan_proportional_glyph(
    glyph: AssembledGlyph,
    parameters: GlyphParameters,
    adjustment: GlyphSpacingAdjustment,
    top_accent_attachment: float | None,
) -> tuple[GlyphPlan, int | None]:
    left_spacing, right_spacing = _adjusted_spacing(parameters, adjustment)
    if not glyph.skeleton:
        if top_accent_attachment is not None:
            raise PlanError(
                f"Math top accent attachment glyph {glyph.name!r} has no "
                "non-empty skeleton."
            )
        return (
            GlyphPlan(
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
            ),
            None,
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
    glyph_plan = GlyphPlan(
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
    return (
        glyph_plan,
        _top_accent_attachment(
            top_accent_attachment,
            glyph,
            parameters,
            start_scale=x_measurement.start_scale,
            left_spacing=left_spacing,
        ),
    )


def _plan_monospace_glyph(
    glyph: AssembledGlyph,
    parameters: GlyphParameters,
    top_accent_attachment: float | None,
) -> tuple[GlyphPlan, int | None]:
    assert parameters.monospace_width is not None
    left_spacing = parameters.left_spacing
    right_spacing = parameters.right_spacing
    glyph_plan = GlyphPlan(
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
    if top_accent_attachment is None:
        return glyph_plan, None
    return (
        glyph_plan,
        round(
            (top_accent_attachment + glyph.monospace_x_offset)
            * parameters.grid
            + left_spacing
            + parameters.monospace_width / 2
        ),
    )


def _plan_variant_glyph(
    glyph: AssembledGlyph,
    parameters: GlyphParameters,
    adjustment: GlyphSpacingAdjustment,
    top_accent_attachment: float | None = None,
    *,
    axis: _Axis,
) -> tuple[GlyphPlan, int, int | None]:
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
    left_spacing, right_spacing = _adjusted_spacing(parameters, adjustment)
    glyph_plan = GlyphPlan(
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
    return (
        glyph_plan,
        full_advance,
        _top_accent_attachment(
            top_accent_attachment,
            glyph,
            parameters,
            start_scale=x_measurement.start_scale,
            left_spacing=left_spacing,
        ),
    )


def _plan_ordinary_glyphs(
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
    adjustment_by_name: Mapping[str, GlyphSpacingAdjustment],
    top_accent_attachments: Mapping[str, float],
) -> _OrdinaryGlyphPlans:
    glyph_plans: dict[str, GlyphPlan] = {}
    planned_attachments: dict[str, int] = {}
    for name, glyph in glyphs.items():
        attachment = top_accent_attachments.get(name)
        if parameters.monospace_width is None:
            glyph_plan, planned_attachment = _plan_proportional_glyph(
                glyph,
                parameters,
                adjustment_by_name.get(name, _EMPTY_SPACING_ADJUSTMENT),
                attachment,
            )
        else:
            glyph_plan, planned_attachment = _plan_monospace_glyph(
                glyph,
                parameters,
                attachment,
            )
        glyph_plans[name] = glyph_plan
        if planned_attachment is not None:
            planned_attachments[name] = planned_attachment
    return _OrdinaryGlyphPlans(
        glyph_plans=MappingProxyType(glyph_plans),
        top_accent_attachments=MappingProxyType(planned_attachments),
    )


def _plan_variant_glyphs(
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
    adjustment_by_name: Mapping[str, GlyphSpacingAdjustment],
    top_accent_attachments: Mapping[str, float],
    *,
    axis: _Axis,
) -> _VariantGlyphPlans:
    planned_glyphs: dict[str, GlyphPlan] = {}
    full_advances: dict[str, int] = {}
    planned_attachments: dict[str, int] = {}
    for name, glyph in glyphs.items():
        plan, full_advance, planned_attachment = _plan_variant_glyph(
            glyph,
            parameters,
            adjustment_by_name.get(name, _EMPTY_SPACING_ADJUSTMENT),
            top_accent_attachments.get(name),
            axis=axis,
        )
        planned_glyphs[name] = plan
        full_advances[name] = full_advance
        if planned_attachment is not None:
            planned_attachments[name] = planned_attachment
    return _VariantGlyphPlans(
        glyph_plans=MappingProxyType(planned_glyphs),
        full_advances=MappingProxyType(full_advances),
        top_accent_attachments=MappingProxyType(planned_attachments),
    )


def _plan_vertical_variant_glyphs(
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
    adjustment_by_name: Mapping[str, GlyphSpacingAdjustment],
    top_accent_attachments: Mapping[str, float],
) -> _VariantGlyphPlans:
    return _plan_variant_glyphs(
        glyphs,
        parameters,
        adjustment_by_name,
        top_accent_attachments,
        axis=1,
    )


def _plan_horizontal_variant_glyphs(
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
    adjustment_by_name: Mapping[str, GlyphSpacingAdjustment],
    top_accent_attachments: Mapping[str, float],
) -> _VariantGlyphPlans:
    return _plan_variant_glyphs(
        glyphs,
        parameters,
        adjustment_by_name,
        top_accent_attachments,
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
                f"Ssty rule for {base!r} references unknown glyphs: "
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


def _merge_ssty_substitutions(
    automatic: Mapping[str, tuple[str, ...]],
    explicit: Mapping[str, tuple[str, ...]],
) -> Mapping[str, tuple[str, ...]]:
    overlap = set(automatic) & set(explicit)
    if overlap:
        raise PlanError(
            "Automatic and explicit ssty substitutions both define: "
            f"{sorted(overlap)}"
        )
    return {**automatic, **explicit}


def _inherited_top_accent_attachments(
    source_attachments: Mapping[str, int],
    source_by_target: Mapping[str, str],
) -> Mapping[str, int]:
    return {
        target_name: source_attachments[source_name]
        for target_name, source_name in source_by_target.items()
        if source_name in source_attachments
    }


def _with_ssty_top_accent_attachments(
    authored_attachments: Mapping[str, float],
    source_by_target: Mapping[str, str],
) -> Mapping[str, float]:
    """Give each ssty glyph its source's authored grid coordinate.

    The target glyph later converts this coordinate using its own planned
    metrics.  An explicitly authored target value takes precedence over the
    inherited source value.
    """

    inherited = {
        target_name: authored_attachments[source_name]
        for target_name, source_name in source_by_target.items()
        if source_name in authored_attachments
        and target_name not in authored_attachments
    }
    return MappingProxyType({**inherited, **authored_attachments})


def _plan_accent_glyphs(
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
) -> Mapping[str, GlyphPlan]:
    """Plan zero-advance combining accents around their authored origin."""

    return MappingProxyType(
        {
            name: GlyphPlan(
                name=glyph.name,
                codepoint=glyph.codepoint,
                source_path=glyph.source_path,
                width=0,
                strokes=_transformed_strokes(
                    glyph.skeleton,
                    grid=parameters.grid,
                    radius=parameters.radius,
                    grid_x_offset=glyph.monospace_x_offset,
                    grid_y_offset=glyph.y_offset,
                    font_x_shift=0,
                    font_y_shift=parameters.y_shift + parameters.radius,
                ),
            )
            for name, glyph in glyphs.items()
        }
    )


def _validate_italic_corrections(
    italic_corrections: Mapping[str, int],
    glyph_names: set[str],
) -> Mapping[str, int]:
    missing = set(italic_corrections) - glyph_names
    if missing:
        raise PlanError(
            "Math italic corrections reference unknown glyphs: "
            f"{sorted(missing)}"
        )
    return italic_corrections


def _group_top_accent_attachments_by_role(
    accent_attachments: Mapping[str, float],
    glyphs_by_role: Mapping[_GlyphRole, Mapping[str, AssembledGlyph]],
) -> _TopAccentAttachmentInputs:
    """Validate exact glyph names and divide authored points by role."""

    role_by_name = {
        name: role
        for role, glyphs in glyphs_by_role.items()
        for name in glyphs
    }
    grouped: dict[str, dict[str, float]] = {
        "ordinary": {},
        "vertical_variant_glyph": {},
        "horizontal_variant_glyph": {},
    }
    for name, attachment in accent_attachments.items():
        role = role_by_name.get(name)
        if role is None:
            raise PlanError(
                "Math top accent attachment references a name not planned "
                f"as an assembled glyph: {name!r}."
            )
        if role not in grouped:
            raise PlanError(
                f"Math top accent attachment glyph {name!r} has unsupported "
                f"planning role {role!r}; expected an ordinary or discrete "
                "variant glyph."
            )
        grouped[role][name] = attachment
    return _TopAccentAttachmentInputs(
        ordinary=MappingProxyType(grouped["ordinary"]),
        vertical_variant_glyph=MappingProxyType(
            grouped["vertical_variant_glyph"]
        ),
        horizontal_variant_glyph=MappingProxyType(
            grouped["horizontal_variant_glyph"]
        ),
    )


def _validate_math_kerns_by_role(
    kerns: Mapping[str, MathGlyphKernData],
    glyphs_by_role: Mapping[_GlyphRole, Mapping[str, AssembledGlyph]],
) -> Mapping[str, MathGlyphKernData]:
    """Validate exact math-kern names against supported glyph roles."""

    role_by_name = {
        name: role
        for role, glyphs in glyphs_by_role.items()
        for name in glyphs
    }
    supported_roles = {
        "ordinary",
        "vertical_variant_glyph",
        "horizontal_variant_glyph",
    }
    for name in kerns:
        role = role_by_name.get(name)
        if role is None:
            raise PlanError(
                "Math kern references a name not planned as an assembled "
                "glyph: "
                f"{name!r}."
            )
        if role not in supported_roles:
            raise PlanError(
                f"Math kern glyph {name!r} has unsupported planning role "
                f"{role!r}; expected an ordinary or discrete variant glyph."
            )
    return kerns


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
        if len(memberships) > 1:
            raise PlanError(
                f"Glyph {name!r} belongs to multiple planning roles: "
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
        if (
            role == "ordinary"
            and parameters.monospace_width is not None
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
    glyph_config: Mapping[GlyphAdjustmentSelector, GlyphAdjustment]
    | None = None,
    kerning: KerningData | None = None,
    ssty_data: SstyData | None = None,
    math_table_data: MathTableData | None = None,
    accent_glyphs: frozenset[str] | None = None,
) -> FontPlan:
    """Resolve all glyph metrics and centerline transforms without file I/O."""

    parameters = assembled_font.glyph_parameters
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
    glyphs_by_role = _group_glyphs_by_role(
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
        glyphs_by_role,
        parameters,
        vertical_variant_glyphs,
        horizontal_variant_glyphs,
        vertical_assemblies,
        horizontal_assemblies,
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
        glyphs_by_role,
    )
    validated_math_kerns = _validate_math_kerns_by_role(
        {} if math_table_data is None else math_table_data.kerns,
        glyphs_by_role,
    )
    ordinary_glyph_plans = _plan_ordinary_glyphs(
        glyphs_by_role["ordinary"],
        parameters,
        resolved_spacing_adjustments.glyph_spacing_by_name,
        top_accent_attachment_inputs.ordinary,
    )
    accent_glyph_plans = _plan_accent_glyphs(
        glyphs_by_role["accent"],
        parameters,
    )
    vertical_variant_glyph_plans = _plan_vertical_variant_glyphs(
        glyphs_by_role["vertical_variant_glyph"],
        parameters,
        resolved_spacing_adjustments.glyph_spacing_by_name,
        top_accent_attachment_inputs.vertical_variant_glyph,
    )
    horizontal_variant_glyph_plans = _plan_horizontal_variant_glyphs(
        glyphs_by_role["horizontal_variant_glyph"],
        parameters,
        resolved_spacing_adjustments.glyph_spacing_by_name,
        top_accent_attachment_inputs.horizontal_variant_glyph,
    )
    minimum_overlap = (
        0
        if math_table_data is None
        else math_table_data.min_connector_overlap
    )
    vertical_assembly_plans = _plan_vertical_assemblies(
        vertical_assemblies,
        glyphs_by_role["vertical_part"],
        parameters,
        minimum_overlap,
        resolved_spacing_adjustments.vertical_part_spacing_by_base,
    )
    horizontal_assembly_plans = _plan_horizontal_assemblies(
        horizontal_assemblies,
        glyphs_by_role["horizontal_part"],
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
        horizontal_variant_glyph_plans.full_advances,
    )
    math_table_plan: MathTablePlan | None = None
    if math_table_data is not None:
        planned_top_accent_attachments = {
            **ordinary_glyph_plans.top_accent_attachments,
            **vertical_variant_glyph_plans.top_accent_attachments,
            **horizontal_variant_glyph_plans.top_accent_attachments,
        }
        math_kerns = dict(validated_math_kerns)
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
            kern = validated_math_kerns.get(alias.source_name)
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
            italic_corrections=_validate_italic_corrections(
                math_table_data.italic_corrections,
                glyph_names,
            ),
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
