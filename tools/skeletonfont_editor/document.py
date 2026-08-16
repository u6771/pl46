from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from skeletonfont.errors import ProjectDataError
from skeletonfont.glyph_source_io import glyph_source_data, parse_glyph_source
from skeletonfont.model import CapStyle, GlyphSource, Point, StrokeRecord

from .identity import glyph_filename


def format_codepoint(codepoint: int | None) -> str:
    return "" if codepoint is None else f"{codepoint:04X}"


def parse_number(text: str, *, field_name: str) -> float:
    try:
        value = float(text.strip())
    except ValueError as error:
        raise ValueError(f"{field_name} must be a number.") from error
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite.")
    return value


def _signed_area(points: list[Point]) -> float:
    open_points = points[:-1] if points and points[0] == points[-1] else points
    return sum(
        start[0] * end[1] - end[0] * start[1]
        for start, end in zip(open_points, open_points[1:] + open_points[:1])
    ) / 2


@dataclass(slots=True)
class EditableStroke:
    centerline: list[Point]
    thickness_scale: float = 1.0
    start_cap: CapStyle = "round"
    end_cap: CapStyle = "round"
    filled: bool = False

    @classmethod
    def from_record(cls, record: StrokeRecord) -> EditableStroke:
        return cls(
            centerline=list(record.centerline),
            thickness_scale=record.thickness_scale,
            start_cap=record.start_cap,
            end_cap=record.end_cap,
            filled=record.filled,
        )

    def to_record(self) -> StrokeRecord:
        if not self.centerline:
            raise ProjectDataError("A stroke centerline cannot be empty.")
        if not math.isfinite(self.thickness_scale) or self.thickness_scale <= 0:
            raise ProjectDataError("thickness_scale must be finite and positive.")
        if self.start_cap not in ("round", "flat"):
            raise ProjectDataError("start_cap must be round or flat.")
        if self.end_cap not in ("round", "flat"):
            raise ProjectDataError("end_cap must be round or flat.")
        if self.filled:
            if len(self.centerline) < 4 or self.centerline[0] != self.centerline[-1]:
                raise ProjectDataError(
                    "A filled stroke must be a closed centerline with at least "
                    "three distinct points."
                )
            if len(set(self.centerline[:-1])) < 3:
                raise ProjectDataError(
                    "A filled stroke needs at least three distinct points."
                )
            if abs(_signed_area(self.centerline)) < 1e-9:
                raise ProjectDataError(
                    "A filled stroke needs non-zero signed area."
                )
        return StrokeRecord(
            centerline=tuple(self.centerline),
            thickness_scale=self.thickness_scale,
            start_cap=self.start_cap,
            end_cap=self.end_cap,
            filled=self.filled,
        )


@dataclass(slots=True)
class EditorDocument:
    name: str = ""
    codepoint: int | None = None
    monospace_x_offset: float = 0.0
    y_offset: float = 0.0
    x_extent: float | None = None
    strokes: list[EditableStroke] = field(default_factory=list)
    source_path: Path | None = None
    locked_identity: tuple[str, int | None] | None = None
    dirty: bool = False

    @classmethod
    def from_source(cls, source: GlyphSource) -> EditorDocument:
        return cls(
            name=source.name,
            codepoint=source.codepoint,
            monospace_x_offset=source.monospace_x_offset,
            y_offset=source.y_offset,
            x_extent=None if source.skeleton else source.x_extent,
            strokes=[EditableStroke.from_record(item) for item in source.skeleton],
            source_path=source.source_path,
            locked_identity=(source.name, source.codepoint),
            dirty=False,
        )

    def to_validated_source(self, path: Path) -> GlyphSource:
        name = self.name.strip()
        if not name:
            raise ProjectDataError("Glyph name cannot be empty.")
        if (
            self.locked_identity is not None
            and (name, self.codepoint) != self.locked_identity
        ):
            raise ProjectDataError(
                "An existing glyph's name and Unicode cannot be changed; "
                "use Save As to create a new glyph source."
            )
        if bool(self.strokes) == (self.x_extent is not None):
            raise ProjectDataError(
                "A glyph must define exactly one of skeleton and x_extent."
            )
        if self.x_extent is not None:
            if not math.isfinite(self.x_extent) or self.x_extent < 0:
                raise ProjectDataError("x_extent must be finite and non-negative.")
        skeleton = tuple(stroke.to_record() for stroke in self.strokes)
        points = tuple(
            point
            for stroke in skeleton
            for point in stroke.centerline
        )
        if skeleton and not points:
            raise ProjectDataError(
                "A non-empty skeleton must contain at least one point."
            )
        if skeleton:
            x_extent = max(point[0] for point in points)
            y_extent: float | None = max(point[1] for point in points)
        else:
            assert self.x_extent is not None
            x_extent = self.x_extent
            y_extent = None
        source = GlyphSource(
            name=name,
            codepoint=self.codepoint,
            monospace_x_offset=self.monospace_x_offset,
            y_offset=self.y_offset,
            x_extent=x_extent,
            y_extent=y_extent,
            skeleton=skeleton,
            source_path=path,
        )
        return parse_glyph_source(glyph_source_data(source), source_path=path)

    def normalize_skeleton(self) -> None:
        """Normalize stored points while preserving their canvas positions."""

        all_display_points = [
            self.display_point(point)
            for stroke in self.strokes
            for point in stroke.centerline
        ]
        if not all_display_points:
            return

        x_offset = min(point[0] for point in all_display_points)
        y_offset = min(point[1] for point in all_display_points)
        for stroke in self.strokes:
            stroke.centerline = [
                (point[0] - x_offset, point[1] - y_offset)
                for point in (
                    self.display_point(stored_point)
                    for stored_point in stroke.centerline
                )
            ]
        self.monospace_x_offset = x_offset
        self.y_offset = y_offset

    def display_point(self, point: Point) -> Point:
        return (
            point[0] + self.monospace_x_offset,
            point[1] + self.y_offset,
        )

    def stored_point(self, point: Point) -> Point:
        return (
            point[0] - self.monospace_x_offset,
            point[1] - self.y_offset,
        )
