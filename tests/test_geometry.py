from __future__ import annotations

import unittest

from skeletonfont.pathops_geometry import stroke_to_path
from skeletonfont.model import StrokePlan


class StrokeGeometryTests(unittest.TestCase):
    def test_isolated_point_uses_point_radius_scale(self) -> None:
        stroke = StrokePlan(
            centerline=((100.0, 200.0),),
            radius=20.0,
            start_cap="round",
            end_cap="round",
            closed=False,
            filled=False,
        )

        path = stroke_to_path(stroke, point_radius_scale=1.5)

        self.assertEqual(path.bounds, (70.0, 170.0, 130.0, 230.0))

    def test_open_stroke_supports_different_end_caps(self) -> None:
        stroke = StrokePlan(
            centerline=((0.0, 0.0), (100.0, 0.0)),
            radius=10.0,
            start_cap="flat",
            end_cap="round",
            closed=False,
            filled=False,
        )

        path = stroke_to_path(stroke, point_radius_scale=1.5)

        self.assertEqual(path.bounds, (0.0, -10.0, 110.0, 10.0))

    def test_closed_stroke_can_be_hollow_or_filled(self) -> None:
        centerline = (
            (0.0, 0.0),
            (100.0, 0.0),
            (100.0, 100.0),
            (0.0, 100.0),
        )
        hollow = StrokePlan(
            centerline,
            10.0,
            "round",
            "round",
            True,
            False,
        )
        filled = StrokePlan(
            centerline,
            10.0,
            "round",
            "round",
            True,
            True,
        )

        hollow_path = stroke_to_path(hollow, point_radius_scale=1.5)
        filled_path = stroke_to_path(filled, point_radius_scale=1.5)

        self.assertEqual(len(tuple(hollow_path.contours)), 2)
        self.assertEqual(len(tuple(filled_path.contours)), 1)
        self.assertEqual(hollow_path.bounds, filled_path.bounds)

if __name__ == "__main__":
    unittest.main()
