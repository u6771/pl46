from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import cast
from unittest.mock import patch

from skeletonfont.assembler import GlyphCatalog, assemble_font
from skeletonfont.errors import PlanError, ProjectDataError
from skeletonfont.loader import (
    load_accent_glyphs,
    load_font_meta,
    load_glyph_config,
    load_kerning_data,
    load_math_table_data,
    load_ssty_data,
    parse_glyph_config,
)
from skeletonfont.model import (
    GlyphAdjustment,
    GlyphAdjustmentGroup,
    GlyphAdjustmentSelector,
    GlyphSpacingAdjustment,
    MathAssemblyPartData,
    MathGlyphAssemblyData,
    MathGlyphKernData,
    MathKernTableData,
    SstyData,
    SstyGenerator,
    StrokeRecord,
    UnicodeDomain,
)
from skeletonfont.planner import (
    _inherited_top_accent_attachments,
    _measure_glyph_axis,
    _plan_variant_glyph,
    _transform_stroke,
    _transformed_strokes,
    _with_ssty_top_accent_attachments,
    plan_font,
)


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


def assembled_font(meta_name: str):
    meta = load_font_meta(PROJECT_DIRECTORY, meta_name)
    return assemble_font(meta, GlyphCatalog(PROJECT_DIRECTORY))


def adjustment(
    left: float | None = None,
    right: float | None = None,
) -> GlyphAdjustment:
    return GlyphAdjustment(GlyphSpacingAdjustment(left, right))


def selector(value: str) -> GlyphAdjustmentSelector:
    if "@" not in value:
        return GlyphAdjustmentSelector(value, None)
    base_name, group = value.split("@")
    assert group in ("variant_glyphs", "parts", "variants")
    return GlyphAdjustmentSelector(
        base_name,
        cast(GlyphAdjustmentGroup, group),
    )


def adjustment_config(
    entries: dict[str, GlyphAdjustment],
) -> dict[GlyphAdjustmentSelector, GlyphAdjustment]:
    return {selector(name): value for name, value in entries.items()}


def glyph_kern(value: int = -40) -> MathGlyphKernData:
    return MathGlyphKernData(
        bottom_right=MathKernTableData((), (value,))
    )


class GlyphConfigLoaderTests(unittest.TestCase):
    def test_math_adjustments_are_typed_and_read_only(self) -> None:
        config = load_glyph_config(PROJECT_DIRECTORY, "math.json")

        self.assertEqual(len(config), 35)
        self.assertEqual(
            config[selector("parenleft@variants")],
            adjustment(left=50.0),
        )
        self.assertEqual(
            config[selector("bar@variants")],
            adjustment(left=50.0, right=50.0),
        )
        self.assertEqual(
            config[selector("uni2A2F")],
            adjustment(left=100.0, right=100.0),
        )
        with self.assertRaises(TypeError):
            config[selector("A")] = GlyphAdjustment()  # type: ignore[index]

    def test_unknown_glyph_config_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "width"):
            parse_glyph_config(
                {"A": {"width": 500}},
                source_path=Path("config.json"),
            )

    def test_group_selectors_are_parsed_without_resolving_math_data(self) -> None:
        config = parse_glyph_config(
            {
                "parenleft@variant_glyphs": {"left_adjustment": 10},
                "parenleft@parts": {"right_adjustment": 20},
                "parenleft@variants": {
                    "left_adjustment": 30,
                    "right_adjustment": 40,
                },
                "uni23B4@parts": {"left_adjustment": 50},
            },
            source_path=Path("config.json"),
        )

        self.assertEqual(
            config[selector("parenleft@parts")],
            adjustment(right=20),
        )
        self.assertEqual(
            config[selector("uni23B4@parts")],
            adjustment(left=50),
        )

    def test_group_selector_syntax_is_validated(self) -> None:
        for selector in (
            "@parts",
            "parenleft@",
            "parenleft@unknown",
            "parenleft@parts@variants",
        ):
            with self.subTest(selector=selector):
                with self.assertRaises(ProjectDataError):
                    parse_glyph_config(
                        {selector: {"left_adjustment": 10}},
                        source_path=Path("config.json"),
                    )

    def test_legacy_spacing_adjustment_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "left_spacing"):
            parse_glyph_config(
                {"A": {"left_spacing": 10}},
                source_path=Path("config.json"),
            )

    def test_empty_glyph_config_entry_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "no adjustment"):
            parse_glyph_config(
                {"A": {}},
                source_path=Path("config.json"),
            )


class TopAccentAttachmentHelperTests(unittest.TestCase):
    def test_ssty_expansion_uses_authored_coordinates_without_mutation(
        self,
    ) -> None:
        authored = {"A": 1.0, "A.st": 1.25}

        expanded = _with_ssty_top_accent_attachments(
            authored,
            {
                "A.st": "A",
                "A.sts": "A",
                "B.st": "B",
            },
        )

        self.assertEqual(authored, {"A": 1.0, "A.st": 1.25})
        self.assertEqual(
            dict(expanded),
            {"A": 1.0, "A.st": 1.25, "A.sts": 1.0},
        )
        with self.assertRaises(TypeError):
            expanded["new"] = 0.0  # type: ignore[index]


class FontPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.meta = load_font_meta(PROJECT_DIRECTORY, "math")
        cls.assembled_math = assemble_font(
            cls.meta,
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        cls.math_table = load_glyph_config(
            PROJECT_DIRECTORY,
            "math.json",
        )
        assert cls.meta.math_table is not None
        cls.math_data = load_math_table_data(
            PROJECT_DIRECTORY, cls.meta.math_table
        )
        assert cls.meta.ssty_file is not None
        cls.ssty_data = load_ssty_data(
            PROJECT_DIRECTORY, cls.meta.ssty_file
        )
        assert cls.meta.accent_file is not None
        cls.accent_glyphs = load_accent_glyphs(
            PROJECT_DIRECTORY,
            cls.meta.accent_file,
        )
        cls.math_plan = plan_font(
            cls.assembled_math,
            cls.math_table,
            math_table_data=cls.math_data,
            ssty_data=cls.ssty_data,
            accent_glyphs=cls.accent_glyphs,
        )

    def test_math_font_plan_has_resolved_glyphs_and_output(self) -> None:
        plan = self.math_plan

        self.assertEqual(plan.output_stem, "PL46-Math")
        self.assertEqual(plan.point_radius_scale, 1.6)
        self.assertEqual(
            set(plan.glyphs),
            set(self.assembled_math.glyphs),
        )
        self.assertEqual(
            plan.glyph_aliases,
            self.assembled_math.glyph_aliases,
        )
        self.assertEqual(plan.glyphs[".notdef"].width, 600)
        self.assertTrue(plan.glyphs[".notdef"].strokes)
        with self.assertRaises(TypeError):
            plan.glyphs["new"] = plan.glyphs["A"]  # type: ignore[index]

    def test_accent_attachment_inheritance_does_not_mutate_input(
        self,
    ) -> None:
        source_attachments = {"A": 400}

        inherited = _inherited_top_accent_attachments(
            source_attachments,
            {"A.st": "A", "B.st": "B"},
        )

        self.assertEqual(source_attachments, {"A": 400})
        self.assertEqual(inherited, {"A.st": 400})

    def test_math_plan_resolves_ssty_and_variant_advances(self) -> None:
        math_plan = self.math_plan.math_table
        assert math_plan is not None

        assert self.math_plan.ssty_feature is not None
        self.assertIn(
            "sub minute by minute.st;",
            self.math_plan.ssty_feature,
        )
        self.assertIn(
            "sub A by A.st;",
            self.math_plan.ssty_feature,
        )
        self.assertIn(
            "sub A.italic by A.italic.st;",
            self.math_plan.ssty_feature,
        )
        self.assertEqual(len(math_plan.vertical_variant_records), 46)
        self.assertEqual(len(math_plan.horizontal_variant_records), 14)
        self.assertIn("parenleft", math_plan.extended_shapes)
        self.assertEqual(
            dict(math_plan.italic_corrections),
            dict(self.math_data.italic_corrections),
        )
        self.assertEqual(math_plan.top_accent_attachments["f.italic"], 400)
        self.assertEqual(math_plan.top_accent_attachments["j"], 500)
        self.assertEqual(math_plan.top_accent_attachments["j.italic"], 500)
        self.assertEqual(math_plan.top_accent_attachments["t"], 200)
        self.assertEqual(math_plan.top_accent_attachments["t.italic"], 200)
        self.assertEqual(math_plan.top_accent_attachments["A.script"], 500)
        self.assertEqual(math_plan.top_accent_attachments["J.st"], 505)
        self.assertEqual(
            math_plan.top_accent_attachments["J.italic.st"],
            505,
        )
        for alias in self.assembled_math.glyph_aliases:
            source_attachment = math_plan.top_accent_attachments.get(
                alias.source_name
            )
            if source_attachment is not None:
                self.assertEqual(
                    math_plan.top_accent_attachments[alias.target_name],
                    source_attachment,
                )
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
        expected_advances = (850, 1050, 1250, 1450, 1670, 1870, 2070, 2270)
        vertical_bases = (
            "uni27E8",
            "uni27E9",
            "uni27EA",
            "uni27EB",
            "uni2308",
            "uni2309",
            "uni230A",
            "uni230B",
            "uni27E6",
            "uni27E7",
        )
        for base in vertical_bases:
            with self.subTest(base=base):
                self.assertEqual(
                    [
                        (record.glyph_name, record.full_advance)
                        for record in math_plan.vertical_variant_records[base]
                    ],
                    [
                        (base if index == 0 else f"{base}.v{index}", advance)
                        for index, advance in enumerate(expected_advances)
                    ],
                )
        expected_glyphs_by_base = {
            "uni2308": ("uni2308.bt", "uni23A2", "uni23A1"),
            "uni2309": ("uni2309.bt", "uni23A5", "uni23A4"),
            "uni230A": ("uni23A3", "uni23A2", "uni230A.tp"),
            "uni230B": ("uni23A6", "uni23A5", "uni230B.tp"),
            "uni27E6": ("uni27E6.bt", "uni27E6.ex", "uni27E6.tp"),
            "uni27E7": ("uni27E7.bt", "uni27E7.ex", "uni27E7.tp"),
        }
        expected_metrics = (
            (0, 200, 835, False),
            (400, 400, 400, True),
            (200, 0, 835, False),
        )
        for base in vertical_bases[4:]:
            with self.subTest(assembly_base=base):
                self.assertEqual(
                    [
                        (
                            part.glyph_name,
                            part.start_connector_length,
                            part.end_connector_length,
                            part.full_advance,
                            part.extender,
                        )
                        for part in math_plan.vertical_assemblies[base].parts
                    ],
                    [
                        (glyph_name, *metrics)
                        for glyph_name, metrics in zip(
                            expected_glyphs_by_base[base],
                            expected_metrics,
                            strict=True,
                        )
                    ],
                )

    def test_explicit_ssty_does_not_require_a_math_table(self) -> None:
        plan = plan_font(
            self.assembled_math,
            ssty_data=self.ssty_data,
        )

        self.assertIsNone(plan.math_table)
        assert plan.ssty_feature is not None
        self.assertIn("sub minute by minute.st;", plan.ssty_feature)
        self.assertIn("sub A by A.st;", plan.ssty_feature)

    def test_automatic_ssty_without_explicit_data_or_math(self) -> None:
        plan = plan_font(self.assembled_math)

        self.assertIsNone(plan.math_table)
        assert plan.ssty_feature is not None
        self.assertIn("sub A by A.st;", plan.ssty_feature)
        self.assertNotIn("sub minute by minute.st;", plan.ssty_feature)

    def test_automatic_and_explicit_ssty_cannot_share_a_base(self) -> None:
        conflicting = SstyData(
            source_path=Path("ssty.json"),
            substitutions=MappingProxyType({"A": ("A.st",)}),
        )

        with self.assertRaisesRegex(
            PlanError,
            "Automatic and explicit ssty",
        ):
            plan_font(self.assembled_math, ssty_data=conflicting)

    def test_math_italics_correction_rejects_unknown_glyphs(self) -> None:
        data = replace(
            self.math_data,
            italic_corrections=MappingProxyType({"missing": 10}),
        )

        with self.assertRaisesRegex(PlanError, "unknown glyphs"):
            plan_font(self.assembled_math, math_table_data=data)

    def test_math_kerns_allow_supported_glyph_roles_and_inherit(self) -> None:
        kern = glyph_kern()
        data = replace(
            self.math_data,
            kerns=MappingProxyType(
                {
                    "A.script": kern,
                    "parenleft.v1": kern,
                    "uni23B4.h1": kern,
                    "j": kern,
                }
            ),
        )

        math_plan = plan_font(self.assembled_math, math_table_data=data).math_table
        assert math_plan is not None
        self.assertEqual(math_plan.kerns["A.script"], kern)
        self.assertEqual(math_plan.kerns["parenleft.v1"], kern)
        self.assertEqual(math_plan.kerns["uni23B4.h1"], kern)
        self.assertEqual(math_plan.kerns["j"], kern)
        self.assertEqual(math_plan.kerns["j.italic"], kern)

    def test_math_kerns_reject_unsupported_or_alias_names(self) -> None:
        invalid = (
            ("missing", frozenset(), "not planned as an assembled glyph"),
            ("j.italic", frozenset(), "not planned as an assembled glyph"),
            ("tildecomb", self.accent_glyphs, "unsupported planning role"),
            ("uni239C", frozenset(), "unsupported planning role"),
        )
        for name, accent_glyphs, message in invalid:
            with self.subTest(name=name):
                data = replace(
                    self.math_data,
                    kerns=MappingProxyType({name: glyph_kern()}),
                )
                with self.assertRaisesRegex(PlanError, message):
                    plan_font(
                        self.assembled_math,
                        math_table_data=data,
                        accent_glyphs=accent_glyphs,
                    )

    def test_top_accent_attachment_uses_effective_glyph_metrics(self) -> None:
        data = replace(
            self.math_data,
            accent_attachments=MappingProxyType({"j": 1.0}),
        )
        config = dict(self.math_table)
        config[selector("j")] = adjustment(left=20)

        with patch(
            "skeletonfont.planning.glyphs._measure_glyph_axis",
            wraps=_measure_glyph_axis,
        ) as measure_axis:
            math_plan = plan_font(
                self.assembled_math,
                config,
                math_table_data=data,
            ).math_table
        assert math_plan is not None
        self.assertEqual(math_plan.top_accent_attachments["j"], 420)
        self.assertEqual(math_plan.top_accent_attachments["j.italic"], 420)
        self.assertEqual(
            sum(
                call.args[0].name == "j"
                for call in measure_axis.call_args_list
            ),
            1,
        )

    def test_monospace_top_accent_attachment_uses_design_origin(self) -> None:
        assembled = replace(
            self.assembled_math,
            glyph_parameters=replace(
                self.assembled_math.glyph_parameters,
                monospace_width=600,
            ),
        )
        data = replace(
            self.math_data,
            accent_attachments=MappingProxyType({"j": 1.0}),
        )

        with patch(
            "skeletonfont.planning.glyphs._measure_glyph_axis",
            wraps=_measure_glyph_axis,
        ) as measure_axis:
            math_plan = plan_font(assembled, math_table_data=data).math_table
        assert math_plan is not None
        self.assertEqual(math_plan.top_accent_attachments["j"], 275)
        self.assertEqual(math_plan.top_accent_attachments["j.italic"], 275)
        self.assertFalse(
            any(
                call.args[0].name == "j"
                for call in measure_axis.call_args_list
            )
        )

    def test_top_accent_attachment_allows_both_variant_roles(self) -> None:
        data = replace(
            self.math_data,
            accent_attachments=MappingProxyType(
                {"parenleft.v1": 1.0, "uni23B4.h1": 1.0}
            ),
        )

        with patch(
            "skeletonfont.planning.glyphs._measure_glyph_axis",
            wraps=_measure_glyph_axis,
        ) as measure_axis:
            math_plan = plan_font(self.assembled_math, math_table_data=data).math_table
        assert math_plan is not None
        self.assertEqual(
            set(math_plan.top_accent_attachments),
            {"parenleft.v1", "uni23B4.h1"},
        )
        self.assertEqual(
            sum(
                call.args[0].name == "parenleft.v1"
                for call in measure_axis.call_args_list
            ),
            2,
        )
        self.assertEqual(
            sum(
                call.args[0].name == "uni23B4.h1"
                for call in measure_axis.call_args_list
            ),
            1,
        )

    def test_top_accent_attachment_rejects_unsupported_roles(self) -> None:
        invalid = (
            ("missing", frozenset(), "not planned as an assembled glyph"),
            ("j.italic", frozenset(), "not planned as an assembled glyph"),
            ("tildecomb", self.accent_glyphs, "unsupported planning role"),
            ("uni239C", frozenset(), "unsupported planning role"),
        )
        for name, accent_glyphs, message in invalid:
            with self.subTest(name=name):
                data = replace(
                    self.math_data,
                    accent_attachments=MappingProxyType({name: 1.0}),
                )
                with self.assertRaisesRegex(PlanError, message):
                    plan_font(
                        self.assembled_math,
                        math_table_data=data,
                        accent_glyphs=accent_glyphs,
                    )

    def test_accent_glyphs_have_zero_advance_and_authored_origin(self) -> None:
        tilde = self.math_plan.glyphs["tildecomb"]

        self.assertEqual(tilde.width, 0)
        self.assertEqual(
            tilde.strokes[0].centerline,
            (
                (-100.0, 625.0),
                (-100.0, 725.0),
                (100.0, 625.0),
                (100.0, 725.0),
            ),
        )
        assert self.math_plan.math_table is not None
        expected_advances = (250, 450, 650, 850, 1050, 1250, 1450, 1650)
        for base in ("tildecomb", "circumflexcmb", "caroncmb"):
            with self.subTest(base=base):
                self.assertEqual(self.math_plan.glyphs[base].width, 0)
                self.assertEqual(
                    [
                        (record.glyph_name, record.full_advance)
                        for record in self.math_plan.math_table.horizontal_variant_records[
                            base
                        ]
                    ],
                    [
                        (base if index == 0 else f"{base}.h{index}", advance)
                        for index, advance in enumerate(expected_advances)
                    ],
                )

    def test_horizontal_accent_base_is_measured_without_replanning(self) -> None:
        with patch(
            "skeletonfont.planning.glyphs._measure_glyph_axis",
            wraps=_measure_glyph_axis,
        ) as measure_axis:
            plan = plan_font(
                self.assembled_math,
                math_table_data=self.math_data,
                accent_glyphs=self.accent_glyphs,
            )

        self.assertEqual(plan.glyphs["tildecomb"].width, 0)
        self.assertEqual(
            sum(
                call.args[0].name == "tildecomb"
                for call in measure_axis.call_args_list
            ),
            1,
        )

    def test_accent_glyphs_reject_spacing_adjustments(self) -> None:
        with self.assertRaisesRegex(PlanError, "accent glyph"):
            plan_font(
                self.assembled_math,
                adjustment_config({"tildecomb": adjustment(left=10)}),
                math_table_data=self.math_data,
                accent_glyphs=self.accent_glyphs,
            )

        with self.assertRaisesRegex(PlanError, "includes combining accent"):
            plan_font(
                self.assembled_math,
                adjustment_config(
                    {"tildecomb@variant_glyphs": adjustment(left=10)}
                ),
                math_table_data=self.math_data,
                accent_glyphs=self.accent_glyphs,
            )

        adjusted = plan_font(
            self.assembled_math,
            adjustment_config({"tildecomb.h1": adjustment(left=10)}),
            math_table_data=self.math_data,
            accent_glyphs=self.accent_glyphs,
        )
        self.assertEqual(
            adjusted.glyphs["tildecomb.h1"].width,
            self.math_plan.glyphs["tildecomb.h1"].width + 10,
        )

    def test_accent_glyphs_reject_unknown_and_unsupported_roles(self) -> None:
        with self.assertRaisesRegex(PlanError, "unknown assembled glyphs"):
            plan_font(
                self.assembled_math,
                math_table_data=self.math_data,
                accent_glyphs=frozenset({"missing"}),
            )

        overlapping = replace(
            self.math_data,
            vertical_variant_glyphs=MappingProxyType(
                {
                    **self.math_data.vertical_variant_glyphs,
                    "circumflexcmb": (),
                }
            ),
        )
        with self.assertRaisesRegex(PlanError, "multiple planning roles"):
            plan_font(
                self.assembled_math,
                math_table_data=overlapping,
                accent_glyphs=self.accent_glyphs,
            )

        with self.assertRaisesRegex(PlanError, "multiple planning roles"):
            plan_font(
                self.assembled_math,
                math_table_data=self.math_data,
                accent_glyphs=(
                    self.accent_glyphs | frozenset({"tildecomb.h1"})
                ),
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

        plan = plan_font(assembled, math_table_data=self.math_data)

        self.assertEqual(plan.glyphs["parenleft"].width, 400)
        self.assertEqual(plan.glyphs["parenleft.v4"].width, 620)
        self.assertEqual(
            plan.glyphs["parenleft"].strokes[0].centerline[0][0],
            300,
        )
        self.assertEqual(
            plan.glyphs["parenleft.v4"].strokes[0].centerline[0][0],
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
            math_table_data=math_data,
        )
        assert plan.math_table is not None

        self.assertEqual(
            [
                (record.glyph_name, record.full_advance)
                for record in plan.math_table.horizontal_variant_records["equal"]
            ],
            [("equal", 650), ("arrowleft", 850)],
        )
        self.assertEqual(plan.math_table.extended_shapes, set())

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
            math_table_data=math_data,
        )
        math_plan = plan.math_table
        assert math_plan is not None

        paren_part = plan.glyphs["parenleft.v1"]
        radical_part = plan.glyphs["radical.v1"]
        self.assertEqual(paren_part.width, 900)
        self.assertEqual(radical_part.width, 900)
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

        equal_part = plan.glyphs["equal"]
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
                math_table_data=missing_data,
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
                math_table_data=no_overlap_data,
            )

    def test_math_references_must_exist_in_assembled_glyphs(self) -> None:
        missing_ssty = SstyData(
            source_path=Path("ssty.json"),
            substitutions=MappingProxyType(
                {"minute": ("missing.st",)}
            ),
        )
        with self.assertRaisesRegex(PlanError, "missing.st"):
            plan_font(
                self.assembled_math,
                self.math_table,
                math_table_data=self.math_data,
                ssty_data=missing_ssty,
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
                math_table_data=missing_variant,
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
            min_connector_overlap=0,
            vertical_variant_glyphs=MappingProxyType({"A": ()}),
            horizontal_variant_glyphs=MappingProxyType({}),
            vertical_assemblies=MappingProxyType({}),
            horizontal_assemblies=MappingProxyType({}),
        )

        plan = plan_font(assembled, math_table_data=data)
        assert plan.math_table is not None

        self.assertEqual(plan.glyphs["A"].width, 600)
        self.assertEqual(plan.glyphs[".notdef"].width, 1050)
        self.assertEqual(
            [
                record.glyph_name
                for record in plan.math_table.vertical_variant_records["A"]
            ],
            ["A"],
        )
        self.assertIn("A", plan.math_table.extended_shapes)

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

        with self.assertRaisesRegex(PlanError, "multiple planning roles"):
            plan_font(self.assembled_math, math_table_data=data)

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
                "skeletonfont.planning.assemblies._transformed_strokes",
                wraps=_transformed_strokes,
            ) as transform,
            patch(
                "skeletonfont.planning.assemblies._measure_glyph_axis",
                wraps=_measure_glyph_axis,
            ) as measure_axis,
        ):
            plan = plan_font(self.assembled_math, math_table_data=data)

        transformed_skeletons = [
            call.args[0] for call in transform.call_args_list
        ]
        for name in ("parenleft.v1", "radical.v1"):
            skeleton = self.assembled_math.glyphs[name].skeleton
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
        assert plan.math_table is not None
        first = plan.math_table.vertical_assemblies["parenleft"].parts[0]
        second = plan.math_table.vertical_assemblies["parenright"].parts[0]
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
                min_connector_overlap=0,
                vertical_variant_glyphs=MappingProxyType(
                    {base: () for base, _construction in construction_items}
                ),
                horizontal_variant_glyphs=MappingProxyType({}),
                vertical_assemblies=MappingProxyType(dict(construction_items)),
                horizontal_assemblies=MappingProxyType({}),
            )
            return plan_font(self.assembled_math, math_table_data=data)

        forward = planned_with(constructions.items())
        backward = planned_with(reversed(tuple(constructions.items())))

        self.assertEqual(
            forward.glyphs["parenleft.v1"],
            backward.glyphs["parenleft.v1"],
        )
        self.assertEqual(forward.glyphs["parenleft.v1"].width, 400)

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
            plan_font(self.assembled_math, math_table_data=data)
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
            plan_font(self.assembled_math, math_table_data=scale_data)
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

        plan = plan_font(self.assembled_math, math_table_data=data)
        assert plan.math_table is not None
        left = plan.math_table.horizontal_assemblies["arrowleft"].parts[0]
        right = plan.math_table.horizontal_assemblies["arrowright"].parts[0]

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
        glyph = self.math_plan.glyphs["A"]

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
        space = self.math_plan.glyphs["space"]

        self.assertEqual(space.width, 550)
        self.assertEqual(space.strokes, ())

    def test_empty_glyph_can_receive_a_top_accent_attachment(self) -> None:
        data = replace(
            self.math_data,
            accent_attachments=MappingProxyType({"space": 1.0}),
        )

        plan = plan_font(self.assembled_math, math_table_data=data)

        assert plan.math_table is not None
        self.assertEqual(plan.math_table.top_accent_attachments["space"], 175)

    def test_resolved_opentype_values_must_fit_storage_ranges(self) -> None:
        oversized_font = replace(
            self.assembled_math,
            glyph_parameters=replace(
                self.assembled_math.glyph_parameters,
                grid=20000,
            ),
        )
        with self.assertRaisesRegex(PlanError, "UFWORD"):
            plan_font(oversized_font)

        oversized_attachment = replace(
            self.math_data,
            accent_attachments=MappingProxyType({"A": 1000.0}),
        )
        with self.assertRaisesRegex(PlanError, "FWORD"):
            plan_font(
                self.assembled_math,
                math_table_data=oversized_attachment,
            )

        with self.assertRaisesRegex(PlanError, "minConnectorOverlap"):
            plan_font(
                self.assembled_math,
                math_table_data=replace(
                    self.math_data,
                    min_connector_overlap=65536,
                ),
            )

        with self.assertRaisesRegex(PlanError, "Math kern"):
            plan_font(
                self.assembled_math,
                math_table_data=replace(
                    self.math_data,
                    kerns=MappingProxyType({"A": glyph_kern(32768)}),
                ),
            )

    def test_glyph_adjustment_is_applied_once(self) -> None:
        parenleft = self.math_plan.glyphs["parenleft"]

        self.assertEqual(parenleft.width, 450)

    def test_variant_glyph_group_adjusts_base_and_discrete_variants(self) -> None:
        baseline = plan_font(
            self.assembled_math,
            math_table_data=self.math_data,
        )
        adjusted = plan_font(
            self.assembled_math,
            adjustment_config(
                {"parenleft@variant_glyphs": adjustment(40, 30)}
            ),
            math_table_data=self.math_data,
        )
        names = (
            "parenleft",
            *self.math_data.vertical_variant_glyphs["parenleft"],
        )

        for name in names:
            self.assertEqual(
                adjusted.glyphs[name].width,
                baseline.glyphs[name].width + 70,
            )
        assert baseline.math_table is not None
        assert adjusted.math_table is not None
        self.assertEqual(
            adjusted.math_table.vertical_variant_records["parenleft"],
            baseline.math_table.vertical_variant_records["parenleft"],
        )

    def test_vertical_part_group_adjusts_layout_but_not_base(self) -> None:
        baseline = plan_font(
            self.assembled_math,
            math_table_data=self.math_data,
        )
        adjusted = plan_font(
            self.assembled_math,
            adjustment_config({"parenleft@parts": adjustment(40, 30)}),
            math_table_data=self.math_data,
        )
        part_names = {
            part.glyph_name
            for part in self.math_data.vertical_assemblies["parenleft"].parts
        }

        self.assertEqual(
            adjusted.glyphs["parenleft"],
            baseline.glyphs["parenleft"],
        )
        for name in part_names:
            self.assertEqual(
                adjusted.glyphs[name].width,
                baseline.glyphs[name].width + 70,
            )
        assert baseline.math_table is not None
        assert adjusted.math_table is not None
        self.assertEqual(
            adjusted.math_table.vertical_assemblies["parenleft"],
            baseline.math_table.vertical_assemblies["parenleft"],
        )

    def test_variants_group_combines_discrete_and_part_adjustments(self) -> None:
        baseline = plan_font(
            self.assembled_math,
            math_table_data=self.math_data,
        )
        adjusted = plan_font(
            self.assembled_math,
            adjustment_config({"parenleft@variants": adjustment(25, 15)}),
            math_table_data=self.math_data,
        )
        names = {
            "parenleft",
            *self.math_data.vertical_variant_glyphs["parenleft"],
            *(
                part.glyph_name
                for part in self.math_data.vertical_assemblies[
                    "parenleft"
                ].parts
            ),
        }

        for name in names:
            self.assertEqual(
                adjusted.glyphs[name].width,
                baseline.glyphs[name].width + 40,
            )

    def test_horizontal_groups_allow_only_discrete_variants(self) -> None:
        baseline = plan_font(
            self.assembled_math,
            math_table_data=self.math_data,
        )
        adjusted = plan_font(
            self.assembled_math,
            adjustment_config(
                {"uni23B4@variant_glyphs": adjustment(left=20)}
            ),
            math_table_data=self.math_data,
        )
        names = (
            "uni23B4",
            *self.math_data.horizontal_variant_glyphs["uni23B4"],
        )
        for name in names:
            self.assertEqual(
                adjusted.glyphs[name].width,
                baseline.glyphs[name].width + 20,
            )
        assert baseline.math_table is not None
        assert adjusted.math_table is not None
        self.assertEqual(
            adjusted.math_table.horizontal_variant_records["uni23B4"],
            baseline.math_table.horizontal_variant_records["uni23B4"],
        )

        for group_kind in ("parts", "variants"):
            with self.subTest(group_kind=group_kind):
                with self.assertRaisesRegex(PlanError, "horizontal"):
                    plan_font(
                        self.assembled_math,
                        adjustment_config(
                            {
                                f"uni23B4@{group_kind}": adjustment(
                                    left=20
                                )
                            }
                        ),
                        math_table_data=self.math_data,
                    )

    def test_part_groups_require_an_existing_vertical_assembly(self) -> None:
        data = replace(
            self.math_data,
            vertical_assemblies=MappingProxyType(
                {
                    base: assembly
                    for base, assembly in self.math_data.vertical_assemblies.items()
                    if base != "parenleft"
                }
            ),
        )

        for group_kind in ("parts", "variants"):
            with self.subTest(group_kind=group_kind):
                with self.assertRaisesRegex(PlanError, "requires a vertical"):
                    plan_font(
                        self.assembled_math,
                        adjustment_config(
                            {
                                f"parenleft@{group_kind}": adjustment(
                                    left=10
                                )
                            }
                        ),
                        math_table_data=data,
                    )

        plan_font(
            self.assembled_math,
            adjustment_config(
                {"parenleft@variant_glyphs": adjustment(left=10)}
            ),
            math_table_data=data,
        )

    def test_group_adjustments_require_math_data_and_known_bases(self) -> None:
        value = adjustment(left=10)
        for selector_name, math_data in (
            ("parenleft@variant_glyphs", None),
            ("missing@variant_glyphs", self.math_data),
        ):
            with self.subTest(selector=selector_name):
                with self.assertRaisesRegex(PlanError, "no MATH construction"):
                    plan_font(
                        self.assembled_math,
                        adjustment_config({selector_name: value}),
                        math_table_data=math_data,
                    )

    def test_direct_part_and_group_overlap_adjustments_are_rejected(self) -> None:
        value = adjustment(left=10)
        invalid_configs = (
            {
                "parenleft@variant_glyphs": value,
                "parenleft": value,
            },
            {
                "parenleft@variants": value,
                "parenleft@parts": value,
            },
            {"uni239C": value},
            {"uni23B4.ex": value},
        )

        for config in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaises(PlanError):
                    plan_font(
                        self.assembled_math,
                        adjustment_config(config),
                        math_table_data=self.math_data,
                    )

    def test_shared_owner_groups_require_complete_equal_adjustments(self) -> None:
        equal = adjustment(left=20)
        config = adjustment_config(
            {
                "bar@variants": equal,
                "divides@variants": adjustment(20, 0),
            }
        )
        baseline = plan_font(
            self.assembled_math,
            math_table_data=self.math_data,
        )

        with patch(
            "skeletonfont.planning.glyphs._plan_variant_glyph",
            wraps=_plan_variant_glyph,
        ) as variant_planner:
            adjusted = plan_font(
                self.assembled_math,
                config,
                math_table_data=self.math_data,
            )
        reversed_plan = plan_font(
            self.assembled_math,
            dict(reversed(tuple(config.items()))),
            math_table_data=self.math_data,
        )

        planned_names = [
            call.args[0].name for call in variant_planner.call_args_list
        ]
        self.assertEqual(planned_names.count("divides.v1"), 1)
        self.assertEqual(
            adjusted.glyphs["divides.v1"].width,
            baseline.glyphs["divides.v1"].width + 20,
        )
        self.assertEqual(
            adjusted.glyphs["divides.ex"].width,
            baseline.glyphs["divides.ex"].width + 20,
        )
        self.assertEqual(adjusted, reversed_plan)

        with self.assertRaisesRegex(PlanError, "owner construction"):
            plan_font(
                self.assembled_math,
                adjustment_config({"bar@variants": equal}),
                math_table_data=self.math_data,
            )
        with self.assertRaisesRegex(
            PlanError,
            "incompatible spacing adjustments",
        ):
            plan_font(
                self.assembled_math,
                adjustment_config(
                    {
                        "bar@variants": equal,
                        "divides@variants": adjustment(left=30),
                    }
                ),
                math_table_data=self.math_data,
            )

    def test_shared_part_groups_require_complete_equal_adjustments(self) -> None:
        equal = adjustment(right=20)
        baseline = plan_font(
            self.assembled_math,
            math_table_data=self.math_data,
        )
        adjusted = plan_font(
            self.assembled_math,
            adjustment_config(
                {
                    "bar@parts": equal,
                    "divides@parts": adjustment(0, 20),
                }
            ),
            math_table_data=self.math_data,
        )

        self.assertEqual(
            adjusted.glyphs["divides.ex"].width,
            baseline.glyphs["divides.ex"].width + 20,
        )
        with self.assertRaisesRegex(PlanError, "owner assembly"):
            plan_font(
                self.assembled_math,
                adjustment_config({"bar@parts": equal}),
                math_table_data=self.math_data,
            )
        with self.assertRaisesRegex(
            PlanError,
            "incompatible spacing adjustments",
        ):
            plan_font(
                self.assembled_math,
                adjustment_config(
                    {
                        "bar@parts": equal,
                        "divides@parts": adjustment(right=30),
                    }
                ),
                math_table_data=self.math_data,
            )

    def test_monospace_rejects_only_current_width_adjustment_fields(self) -> None:
        with self.assertRaisesRegex(PlanError, "Monospace ordinary"):
            plan_font(
                assembled_font("ascii"),
                adjustment_config({"A": adjustment(left=10)}),
            )

        parameters = replace(
            self.assembled_math.glyph_parameters,
            monospace_width=900,
        )
        plan_font(
            replace(self.assembled_math, glyph_parameters=parameters),
            adjustment_config(
                {"parenleft@variant_glyphs": adjustment(left=10)}
            ),
            math_table_data=self.math_data,
        )

    def test_scaled_edge_thickness_affects_metrics(self) -> None:
        minute = self.math_plan.glyphs["minute.st"]

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
            self.math_table,
            math_table_data=self.math_data,
        ).glyphs["minute.st"]
        self.assertEqual(unscaled.width, 400)
        self.assertEqual(unscaled.strokes[0].radius, 35)

    def test_glyph_alias_records_only_its_copy_source(self) -> None:
        alias = next(
            glyph_alias
            for glyph_alias in self.math_plan.glyph_aliases
            if glyph_alias.target_name == "A.italic"
        )

        self.assertEqual(alias.source_name, "A")
        self.assertEqual(alias.target_codepoint, 0x1D434)
        self.assertFalse(hasattr(alias, "strokes"))

    def test_monospace_uses_fixed_width_and_source_x_offset(self) -> None:
        mono_plan = plan_font(assembled_font("ascii"))
        a = mono_plan.glyphs["A"]
        space = mono_plan.glyphs["space"]

        self.assertEqual(a.width, 600)
        self.assertEqual(space.width, 600)
        self.assertEqual(a.strokes[0].centerline[0], (100.0, 25.0))
        self.assertEqual(a.strokes[0].centerline[-1], (500.0, 25.0))

    def test_local_monospace_width_plans_only_its_ordinary_glyph(self) -> None:
        assembled = assembled_font("ascii")
        glyphs = dict(assembled.glyphs)
        glyphs["A"] = replace(
            glyphs["A"],
            ordinary_monospace_width=500,
        )
        local = replace(
            assembled,
            glyph_parameters=replace(
                assembled.glyph_parameters,
                monospace_width=None,
            ),
            glyphs=MappingProxyType(glyphs),
        )

        plan = plan_font(local)

        self.assertEqual(plan.glyphs["A"].width, 650)
        self.assertEqual(
            plan.glyphs["A"].strokes[0].centerline[0],
            (125.0, 25.0),
        )
        self.assertEqual(
            plan.glyphs["A"].strokes[0].centerline[-1],
            (525.0, 25.0),
        )

        with self.assertRaisesRegex(PlanError, "Monospace ordinary"):
            plan_font(
                local,
                adjustment_config({"A": adjustment(left=0)}),
            )

    def test_ssty_generator_width_controls_only_its_alternate(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        parameters = replace(meta.glyph_parameters, monospace_width=None)
        domain = UnicodeDomain(((0x0041, 0x0041),))

        fixed = assemble_font(
            replace(
                meta,
                glyph_parameters=parameters,
                ssty_generators=(
                    SstyGenerator(domain, "st", 1.2, 450),
                ),
            ),
            GlyphCatalog(PROJECT_DIRECTORY),
        )

        self.assertEqual(plan_font(fixed).glyphs["A.st"].width, 600)
        with self.assertRaisesRegex(PlanError, "Monospace ordinary"):
            plan_font(
                fixed,
                adjustment_config({"A.st": adjustment(right=10)}),
            )

        proportional = assemble_font(
            replace(
                meta,
                glyph_parameters=parameters,
                ssty_generators=(
                    SstyGenerator(domain, "st", 1.2, None),
                ),
            ),
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        baseline_width = plan_font(proportional).glyphs["A.st"].width
        adjusted_width = plan_font(
            proportional,
            adjustment_config({"A.st": adjustment(right=10)}),
        ).glyphs["A.st"].width

        self.assertEqual(adjusted_width, baseline_width + 10)

    def test_special_roles_ignore_local_monospace_width(self) -> None:
        glyphs = dict(self.assembled_math.glyphs)
        glyphs["circumflexcmb"] = replace(
            glyphs["circumflexcmb"],
            ordinary_monospace_width=500,
        )
        glyphs["parenleft"] = replace(
            glyphs["parenleft"],
            ordinary_monospace_width=500,
        )
        assembled = replace(
            self.assembled_math,
            glyphs=MappingProxyType(glyphs),
        )

        baseline = plan_font(
            assembled,
            math_table_data=self.math_data,
            accent_glyphs=self.accent_glyphs,
        )
        adjusted = plan_font(
            assembled,
            adjustment_config({"parenleft": adjustment(left=10)}),
            math_table_data=self.math_data,
            accent_glyphs=self.accent_glyphs,
        )

        self.assertEqual(baseline.glyphs["circumflexcmb"].width, 0)
        self.assertEqual(
            adjusted.glyphs["parenleft"].width,
            baseline.glyphs["parenleft"].width + 10,
        )

    def test_monospace_design_origin_tracks_core_width_center(self) -> None:
        assembled = assembled_font("ascii")
        narrow_assembled = replace(
            assembled,
            glyph_parameters=replace(
                assembled.glyph_parameters,
                monospace_width=500,
            ),
        )

        a = plan_font(narrow_assembled).glyphs["A"]

        self.assertEqual(a.width, 650)
        self.assertEqual(a.strokes[0].centerline[0], (125.0, 25.0))
        self.assertEqual(a.strokes[0].centerline[-1], (525.0, 25.0))

    def test_monospace_center_does_not_depend_on_radius(self) -> None:
        assembled = assembled_font("ascii")
        thick_assembled = replace(
            assembled,
            glyph_parameters=replace(
                assembled.glyph_parameters,
                radius=50,
            ),
        )

        a = plan_font(thick_assembled).glyphs["A"]

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
            self.math_table,
            math_table_data=self.math_data,
        ).glyphs["A"]

        self.assertEqual(
            shifted.strokes[0].centerline[0],
            (100.0, 55.0),
        )

    def test_monospace_meta_spacing_preserves_equal_width(self) -> None:
        assembled = assembled_font("ascii")
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
        a = plan.glyphs["A"]
        space = plan.glyphs["space"]

        self.assertEqual(a.width, 500)
        self.assertEqual(space.width, 500)
        self.assertEqual(plan.glyphs[".notdef"].width, 500)
        self.assertEqual(a.strokes[0].centerline[0], (45.0, 25.0))

    def test_preloaded_kerning_is_retained_by_the_plan(self) -> None:
        assembled = assembled_font("fraktur")
        kerning = load_kerning_data(PROJECT_DIRECTORY, "fraktur.json")
        plan = plan_font(assembled, kerning=kerning)
        self.assertIs(plan.kerning, kerning)

    def test_unused_config_name_is_rejected(self) -> None:
        config = dict(self.math_table)
        config[selector("does.not.exist")] = adjustment(left=1)

        with self.assertRaisesRegex(PlanError, "does.not.exist"):
            plan_font(
                self.assembled_math,
                config,
                math_table_data=self.math_data,
            )


if __name__ == "__main__":
    unittest.main()
