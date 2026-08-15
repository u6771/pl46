from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from ..errors import PlanError
from ..model import (
    AssembledGlyph,
    GlyphParameters,
    GlyphPlan,
    GlyphSpacingAdjustment,
    Point,
    StrokePlan,
    StrokeRecord,
)
from ..opentype import FWORD_MAX, FWORD_MIN, UFWORD_MAX
from .spacing import _EMPTY_SPACING_ADJUSTMENT, _adjusted_spacing


_EDGE_TOLERANCE = 1e-9
_POINT_TOLERANCE = 1e-9
_Axis = Literal[0, 1]


@dataclass(frozen=True, slots=True)
class _AxisMeasurement:
    extent: float
    start_scale: float
    end_scale: float


@dataclass(frozen=True, slots=True)
class _OrdinaryGlyphPlans:
    glyph_plans: Mapping[str, GlyphPlan]
    top_accent_attachments: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _VariantGlyphPlans:
    glyph_plans: Mapping[str, GlyphPlan]
    full_advances: Mapping[str, int]
    top_accent_attachments: Mapping[str, int]


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
    return _rounded_fword(
        (attachment - glyph.monospace_x_offset) * parameters.grid
        + start_scale * parameters.radius
        + left_spacing,
        location=f"Math top accent attachment for glyph {glyph.name!r}",
    )


def _rounded_fword(value: float, *, location: str) -> int:
    if not math.isfinite(value):
        raise PlanError(f"{location} is not finite: {value!r}.")
    rounded = round(value)
    if not FWORD_MIN <= rounded <= FWORD_MAX:
        raise PlanError(
            f"{location} resolves to {rounded}, outside the OpenType "
            f"FWORD range {FWORD_MIN}..{FWORD_MAX}."
        )
    return rounded


def _rounded_width(value: float, *, glyph_name: str) -> int:
    if not math.isfinite(value) or value < 0:
        raise PlanError(
            f"Glyph {glyph_name!r} has invalid resolved width {value!r}."
        )
    rounded = round(value)
    if rounded > UFWORD_MAX:
        raise PlanError(
            f"Glyph {glyph_name!r} resolves to width {rounded}, outside "
            f"the OpenType UFWORD range 0..{UFWORD_MAX}."
        )
    return rounded


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
            (
                None
                if top_accent_attachment is None
                else _rounded_fword(
                    top_accent_attachment * parameters.grid + left_spacing,
                    location=(
                        "Math top accent attachment for empty glyph "
                        f"{glyph.name!r}"
                    ),
                )
            ),
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


def _plan_ordinary_glyph(
    glyph: AssembledGlyph,
    parameters: GlyphParameters,
    adjustment: GlyphSpacingAdjustment,
    top_accent_attachment: float | None,
) -> tuple[GlyphPlan, int | None]:
    monospace_width = (
        parameters.monospace_width
        if parameters.monospace_width is not None
        else glyph.ordinary_monospace_width
    )
    if monospace_width is None:
        return _plan_proportional_glyph(
            glyph,
            parameters,
            adjustment,
            top_accent_attachment,
        )

    left_spacing = parameters.left_spacing
    right_spacing = parameters.right_spacing
    glyph_plan = GlyphPlan(
        name=glyph.name,
        codepoint=glyph.codepoint,
        source_path=glyph.source_path,
        width=_rounded_width(
            monospace_width + left_spacing + right_spacing,
            glyph_name=glyph.name,
        ),
        strokes=_transformed_strokes(
            glyph.skeleton,
            grid=parameters.grid,
            radius=parameters.radius,
            grid_x_offset=glyph.monospace_x_offset,
            grid_y_offset=glyph.y_offset,
            font_x_shift=left_spacing + monospace_width / 2,
            font_y_shift=parameters.y_shift + parameters.radius,
        ),
    )
    if top_accent_attachment is None:
        return glyph_plan, None
    return (
        glyph_plan,
        _rounded_fword(
            (top_accent_attachment + glyph.monospace_x_offset)
            * parameters.grid
            + left_spacing
            + monospace_width / 2,
            location=f"Math top accent attachment for glyph {glyph.name!r}",
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
    axis_measurement = _measure_glyph_axis(glyph, axis=axis)
    if math.isclose(
        axis_measurement.extent,
        0,
        abs_tol=_EDGE_TOLERANCE,
    ):
        axis_name = "horizontal" if axis == 0 else "vertical"
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
        glyph_plan, planned_attachment = _plan_ordinary_glyph(
            glyph,
            parameters,
            adjustment_by_name.get(name, _EMPTY_SPACING_ADJUSTMENT),
            top_accent_attachments.get(name),
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


def _plan_horizontal_accent_variant_advances(
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
) -> Mapping[str, int]:
    """Measure accent construction bases without replanning their glyphs."""

    advances: dict[str, int] = {}
    for name, glyph in glyphs.items():
        measurement = _measure_glyph_axis(glyph, axis=0)
        if math.isclose(
            measurement.extent,
            0,
            abs_tol=_EDGE_TOLERANCE,
        ):
            raise PlanError(
                f"Math horizontal accent construction base {name!r} has no "
                "positive centerline extent."
            )
        advances[name] = _rounded_width(
            _axis_length(
                measurement,
                grid=parameters.grid,
                radius=parameters.radius,
            ),
            glyph_name=glyph.name,
        )
    return MappingProxyType(advances)
