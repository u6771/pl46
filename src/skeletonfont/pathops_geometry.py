"""Experimental pathops-stroke backend kept for outline comparison."""

from __future__ import annotations

from collections.abc import Iterable

import pathops

from .model import Point, StrokePlan


_KAPPA = 0.5522847498307936


def _circle_path(center: Point, radius: float) -> pathops.Path:
    x, y = center
    control = radius * _KAPPA
    path = pathops.Path()
    pen = path.getPen()
    pen.moveTo((x + radius, y))
    pen.curveTo(
        (x + radius, y + control),
        (x + control, y + radius),
        (x, y + radius),
    )
    pen.curveTo(
        (x - control, y + radius),
        (x - radius, y + control),
        (x - radius, y),
    )
    pen.curveTo(
        (x - radius, y - control),
        (x - control, y - radius),
        (x, y - radius),
    )
    pen.curveTo(
        (x + control, y - radius),
        (x + radius, y - control),
        (x + radius, y),
    )
    pen.closePath()
    return path


def _centerline_path(
    points: tuple[Point, ...],
    *,
    closed: bool,
) -> pathops.Path:
    path = pathops.Path()
    pen = path.getPen()
    pen.moveTo(points[0])
    for point in points[1:]:
        pen.lineTo(point)
    if closed:
        pen.closePath()
    return path


def _union_paths(paths: Iterable[pathops.Path]) -> pathops.Path:
    iterator = iter(paths)
    try:
        result = next(iterator)
    except StopIteration:
        return pathops.Path()

    for path in iterator:
        result = pathops.op(result, path, pathops.PathOp.UNION)
    return result


def stroke_to_path(
    stroke: StrokePlan,
    *,
    point_radius_scale: float,
) -> pathops.Path:
    """Expand one planned centerline into a closed outline path."""

    points = stroke.centerline
    if stroke.radius <= 0:
        raise ValueError("Stroke radius must be positive.")
    if point_radius_scale <= 0:
        raise ValueError("Point radius scale must be positive.")

    radius = stroke.radius
    if len(points) == 1:
        return _circle_path(
            points[0],
            radius * point_radius_scale,
        )

    if stroke.closed:
        centerline = _centerline_path(points, closed=True)
        centerline.stroke(
            2 * radius,
            pathops.LineCap.BUTT_CAP,
            pathops.LineJoin.ROUND_JOIN,
            4,
        )
        centerline.convertConicsToQuads()
        if not stroke.filled:
            return centerline

        interior = _centerline_path(points, closed=True)
        return pathops.op(
            centerline,
            interior,
            pathops.PathOp.UNION,
        )

    centerline = _centerline_path(points, closed=False)
    centerline.stroke(
        2 * radius,
        pathops.LineCap.BUTT_CAP,
        pathops.LineJoin.ROUND_JOIN,
        4,
    )
    centerline.convertConicsToQuads()
    parts = [centerline]
    if stroke.start_cap == "round":
        parts.append(_circle_path(points[0], radius))
    if stroke.end_cap == "round":
        parts.append(_circle_path(points[-1], radius))
    return _union_paths(parts)


def merge_stroke_paths(
    strokes: Iterable[StrokePlan],
    *,
    point_radius_scale: float,
) -> pathops.Path:
    """Expand and union all strokes belonging to one glyph."""

    paths = (
        stroke_to_path(
            stroke,
            point_radius_scale=point_radius_scale,
        )
        for stroke in strokes
    )
    result = _union_paths(paths)
    if result.verbs:
        result = pathops.simplify(result)
        result.convertConicsToQuads()
    return result
