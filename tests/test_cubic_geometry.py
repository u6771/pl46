from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import pathops
from fontTools.pens.recordingPen import RecordingPen

from skeletonfont.assembler import GlyphCatalog, assemble_font
from skeletonfont.cubic_geometry import (
    _draw_circular_arc,
    merge_stroke_paths,
    stroke_to_path,
)
from skeletonfont.loader import load_font_meta
from skeletonfont.model import StrokePlan
from skeletonfont.planner import plan_font
from skeletonfont.renderer import render_font


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


def _verb_count(path: pathops.Path, verb: pathops.PathVerb) -> int:
    return sum(item == verb for item in path.verbs)


def _outline_digest(glyph) -> str:
    contours = [
        [
            [point.x, point.y, point.type, point.smooth]
            for point in contour.points
        ]
        for contour in glyph.contours
    ]
    payload = json.dumps(
        contours,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


class CubicStrokeGeometryTests(unittest.TestCase):
    def test_round_cap_segment_count_is_rotation_invariant(self) -> None:
        horizontal = StrokePlan(
            ((0.0, 0.0), (100.0, 0.0)),
            10.0,
            "round",
            "round",
            False,
            False,
        )
        diagonal = StrokePlan(
            ((0.0, 0.0), (100.0, 100.0)),
            10.0,
            "round",
            "round",
            False,
            False,
        )

        for stroke in (horizontal, diagonal):
            with self.subTest(stroke=stroke.centerline):
                path = stroke_to_path(stroke, point_radius_scale=1.5)
                self.assertEqual(
                    _verb_count(path, pathops.PathVerb.CUBIC),
                    4,
                )
                self.assertEqual(
                    _verb_count(path, pathops.PathVerb.QUAD),
                    0,
                )

    def test_ninety_degree_join_uses_one_cubic_arc(self) -> None:
        stroke = StrokePlan(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0)),
            10.0,
            "flat",
            "flat",
            False,
            False,
        )

        path = stroke_to_path(stroke, point_radius_scale=1.5)

        self.assertEqual(_verb_count(path, pathops.PathVerb.CUBIC), 1)
        self.assertEqual(_verb_count(path, pathops.PathVerb.QUAD), 0)

    def test_closed_stroke_can_be_hollow_or_filled(self) -> None:
        centerline = (
            (0.0, 0.0),
            (100.0, 0.0),
            (100.0, 100.0),
            (0.0, 100.0),
        )
        hollow = stroke_to_path(
            StrokePlan(
                centerline,
                10.0,
                "round",
                "round",
                True,
                False,
            ),
            point_radius_scale=1.5,
        )
        filled = stroke_to_path(
            StrokePlan(
                centerline,
                10.0,
                "round",
                "round",
                True,
                True,
            ),
            point_radius_scale=1.5,
        )

        self.assertEqual(len(tuple(hollow.contours)), 2)
        self.assertEqual(len(tuple(filled.contours)), 1)
        self.assertEqual(hollow.bounds, filled.bounds)

    def test_filled_closed_path_requires_nonzero_signed_area(self) -> None:
        bowtie = StrokePlan(
            (
                (0.0, 0.0),
                (100.0, 100.0),
                (0.0, 100.0),
                (100.0, 0.0),
            ),
            10.0,
            "round",
            "round",
            True,
            True,
        )

        with self.assertRaisesRegex(ValueError, "non-zero signed area"):
            stroke_to_path(bowtie, point_radius_scale=1.5)

    def test_arc_uses_the_supplied_final_endpoint_exactly(self) -> None:
        pen = RecordingPen()
        start = (3.0, 4.0)
        end = (-4.0, 3.0)

        _draw_circular_arc(
            pen,
            center=(0.0, 0.0),
            start=start,
            end=end,
            clockwise=False,
        )

        _operator, points = pen.value[-1]
        self.assertEqual(points[-1], end)

    def test_multiple_strokes_use_one_nary_union(self) -> None:
        strokes = (
            StrokePlan(
                ((0.0, 0.0), (100.0, 0.0)),
                10.0,
                "round",
                "round",
                False,
                False,
            ),
            StrokePlan(
                ((50.0, -50.0), (50.0, 50.0)),
                10.0,
                "round",
                "round",
                False,
                False,
            ),
        )

        with patch(
            "skeletonfont.cubic_geometry.pathops.union",
            wraps=pathops.union,
        ) as union:
            merge_stroke_paths(strokes, point_radius_scale=1.5)

        union.assert_called_once()


class AsciiCubicGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        assembled = assemble_font(
            meta,
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        cls.font = render_font(plan_font(assembled))
        golden_path = (
            PROJECT_DIRECTORY
            / "tests"
            / "data"
            / "ascii_cubic_outlines.json"
        )
        cls.golden = json.loads(golden_path.read_text(encoding="utf-8"))

    def test_every_ascii_glyph_matches_approved_cubic_outline(self) -> None:
        self.assertEqual(set(self.font.keys()), set(self.golden))
        for name, expected_digest in self.golden.items():
            with self.subTest(glyph=name):
                self.assertEqual(
                    _outline_digest(self.font[name]),
                    expected_digest,
                )


if __name__ == "__main__":
    unittest.main()
