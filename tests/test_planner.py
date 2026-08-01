from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from skeletonfont.assembler import GlyphCatalog, assemble_font
from skeletonfont.errors import PlanError, ProjectDataError
from skeletonfont.loader import (
    load_font_meta,
    load_glyph_config,
    load_kerning_data,
    load_math_data,
    parse_glyph_config,
)
from skeletonfont.model import (
    GlyphSpacingOverride,
    MathAssemblyPartData,
    MathGlyphAssemblyData,
    StrokeRecord,
)
from skeletonfont.planner import (
    _measure_glyph_axis,
    _transform_stroke,
    _transformed_strokes,
    plan_font,
)


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


def assembled_font(build_name: str):
    meta = load_font_meta(PROJECT_DIRECTORY, build_name)
    return assemble_font(meta, GlyphCatalog(PROJECT_DIRECTORY))


class GlyphConfigLoaderTests(unittest.TestCase):
    def test_math_spacing_overrides_are_typed_and_read_only(self) -> None:
        config = load_glyph_config(PROJECT_DIRECTORY, "math.json")

        self.assertEqual(len(config), 13)
        self.assertEqual(
            config["parenleft"],
            GlyphSpacingOverride(50.0, 0.0),
        )
        self.assertEqual(
            config["bar"],
            GlyphSpacingOverride(50.0, 50.0),
        )
        with self.assertRaises(TypeError):
            config["A"] = GlyphSpacingOverride(0, 0)  # type: ignore[index]

    def test_unknown_glyph_config_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "width"):
            parse_glyph_config(
                {"A": {"width": 500}},
                source_path=Path("config.json"),
            )

    def test_empty_glyph_config_entry_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "no spacing"):
            parse_glyph_config(
                {"A": {}},
                source_path=Path("config.json"),
            )


class FontPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.meta = load_font_meta(PROJECT_DIRECTORY, "math")
        cls.assembled_math = assemble_font(
            cls.meta,
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        cls.math_config = load_glyph_config(
            PROJECT_DIRECTORY,
            "math.json",
        )
        assert cls.meta.math_config is not None
        cls.math_data = load_math_data(
            PROJECT_DIRECTORY, cls.meta.math_config
        )
        cls.math_plan = plan_font(
            cls.assembled_math,
            cls.math_config,
            math_data=cls.math_data,
        )

    def test_math_font_plan_has_resolved_glyphs_and_output(self) -> None:
        plan = self.math_plan

        self.assertEqual(plan.output_stem, "PL46-Math")
        self.assertEqual(plan.point_radius_scale, 1.6)
        self.assertEqual(
            len(plan.real_glyphs) + len(plan.generated_glyphs),
            1198,
        )
        self.assertEqual(
            sum(
                glyph.codepoint is not None
                for glyph in plan.real_glyphs.values()
            )
            + len(plan.generated_glyphs),
            1033,
        )
        self.assertEqual(plan.real_glyphs[".notdef"].width, 600)
        self.assertTrue(plan.real_glyphs[".notdef"].strokes)
        with self.assertRaises(TypeError):
            plan.real_glyphs["new"] = plan.real_glyphs["A"]  # type: ignore[index]

    def test_math_plan_resolves_ssty_and_variant_advances(self) -> None:
        math_plan = self.math_plan.math
        assert math_plan is not None

        self.assertIn("sub minute by minute.st;", math_plan.ssty_feature)
        self.assertEqual(len(math_plan.vertical_variant_records), 36)
        self.assertEqual(len(math_plan.horizontal_variant_records), 6)
        self.assertIn("parenleft", math_plan.extended_shapes)
        self.assertEqual(
            [
                (record.glyph_name, record.full_advance)
                for record in math_plan.vertical_variant_records["parenleft"]
            ],
            [
                ("parenleft", 850),
                ("parenleft.v1", 1050),
                ("parenleft.v2", 1250),
                ("parenleft.v3", 1450),
                ("parenleft.v4", 1670),
                ("parenleft.v5", 1870),
                ("parenleft.v6", 2070),
                ("parenleft.v7", 2270),
            ],
        )

    def test_monospace_variant_alternates_use_proportional_metrics(self) -> None:
        parameters = replace(
            self.assembled_math.glyph_parameters,
            monospace_width=900,
        )
        assembled = replace(
            self.assembled_math,
            glyph_parameters=parameters,
        )

        plan = plan_font(assembled, math_data=self.math_data)

        self.assertEqual(plan.real_glyphs["parenleft"].width, 400)
        self.assertEqual(plan.real_glyphs["parenleft.v4"].width, 620)
        self.assertEqual(
            plan.real_glyphs["parenleft"].strokes[0].centerline[0][0],
            300,
        )
        self.assertEqual(
            plan.real_glyphs["parenleft.v4"].strokes[0].centerline[0][0],
            510,
        )

    def test_horizontal_variant_glyphs_use_horizontal_full_advance(self) -> None:
        math_data = replace(
            self.math_data,
            vertical_variant_glyphs=MappingProxyType({}),
            horizontal_variant_glyphs=MappingProxyType(
                {"equal": ("arrowleft",)}
            ),
            vertical_assemblies=MappingProxyType({}),
            horizontal_assemblies=MappingProxyType({}),
            min_connector_overlap=0,
        )

        plan = plan_font(
            self.assembled_math,
            self.math_config,
            math_data=math_data,
        )
        assert plan.math is not None

        self.assertEqual(
            [
                (record.glyph_name, record.full_advance)
                for record in plan.math.horizontal_variant_records["equal"]
            ],
            [("equal", 650), ("arrowleft", 850)],
        )
        self.assertEqual(plan.math.extended_shapes, set())

    def test_assemblies_resolve_part_roles_and_common_vertical_metrics(self) -> None:
        vertical = MathGlyphAssemblyData(
            italic_correction=10,
            parts=(
                MathAssemblyPartData(
                    glyph_name="parenleft.v1",
                    start_connector_extent=0,
                    end_connector_extent=0.5,
                    start_scale=0,
                    end_scale=None,
                    extender=False,
                ),
                MathAssemblyPartData(
                    glyph_name="radical.v1",
                    start_connector_extent=0.5,
                    end_connector_extent=0.5,
                    start_scale=None,
                    end_scale=2,
                    extender=True,
                ),
            ),
        )
        horizontal = MathGlyphAssemblyData(
            italic_correction=0,
            parts=(
                MathAssemblyPartData(
                    glyph_name="equal",
                    start_connector_extent=0.5,
                    end_connector_extent=0.5,
                    start_scale=0,
                    end_scale=0,
                    extender=True,
                ),
                MathAssemblyPartData(
                    glyph_name="arrowleft",
                    start_connector_extent=0.5,
                    end_connector_extent=0,
                    start_scale=0,
                    end_scale=None,
                    extender=False,
                ),
            ),
        )
        math_data = replace(
            self.math_data,
            min_connector_overlap=20,
            vertical_variant_glyphs=MappingProxyType({"parenleft": ()}),
            horizontal_variant_glyphs=MappingProxyType({"arrowright": ()}),
            vertical_assemblies=MappingProxyType({"parenleft": vertical}),
            horizontal_assemblies=MappingProxyType(
                {"arrowright": horizontal}
            ),
        )

        plan = plan_font(
            self.assembled_math,
            self.math_config,
            math_data=math_data,
        )
        math_plan = plan.math
        assert math_plan is not None

        paren_part = plan.real_glyphs["parenleft.v1"]
        radical_part = plan.real_glyphs["radical.v1"]
        self.assertEqual(paren_part.width, 800)
        self.assertEqual(radical_part.width, 800)
        self.assertEqual(
            paren_part.strokes[0].centerline[0],
            (500.0, 700.0),
        )

        vertical_plan = math_plan.vertical_assemblies["parenleft"]
        self.assertEqual(vertical_plan.italic_correction, 10)
        self.assertEqual(
            [
                (
                    part.glyph_name,
                    part.start_connector_length,
                    part.end_connector_length,
                    part.full_advance,
                    part.extender,
                )
                for part in vertical_plan.parts
            ],
            [
                ("parenleft.v1", 0, 50, 1025, False),
                ("radical.v1", 50, 50, 1075, True),
            ],
        )

        equal_part = plan.real_glyphs["equal"]
        self.assertEqual(equal_part.width, 600)
        self.assertEqual(equal_part.strokes[0].centerline[0], (0.0, 325.0))
        self.assertEqual(math_plan.min_connector_overlap, 20)
        self.assertEqual(
            [
                record.glyph_name
                for record in math_plan.vertical_variant_records["parenleft"]
            ],
            ["parenleft"],
        )
        self.assertIn("parenleft", math_plan.extended_shapes)
        self.assertNotIn("arrowright", math_plan.extended_shapes)

    def test_assembly_references_and_connector_overlap_are_validated(self) -> None:
        missing = MathGlyphAssemblyData(
            italic_correction=0,
            parts=(
                MathAssemblyPartData(
                    glyph_name="missing.part",
                    start_connector_extent=0,
                    end_connector_extent=0,
                    start_scale=None,
                    end_scale=None,
                    extender=False,
                ),
            ),
        )
        missing_data = replace(
            self.math_data,
            min_connector_overlap=20,
            vertical_variant_glyphs=MappingProxyType({"parenleft": ()}),
            horizontal_variant_glyphs=MappingProxyType({}),
            vertical_assemblies=MappingProxyType({"parenleft": missing}),
            horizontal_assemblies=MappingProxyType({}),
        )
        with self.assertRaisesRegex(PlanError, "missing.part"):
            plan_font(
                self.assembled_math,
                self.math_config,
                math_data=missing_data,
            )

        no_overlap = replace(
            missing,
            parts=(
                MathAssemblyPartData(
                    glyph_name="parenleft.v1",
                    start_connector_extent=0,
                    end_connector_extent=0,
                    start_scale=None,
                    end_scale=None,
                    extender=True,
                ),
            ),
        )
        no_overlap_data = replace(
            missing_data,
            vertical_assemblies=MappingProxyType(
                {"parenleft": no_overlap}
            ),
        )
        with self.assertRaisesRegex(PlanError, "overlap itself"):
            plan_font(
                self.assembled_math,
                self.math_config,
                math_data=no_overlap_data,
            )

    def test_math_references_must_exist_in_real_glyphs(self) -> None:
        missing_ssty = replace(
            self.math_data,
            ssty=MappingProxyType({"minute": ("missing.st",)}),
        )
        with self.assertRaisesRegex(PlanError, "missing.st"):
            plan_font(
                self.assembled_math,
                self.math_config,
                math_data=missing_ssty,
            )

        missing_variant = replace(
            self.math_data,
            vertical_variant_glyphs=MappingProxyType(
                {"parenleft": ("missing.v1",)}
            ),
            horizontal_variant_glyphs=MappingProxyType({}),
            vertical_assemblies=MappingProxyType({}),
            horizontal_assemblies=MappingProxyType({}),
        )
        with self.assertRaisesRegex(PlanError, "missing.v1"):
            plan_font(
                self.assembled_math,
                self.math_config,
                math_data=missing_variant,
            )

    def test_empty_variant_glyph_sequence_still_plans_its_base(self) -> None:
        parameters = replace(
            self.assembled_math.glyph_parameters,
            monospace_width=900,
        )
        assembled = replace(
            self.assembled_math,
            glyph_parameters=parameters,
        )
        data = replace(
            self.math_data,
            ssty=MappingProxyType({}),
            min_connector_overlap=0,
            vertical_variant_glyphs=MappingProxyType({"A": ()}),
            horizontal_variant_glyphs=MappingProxyType({}),
            vertical_assemblies=MappingProxyType({}),
            horizontal_assemblies=MappingProxyType({}),
        )

        plan = plan_font(assembled, math_data=data)
        assert plan.math is not None

        self.assertEqual(plan.real_glyphs["A"].width, 600)
        self.assertEqual(plan.real_glyphs[".notdef"].width, 1050)
        self.assertEqual(
            [
                record.glyph_name
                for record in plan.math.vertical_variant_records["A"]
            ],
            ["A"],
        )
        self.assertIn("A", plan.math.extended_shapes)

    def test_cross_role_math_glyph_is_rejected_before_branch_planning(self) -> None:
        part = MathAssemblyPartData(
            glyph_name="A",
            start_connector_extent=0,
            end_connector_extent=0,
            start_scale=0,
            end_scale=0,
            extender=False,
        )
        data = replace(
            self.math_data,
            ssty=MappingProxyType({}),
            min_connector_overlap=0,
            vertical_variant_glyphs=MappingProxyType(
                {"A": (), "parenleft": ()}
            ),
            horizontal_variant_glyphs=MappingProxyType({}),
            vertical_assemblies=MappingProxyType(
                {
                    "parenleft": MathGlyphAssemblyData(
                        italic_correction=0,
                        parts=(part,),
                    )
                }
            ),
            horizontal_assemblies=MappingProxyType({}),
        )

        with self.assertRaisesRegex(PlanError, "multiple construction roles"):
            plan_font(self.assembled_math, math_data=data)

    def test_shared_vertical_parts_are_transformed_once_per_glyph(self) -> None:
        first_parts = (
            MathAssemblyPartData(
                "parenleft.v1", 0, 0.5, 0, None, False
            ),
            MathAssemblyPartData(
                "radical.v1", 0.5, 0.5, None, 2, True
            ),
        )
        second_parts = (
            replace(
                first_parts[0],
                start_connector_extent=0.25,
                extender=True,
            ),
            replace(
                first_parts[1],
                end_connector_extent=0.75,
                extender=False,
            ),
        )
        data = replace(
            self.math_data,
            ssty=MappingProxyType({}),
            min_connector_overlap=0,
            vertical_variant_glyphs=MappingProxyType(
                {"parenleft": (), "parenright": ()}
            ),
            horizontal_variant_glyphs=MappingProxyType({}),
            vertical_assemblies=MappingProxyType(
                {
                    "parenleft": MathGlyphAssemblyData(0, first_parts),
                    "parenright": MathGlyphAssemblyData(0, second_parts),
                }
            ),
            horizontal_assemblies=MappingProxyType({}),
        )

        with (
            patch(
                "skeletonfont.planner._transformed_strokes",
                wraps=_transformed_strokes,
            ) as transform,
            patch(
                "skeletonfont.planner._measure_glyph_axis",
                wraps=_measure_glyph_axis,
            ) as measure_axis,
        ):
            plan = plan_font(self.assembled_math, math_data=data)

        transformed_skeletons = [
            call.args[0] for call in transform.call_args_list
        ]
        for name in ("parenleft.v1", "radical.v1"):
            skeleton = self.assembled_math.real_glyphs[name].skeleton
            self.assertEqual(
                sum(item is skeleton for item in transformed_skeletons),
                1,
            )
        vertically_measured_names = [
            call.args[0].name
            for call in measure_axis.call_args_list
            if call.kwargs["axis"] == 1
        ]
        self.assertEqual(
            vertically_measured_names.count("parenleft.v1"),
            1,
        )
        self.assertEqual(
            vertically_measured_names.count("radical.v1"),
            1,
        )
        assert plan.math is not None
        first = plan.math.vertical_assemblies["parenleft"].parts[0]
        second = plan.math.vertical_assemblies["parenright"].parts[0]
        self.assertNotEqual(
            first.start_connector_length,
            second.start_connector_length,
        )
        self.assertNotEqual(first.extender, second.extender)

    def test_shared_vertical_part_accepts_subset_and_is_order_independent(self) -> None:
        shared = MathAssemblyPartData(
            "parenleft.v1", 0, 0, 0, 0, False
        )
        other = MathAssemblyPartData(
            "parenleft.v2", 0, 0, 0, 0, False
        )
        constructions = {
            "parenleft": MathGlyphAssemblyData(0, (shared, other)),
            "parenright": MathGlyphAssemblyData(
                0,
                (replace(shared, end_connector_extent=0.5),),
            ),
        }

        def planned_with(items):
            construction_items = tuple(items)
            data = replace(
                self.math_data,
                ssty=MappingProxyType({}),
                min_connector_overlap=0,
                vertical_variant_glyphs=MappingProxyType(
                    {base: () for base, _construction in construction_items}
                ),
                horizontal_variant_glyphs=MappingProxyType({}),
                vertical_assemblies=MappingProxyType(dict(construction_items)),
                horizontal_assemblies=MappingProxyType({}),
            )
            return plan_font(self.assembled_math, math_data=data)

        forward = planned_with(constructions.items())
        backward = planned_with(reversed(tuple(constructions.items())))

        self.assertEqual(
            forward.real_glyphs["parenleft.v1"],
            backward.real_glyphs["parenleft.v1"],
        )
        self.assertEqual(forward.real_glyphs["parenleft.v1"].width, 400)

    def test_shared_vertical_part_rejects_scale_or_layout_mismatch(self) -> None:
        shared = MathAssemblyPartData(
            "parenleft.v1", 0, 0, 0, None, False
        )
        common = MappingProxyType(
            {
                "parenleft": MathGlyphAssemblyData(0, (shared,)),
                "parenright": MathGlyphAssemblyData(
                    0,
                    (
                        shared,
                        MathAssemblyPartData(
                            "radical.v1", 0, 0, None, 2, False
                        ),
                    ),
                ),
            }
        )
        data = replace(
            self.math_data,
            ssty=MappingProxyType({}),
            min_connector_overlap=0,
            vertical_variant_glyphs=MappingProxyType(
                {"parenleft": (), "parenright": ()}
            ),
            horizontal_variant_glyphs=MappingProxyType({}),
            vertical_assemblies=common,
            horizontal_assemblies=MappingProxyType({}),
        )
        with self.assertRaisesRegex(
            PlanError,
            "incompatible construction layouts",
        ) as context:
            plan_font(self.assembled_math, math_data=data)
        self.assertIn("'parenleft':", str(context.exception))
        self.assertIn("'parenright':", str(context.exception))

        mismatched = replace(shared, start_scale=1)
        scale_data = replace(
            data,
            vertical_assemblies=MappingProxyType(
                {
                    "parenleft": MathGlyphAssemblyData(0, (shared,)),
                    "parenright": MathGlyphAssemblyData(0, (mismatched,)),
                }
            ),
        )
        with self.assertRaisesRegex(
            PlanError,
            "inconsistent authored",
        ) as context:
            plan_font(self.assembled_math, math_data=scale_data)
        self.assertIn("'parenleft':", str(context.exception))
        self.assertIn("'parenright':", str(context.exception))

    def test_shared_horizontal_part_allows_distinct_connector_data(self) -> None:
        shared = MathAssemblyPartData("equal", 0, 0, 0, 0, False)
        changed = replace(
            shared,
            start_connector_extent=0.5,
            extender=True,
        )
        data = replace(
            self.math_data,
            ssty=MappingProxyType({}),
            min_connector_overlap=0,
            vertical_variant_glyphs=MappingProxyType({}),
            horizontal_variant_glyphs=MappingProxyType(
                {"arrowleft": (), "arrowright": ()}
            ),
            vertical_assemblies=MappingProxyType({}),
            horizontal_assemblies=MappingProxyType(
                {
                    "arrowleft": MathGlyphAssemblyData(0, (shared,)),
                    "arrowright": MathGlyphAssemblyData(0, (changed,)),
                }
            ),
        )

        plan = plan_font(self.assembled_math, math_data=data)
        assert plan.math is not None
        left = plan.math.horizontal_assemblies["arrowleft"].parts[0]
        right = plan.math.horizontal_assemblies["arrowright"].parts[0]

        self.assertNotEqual(
            left.start_connector_length,
            right.start_connector_length,
        )
        self.assertNotEqual(left.extender, right.extender)

    def test_transform_cleans_consecutive_points_in_font_units(self) -> None:
        parameters = self.assembled_math.glyph_parameters
        stroke = StrokeRecord(
            centerline=(
                (0.0, 0.0),
                (0.0, 0.0),
                (1.0, 0.0),
                (1.0 + 1e-12, 0.0),
                (2.0, 0.0),
            ),
            thickness_scale=1.0,
            start_cap="round",
            end_cap="round",
            filled=False,
        )

        planned = _transform_stroke(
            stroke,
            grid=parameters.grid,
            radius=parameters.radius,
            grid_x_offset=0.0,
            grid_y_offset=0.0,
            font_x_shift=0.0,
            font_y_shift=0.0,
        )

        self.assertEqual(
            planned.centerline,
            (
                (0.0, 0.0),
                (parameters.grid, 0.0),
                (2 * parameters.grid, 0.0),
            ),
        )

    def test_transform_rejects_empty_centerline_before_geometry(self) -> None:
        stroke = StrokeRecord(
            centerline=(),
            thickness_scale=1.0,
            start_cap="round",
            end_cap="round",
            filled=False,
        )

        with self.assertRaisesRegex(PlanError, "empty centerline"):
            _transform_stroke(
                stroke,
                grid=self.assembled_math.glyph_parameters.grid,
                radius=self.assembled_math.glyph_parameters.radius,
                grid_x_offset=0.0,
                grid_y_offset=0.0,
                font_x_shift=0.0,
                font_y_shift=0.0,
            )

    def test_transform_marks_closed_centerline_and_removes_repeated_endpoint(self) -> None:
        stroke = StrokeRecord(
            centerline=((0, 0), (2, 0), (2, 2), (0, 2), (0, 0)),
            thickness_scale=1.0,
            start_cap="round",
            end_cap="round",
            filled=False,
        )

        planned = _transform_stroke(
            stroke,
            grid=self.assembled_math.glyph_parameters.grid,
            radius=self.assembled_math.glyph_parameters.radius,
            grid_x_offset=0.0,
            grid_y_offset=0.0,
            font_x_shift=0.0,
            font_y_shift=0.0,
        )

        self.assertTrue(planned.closed)
        grid = self.assembled_math.glyph_parameters.grid
        self.assertEqual(
            planned.centerline,
            ((0.0, 0.0), (2 * grid, 0.0), (2 * grid, 2 * grid), (0.0, 2 * grid)),
        )

    def test_transform_keeps_repeated_endpoint_when_flat_cap_makes_path_open(self) -> None:
        stroke = StrokeRecord(
            centerline=((0, 0), (2, 0), (2, 2), (0, 2), (0, 0)),
            thickness_scale=1.0,
            start_cap="flat",
            end_cap="round",
            filled=False,
        )

        planned = _transform_stroke(
            stroke,
            grid=self.assembled_math.glyph_parameters.grid,
            radius=self.assembled_math.glyph_parameters.radius,
            grid_x_offset=0.0,
            grid_y_offset=0.0,
            font_x_shift=0.0,
            font_y_shift=0.0,
        )

        self.assertFalse(planned.closed)
        self.assertEqual(planned.centerline[0], planned.centerline[-1])

    def test_transform_rejects_filled_open_centerline(self) -> None:
        stroke = StrokeRecord(
            centerline=((0, 0), (2, 0)),
            thickness_scale=1.0,
            start_cap="round",
            end_cap="round",
            filled=True,
        )

        with self.assertRaisesRegex(PlanError, "filled can only be used"):
            _transform_stroke(
                stroke,
                grid=self.assembled_math.glyph_parameters.grid,
                radius=self.assembled_math.glyph_parameters.radius,
                grid_x_offset=0.0,
                grid_y_offset=0.0,
                font_x_shift=0.0,
                font_y_shift=0.0,
            )

    def test_transform_rejects_closed_centerline_with_fewer_than_three_points(self) -> None:
        stroke = StrokeRecord(
            centerline=((0, 0), (2, 0), (0, 0)),
            thickness_scale=1.0,
            start_cap="round",
            end_cap="round",
            filled=False,
        )

        with self.assertRaisesRegex(PlanError, "at least three distinct points"):
            _transform_stroke(
                stroke,
                grid=self.assembled_math.glyph_parameters.grid,
                radius=self.assembled_math.glyph_parameters.radius,
                grid_x_offset=0.0,
                grid_y_offset=0.0,
                font_x_shift=0.0,
                font_y_shift=0.0,
            )

    def test_proportional_strokes_and_width_are_resolved(self) -> None:
        glyph = self.math_plan.real_glyphs["A"]

        self.assertEqual(glyph.width, 600)
        self.assertEqual(glyph.strokes[0].radius, 25)
        self.assertEqual(
            glyph.strokes[0].centerline,
            (
                (100.0, 25.0),
                (100.0, 325.0),
                (300.0, 625.0),
                (500.0, 325.0),
                (500.0, 25.0),
            ),
        )

    def test_empty_glyph_length_resolves_width(self) -> None:
        space = self.math_plan.real_glyphs["space"]

        self.assertEqual(space.width, 550)
        self.assertEqual(space.strokes, ())

    def test_glyph_spacing_override_is_applied_once(self) -> None:
        parenleft = self.math_plan.real_glyphs["parenleft"]

        self.assertEqual(parenleft.width, 450)

    def test_scaled_edge_thickness_affects_metrics(self) -> None:
        minute = self.math_plan.real_glyphs["minute.st"]

        self.assertEqual(minute.width, 420)
        self.assertEqual(minute.strokes[0].radius, 35)
        self.assertEqual(
            minute.strokes[0].centerline,
            ((310.0, 525.0), (110.0, 125.0)),
        )

        unscaled_parameters = replace(
            self.assembled_math.glyph_parameters,
            use_scaled_edge_thickness=False,
        )
        unscaled_assembled = replace(
            self.assembled_math,
            glyph_parameters=unscaled_parameters,
        )
        unscaled = plan_font(
            unscaled_assembled,
            self.math_config,
            math_data=self.math_data,
        ).real_glyphs["minute.st"]
        self.assertEqual(unscaled.width, 400)
        self.assertEqual(unscaled.strokes[0].radius, 35)

    def test_generated_glyph_records_only_its_copy_source(self) -> None:
        generated = next(
            glyph
            for glyph in self.math_plan.generated_glyphs
            if glyph.target_name == "u1D434"
        )

        self.assertEqual(generated.source_name, "A")
        self.assertEqual(generated.target_codepoint, 0x1D434)
        self.assertFalse(hasattr(generated, "strokes"))

    def test_monospace_uses_fixed_width_and_source_x_offset(self) -> None:
        mono_plan = plan_font(assembled_font("mono"))
        a = mono_plan.real_glyphs["A"]
        space = mono_plan.real_glyphs["space"]

        self.assertEqual(a.width, 600)
        self.assertEqual(space.width, 600)
        self.assertEqual(a.strokes[0].centerline[0], (100.0, 25.0))
        self.assertEqual(a.strokes[0].centerline[-1], (500.0, 25.0))

    def test_monospace_design_origin_tracks_core_width_center(self) -> None:
        assembled = assembled_font("mono")
        narrow_assembled = replace(
            assembled,
            glyph_parameters=replace(
                assembled.glyph_parameters,
                monospace_width=500,
            ),
        )

        a = plan_font(narrow_assembled).real_glyphs["A"]

        self.assertEqual(a.width, 500)
        self.assertEqual(a.strokes[0].centerline[0], (50.0, 25.0))
        self.assertEqual(a.strokes[0].centerline[-1], (450.0, 25.0))

    def test_monospace_center_does_not_depend_on_radius(self) -> None:
        assembled = assembled_font("mono")
        thick_assembled = replace(
            assembled,
            glyph_parameters=replace(
                assembled.glyph_parameters,
                radius=50,
            ),
        )

        a = plan_font(thick_assembled).real_glyphs["A"]

        self.assertEqual(a.strokes[0].centerline[0][0], 100.0)
        self.assertEqual(a.strokes[0].centerline[-1][0], 500.0)

    def test_meta_y_shift_is_applied_in_font_units(self) -> None:
        shifted_parameters = replace(
            self.assembled_math.glyph_parameters,
            y_shift=30,
        )
        shifted_assembled = replace(
            self.assembled_math,
            glyph_parameters=shifted_parameters,
        )

        shifted = plan_font(
            shifted_assembled,
            self.math_config,
            math_data=self.math_data,
        ).real_glyphs["A"]

        self.assertEqual(
            shifted.strokes[0].centerline[0],
            (100.0, 55.0),
        )

    def test_monospace_meta_spacing_preserves_equal_width(self) -> None:
        assembled = assembled_font("mono")
        spaced_parameters = replace(
            assembled.glyph_parameters,
            left_spacing=20,
            right_spacing=30,
        )
        spaced_assembled = replace(
            assembled,
            glyph_parameters=spaced_parameters,
        )

        plan = plan_font(spaced_assembled)
        a = plan.real_glyphs["A"]
        space = plan.real_glyphs["space"]

        self.assertEqual(a.width, 650)
        self.assertEqual(space.width, 650)
        self.assertEqual(plan.real_glyphs[".notdef"].width, 650)
        self.assertEqual(a.strokes[0].centerline[0], (120.0, 25.0))

    def test_preloaded_kerning_is_retained_by_the_plan(self) -> None:
        assembled = assembled_font("fraktur")
        kerning = load_kerning_data(PROJECT_DIRECTORY, "fraktur.json")
        plan = plan_font(assembled, kerning=kerning)
        self.assertIs(plan.kerning, kerning)

    def test_unused_config_name_is_rejected(self) -> None:
        config = dict(self.math_config)
        config["does.not.exist"] = GlyphSpacingOverride(1, 0)

        with self.assertRaisesRegex(PlanError, "does.not.exist"):
            plan_font(
                self.assembled_math,
                config,
                math_data=self.math_data,
            )


if __name__ == "__main__":
    unittest.main()
