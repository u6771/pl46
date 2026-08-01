from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import pathops

from .model import Point, StrokePlan


_EPSILON = 1e-9
_KAPPA = 4 / 3 * math.tan(math.pi / 8)
_LEFT = 1.0
_RIGHT = -1.0


class SegmentPen(Protocol):
    def moveTo(self, point: Point) -> None: ...

    def lineTo(self, point: Point) -> None: ...

    def curveTo(
        self,
        control1: Point,
        control2: Point,
        point: Point,
    ) -> None: ...

    def closePath(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SegmentFrame:
    tangent: Point
    normal: Point


@dataclass(frozen=True, slots=True)
class LineSegment:
    start: Point
    end: Point

    def draw(self, pen: SegmentPen) -> None:
        pen.lineTo(self.end)

    def reversed(self) -> LineSegment:
        return type(self)(self.end, self.start)


@dataclass(frozen=True, slots=True)
class ArcSegment:
    center: Point
    start: Point
    end: Point
    clockwise: bool

    def draw(self, pen: SegmentPen) -> None:
        _draw_circular_arc(
            pen,
            center=self.center,
            start=self.start,
            end=self.end,
            clockwise=self.clockwise,
        )

    def reversed(self) -> ArcSegment:
        return type(self)(
            center=self.center,
            start=self.end,
            end=self.start,
            clockwise=not self.clockwise,
        )


OutlineSegment = LineSegment | ArcSegment


@dataclass(frozen=True, slots=True)
class SideJoin:
    entry: Point
    exit: Point
    arc: ArcSegment | None


@dataclass(frozen=True, slots=True)
class VertexJoin:
    left: SideJoin
    right: SideJoin


def _add(first: Point, second: Point) -> Point:
    return first[0] + second[0], first[1] + second[1]


def _subtract(first: Point, second: Point) -> Point:
    return first[0] - second[0], first[1] - second[1]


def _scale(vector: Point, factor: float) -> Point:
    return vector[0] * factor, vector[1] * factor


def _cross(first: Point, second: Point) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _signed_area(points: tuple[Point, ...]) -> float:
    return sum(
        _cross(start, end)
        for start, end in zip(points, points[1:] + points[:1])
    ) / 2


def _normalize(vector: Point) -> Point:
    length = math.hypot(vector[0], vector[1])
    if length < _EPSILON:
        raise ValueError("Cannot normalize a zero-length vector.")
    return vector[0] / length, vector[1] / length


def _left_normal(tangent: Point) -> Point:
    return -tangent[1], tangent[0]


def _line_intersection(
    first_point: Point,
    first_direction: Point,
    second_point: Point,
    second_direction: Point,
) -> Point | None:
    denominator = _cross(first_direction, second_direction)
    if abs(denominator) < _EPSILON:
        return None
    distance = (
        _cross(
            _subtract(second_point, first_point),
            second_direction,
        )
        / denominator
    )
    return _add(first_point, _scale(first_direction, distance))


def _frame(start: Point, end: Point) -> SegmentFrame:
    tangent = _normalize(_subtract(end, start))
    return SegmentFrame(tangent, _left_normal(tangent))


def _open_frames(points: tuple[Point, ...]) -> tuple[SegmentFrame, ...]:
    return tuple(_frame(start, end) for start, end in zip(points, points[1:]))


def _closed_frames(points: tuple[Point, ...]) -> tuple[SegmentFrame, ...]:
    return tuple(
        _frame(point, points[(index + 1) % len(points)])
        for index, point in enumerate(points)
    )


def _offset_point(
    center: Point,
    normal: Point,
    radius: float,
    side: float,
) -> Point:
    return _add(center, _scale(normal, radius * side))


def _side_join(
    center: Point,
    previous: SegmentFrame,
    current: SegmentFrame,
    radius: float,
    side: float,
) -> SideJoin:
    turn = _cross(previous.tangent, current.tangent)
    previous_point = _offset_point(
        center,
        previous.normal,
        radius,
        side,
    )
    current_point = _offset_point(
        center,
        current.normal,
        radius,
        side,
    )

    if turn * side > _EPSILON:
        intersection = _line_intersection(
            previous_point,
            previous.tangent,
            current_point,
            current.tangent,
        )
        target = current_point if intersection is None else intersection
        return SideJoin(target, target, None)

    if turn * side < -_EPSILON:
        return SideJoin(
            entry=previous_point,
            exit=current_point,
            arc=ArcSegment(
                center=center,
                start=previous_point,
                end=current_point,
                clockwise=side == _LEFT,
            ),
        )

    return SideJoin(current_point, current_point, None)


def _vertex_join(
    center: Point,
    previous: SegmentFrame,
    current: SegmentFrame,
    radius: float,
) -> VertexJoin:
    return VertexJoin(
        left=_side_join(center, previous, current, radius, _LEFT),
        right=_side_join(center, previous, current, radius, _RIGHT),
    )


def _draw_circular_arc(
    pen: SegmentPen,
    *,
    center: Point,
    start: Point,
    end: Point,
    clockwise: bool,
) -> None:
    start_vector = _subtract(start, center)
    end_vector = _subtract(end, center)
    radius = math.hypot(*start_vector)
    if radius < _EPSILON:
        pen.lineTo(end)
        return

    start_angle = math.atan2(start_vector[1], start_vector[0])
    end_angle = math.atan2(end_vector[1], end_vector[0])
    if clockwise:
        while end_angle >= start_angle:
            end_angle -= 2 * math.pi
    else:
        while end_angle <= start_angle:
            end_angle += 2 * math.pi

    total_angle = end_angle - start_angle
    segment_count = max(
        1,
        math.ceil((abs(total_angle) - _EPSILON) / (math.pi / 2)),
    )
    angle_step = total_angle / segment_count
    angle0 = start_angle

    for segment_index in range(segment_count):
        angle1 = angle0 + angle_step
        point0 = (
            start
            if segment_index == 0
            else (
                center[0] + radius * math.cos(angle0),
                center[1] + radius * math.sin(angle0),
            )
        )
        point1 = (
            end
            if segment_index == segment_count - 1
            else (
                center[0] + radius * math.cos(angle1),
                center[1] + radius * math.sin(angle1),
            )
        )
        tangent0 = (-math.sin(angle0), math.cos(angle0))
        tangent1 = (-math.sin(angle1), math.cos(angle1))
        control_distance = (
            4 / 3 * math.tan(angle_step / 4) * radius
        )
        control1 = _add(
            point0,
            _scale(tangent0, control_distance),
        )
        control2 = _subtract(
            point1,
            _scale(tangent1, control_distance),
        )
        pen.curveTo(control1, control2, point1)
        angle0 = angle1


def _draw_round_cap(
    pen: SegmentPen,
    *,
    center: Point,
    frame: SegmentFrame,
    radius: float,
    at_end: bool,
) -> None:
    control_distance = _KAPPA * radius
    tangent = frame.tangent
    normal = frame.normal

    if at_end:
        left = _add(center, _scale(normal, radius))
        right = _subtract(center, _scale(normal, radius))
        outer = _add(center, _scale(tangent, radius))
        pen.curveTo(
            _add(left, _scale(tangent, control_distance)),
            _add(outer, _scale(normal, control_distance)),
            outer,
        )
        pen.curveTo(
            _subtract(outer, _scale(normal, control_distance)),
            _add(right, _scale(tangent, control_distance)),
            right,
        )
        return

    right = _subtract(center, _scale(normal, radius))
    left = _add(center, _scale(normal, radius))
    outer = _subtract(center, _scale(tangent, radius))
    pen.curveTo(
        _subtract(right, _scale(tangent, control_distance)),
        _subtract(outer, _scale(normal, control_distance)),
        outer,
    )
    pen.curveTo(
        _add(outer, _scale(normal, control_distance)),
        _subtract(left, _scale(tangent, control_distance)),
        left,
    )


def _side_segments(
    start: Point,
    joins: Iterable[SideJoin],
    end: Point,
) -> tuple[OutlineSegment, ...]:
    segments: list[OutlineSegment] = []
    cursor = start
    for join in joins:
        segments.append(LineSegment(cursor, join.entry))
        if join.arc is not None:
            segments.append(join.arc)
        cursor = join.exit
    segments.append(LineSegment(cursor, end))
    return tuple(segments)


def _draw_segments(
    pen: SegmentPen,
    segments: tuple[OutlineSegment, ...],
    *,
    reverse: bool = False,
) -> None:
    if reverse:
        for segment in reversed(segments):
            segment.reversed().draw(pen)
        return
    for segment in segments:
        segment.draw(pen)


def _point_path(
    point: Point,
    radius: float,
    point_radius_scale: float,
) -> pathops.Path:
    radius *= point_radius_scale
    start = (point[0] + radius, point[1])
    path = pathops.Path()
    pen = path.getPen()
    pen.moveTo(start)
    _draw_circular_arc(
        pen,
        center=point,
        start=start,
        end=start,
        clockwise=False,
    )
    pen.closePath()
    return path


def _open_path(
    stroke: StrokePlan,
) -> pathops.Path:
    points = stroke.centerline
    radius = stroke.radius
    frames = _open_frames(points)
    first = frames[0]
    last = frames[-1]
    start_left = _offset_point(points[0], first.normal, radius, _LEFT)
    start_right = _offset_point(points[0], first.normal, radius, _RIGHT)
    end_left = _offset_point(points[-1], last.normal, radius, _LEFT)
    end_right = _offset_point(points[-1], last.normal, radius, _RIGHT)

    joins = tuple(
        _vertex_join(
            points[index],
            frames[index - 1],
            frames[index],
            radius,
        )
        for index in range(1, len(points) - 1)
    )
    left_segments = _side_segments(
        start_left,
        (join.left for join in joins),
        end_left,
    )
    right_segments = _side_segments(
        start_right,
        (join.right for join in joins),
        end_right,
    )

    path = pathops.Path()
    pen = path.getPen()
    pen.moveTo(start_left)
    _draw_segments(pen, left_segments)
    if stroke.end_cap == "round":
        _draw_round_cap(
            pen,
            center=points[-1],
            frame=last,
            radius=radius,
            at_end=True,
        )
    else:
        pen.lineTo(end_right)
    _draw_segments(pen, right_segments, reverse=True)
    if stroke.start_cap == "round":
        _draw_round_cap(
            pen,
            center=points[0],
            frame=first,
            radius=radius,
            at_end=False,
        )
    else:
        pen.lineTo(start_left)
    pen.closePath()
    return path


def _draw_closed_side(
    pen: SegmentPen,
    joins: tuple[SideJoin, ...],
    *,
    reverse: bool,
) -> None:
    count = len(joins)
    if reverse:
        pen.moveTo(joins[0].entry)
        for step in range(1, count + 1):
            join = joins[(-step) % count]
            pen.lineTo(join.exit)
            if join.arc is not None:
                join.arc.reversed().draw(pen)
        pen.closePath()
        return

    pen.moveTo(joins[0].exit)
    for step in range(1, count + 1):
        join = joins[step % count]
        pen.lineTo(join.entry)
        if join.arc is not None:
            join.arc.draw(pen)
    pen.closePath()


def _closed_path(
    stroke: StrokePlan,
) -> pathops.Path:
    points = stroke.centerline
    radius = stroke.radius
    frames = _closed_frames(points)
    vertex_joins = tuple(
        _vertex_join(
            center,
            frames[(index - 1) % len(frames)],
            frames[index],
            radius,
        )
        for index, center in enumerate(points)
    )
    left_joins = tuple(join.left for join in vertex_joins)
    right_joins = tuple(join.right for join in vertex_joins)

    path = pathops.Path()
    pen = path.getPen()
    if stroke.filled:
        signed_area = _signed_area(points)
        if abs(signed_area) < _EPSILON:
            raise ValueError(
                "A filled closed stroke needs non-zero signed area."
            )
        if signed_area > 0:
            _draw_closed_side(pen, right_joins, reverse=True)
        else:
            _draw_closed_side(pen, left_joins, reverse=False)
        return path

    _draw_closed_side(pen, left_joins, reverse=False)
    _draw_closed_side(pen, right_joins, reverse=True)
    return path


def stroke_to_path(
    stroke: StrokePlan,
    *,
    point_radius_scale: float,
) -> pathops.Path:
    """Expand one planned centerline with cubic round joins and caps."""

    if stroke.radius <= 0:
        raise ValueError("Stroke radius must be positive.")
    if point_radius_scale <= 0:
        raise ValueError("Point radius scale must be positive.")
    points = stroke.centerline
    if len(points) == 1:
        return _point_path(
            points[0],
            stroke.radius,
            point_radius_scale,
        )

    if stroke.closed:
        return _closed_path(stroke)
    return _open_path(stroke)


def merge_stroke_paths(
    strokes: Iterable[StrokePlan],
    *,
    point_radius_scale: float,
) -> pathops.Path:
    """Expand strokes, union all of them together, then simplify once."""

    paths = [
        stroke_to_path(
            stroke,
            point_radius_scale=point_radius_scale,
        )
        for stroke in strokes
    ]
    if not paths:
        return pathops.Path()
    if len(paths) == 1:
        return pathops.simplify(paths[0])

    result = pathops.Path()
    pathops.union(paths, result.getPen())
    return pathops.simplify(result)
