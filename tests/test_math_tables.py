from __future__ import annotations

import io
import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from fontTools.ttLib import TTFont

from skeletonfont.assembler import GlyphCatalog, assemble_font
from skeletonfont.compiler import compile_font
from skeletonfont.loader import (
    load_font_meta,
    load_glyph_config,
    load_math_data,
)
from skeletonfont.math_tables import apply_math_table
from skeletonfont.model import (
    MathAssemblyPartPlan,
    MathGlyphAssemblyPlan,
    MathGlyphKernData,
    MathKernTableData,
    MathPlan,
)
from skeletonfont.planner import plan_font
from skeletonfont.renderer import render_font


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class MathTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        math_meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert math_meta.math_config is not None
        cls.math_data = load_math_data(
            PROJECT_DIRECTORY,
            math_meta.math_config,
        )
        cls.math_assembled = assemble_font(
            math_meta,
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        cls.math_config = load_glyph_config(
            PROJECT_DIRECTORY,
            math_meta.glyph_config_file,
        )

    def test_ssty_with_two_alternates_compiles_as_alternate_substitution(self) -> None:
        two_level_data = replace(
            self.math_data,
            ssty=MappingProxyType(
                {"minute": ("minute.st", "A")}
            ),
        )
        plan = plan_font(
            self.math_assembled,
            self.math_config,
            math_data=two_level_data,
        )
        font = compile_font(render_font(plan))

        gsub = font["GSUB"].table
        ssty = next(
            record.Feature
            for record in gsub.FeatureList.FeatureRecord
            if record.FeatureTag == "ssty"
        )
        lookup_types = [
            gsub.LookupList.Lookup[index].LookupType
            for index in ssty.LookupListIndex
        ]
        self.assertEqual(lookup_types, [3])

    def test_math_script_is_created_when_no_ssty_generates_gsub(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        assembled = assemble_font(
            meta,
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        font = compile_font(render_font(plan_font(assembled)))
        self.assertNotIn("GSUB", font)

        plan = MathPlan(
            constants=self.math_data.constants,
            ssty_feature=None,
            vertical_variant_records=MappingProxyType({}),
            horizontal_variant_records=MappingProxyType({}),
            min_connector_overlap=0,
            vertical_assemblies=MappingProxyType({}),
            horizontal_assemblies=MappingProxyType({}),
            extended_shapes=frozenset(),
            italic_corrections=MappingProxyType({}),
            top_accent_attachments=MappingProxyType({}),
            kerns=MappingProxyType(
                {
                    "A": MathGlyphKernData(
                        bottom_right=MathKernTableData((), (-40,))
                    )
                }
            ),
        )
        apply_math_table(font, plan)

        buffer = io.BytesIO()
        font.save(buffer)
        buffer.seek(0)
        reopened = TTFont(buffer)
        self.assertIn("MATH", reopened)
        self.assertEqual(
            [
                record.ScriptTag
                for record in reopened["GSUB"].table.ScriptList.ScriptRecord
            ],
            ["math"],
        )
        self.assertEqual(
            reopened["GSUB"].table.FeatureList.FeatureRecord,
            [],
        )
        self.assertEqual(reopened["GSUB"].table.LookupList.Lookup, [])
        kern_info = reopened["MATH"].table.MathGlyphInfo.MathKernInfo
        self.assertEqual(kern_info.MathKernCoverage.glyphs, ["A"])
        bottom_right = kern_info.MathKernInfoRecords[0].BottomRightMathKern
        self.assertEqual(bottom_right.HeightCount, 0)
        self.assertEqual(
            [value.Value for value in bottom_right.KernValue],
            [-40],
        )

    def test_vertical_and_horizontal_assemblies_are_serialized(self) -> None:
        base_plan = plan_font(
            self.math_assembled,
            self.math_config,
            math_data=self.math_data,
        )
        font = compile_font(render_font(base_plan))
        vertical = MathGlyphAssemblyPlan(
            italic_correction=10,
            parts=(
                MathAssemblyPartPlan(
                    glyph_name="parenleft.v1",
                    start_connector_length=0,
                    end_connector_length=50,
                    full_advance=1025,
                    extender=False,
                ),
                MathAssemblyPartPlan(
                    glyph_name="radical.v1",
                    start_connector_length=50,
                    end_connector_length=50,
                    full_advance=1075,
                    extender=True,
                ),
            ),
        )
        horizontal = MathGlyphAssemblyPlan(
            italic_correction=0,
            parts=(
                MathAssemblyPartPlan(
                    glyph_name="equal",
                    start_connector_length=50,
                    end_connector_length=50,
                    full_advance=600,
                    extender=True,
                ),
                MathAssemblyPartPlan(
                    glyph_name="arrowleft",
                    start_connector_length=50,
                    end_connector_length=0,
                    full_advance=825,
                    extender=False,
                ),
            ),
        )
        plan = MathPlan(
            constants=self.math_data.constants,
            ssty_feature=None,
            vertical_variant_records=(
                base_plan.math.vertical_variant_records
            ),
            horizontal_variant_records=MappingProxyType({}),
            min_connector_overlap=20,
            vertical_assemblies=MappingProxyType({"parenleft": vertical}),
            horizontal_assemblies=MappingProxyType({"arrowright": horizontal}),
            extended_shapes=frozenset({"parenleft"}),
            italic_corrections=MappingProxyType({}),
            top_accent_attachments=MappingProxyType({}),
            kerns=MappingProxyType({}),
        )

        apply_math_table(font, plan)
        buffer = io.BytesIO()
        font.save(buffer)
        buffer.seek(0)
        reopened = TTFont(buffer)
        variants = reopened["MATH"].table.MathVariants

        self.assertEqual(variants.MinConnectorOverlap, 20)
        vertical_index = variants.VertGlyphCoverage.glyphs.index("parenleft")
        vertical_assembly = variants.VertGlyphConstruction[
            vertical_index
        ].GlyphAssembly
        self.assertEqual(vertical_assembly.ItalicsCorrection.Value, 10)
        self.assertEqual(
            [
                (
                    part.glyph,
                    part.PartFlags,
                    part.StartConnectorLength,
                    part.EndConnectorLength,
                    part.FullAdvance,
                )
                for part in vertical_assembly.PartRecords
            ],
            [
                ("parenleft.v1", 0, 0, 50, 1025),
                ("radical.v1", 1, 50, 50, 1075),
            ],
        )

        horizontal_index = variants.HorizGlyphCoverage.glyphs.index(
            "arrowright"
        )
        horizontal_assembly = variants.HorizGlyphConstruction[
            horizontal_index
        ].GlyphAssembly
        self.assertEqual(
            [part.glyph for part in horizontal_assembly.PartRecords],
            ["equal", "arrowleft"],
        )


if __name__ == "__main__":
    unittest.main()
