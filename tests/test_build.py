from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fontTools.ttLib import TTFont

from skeletonfont.build import build_font


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class BuildPipelineTests(unittest.TestCase):
    def test_ascii_is_built_directly_to_final_otf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)

            output_path = build_font(
                PROJECT_DIRECTORY,
                "ascii",
                output_directory=output_directory,
            )

            self.assertEqual(output_path.name, "PL46-Ascii.otf")
            self.assertEqual(list(output_directory.iterdir()), [output_path])
            font = TTFont(output_path)
            self.assertEqual(font.getBestCmap()[0x0041], "A")
            self.assertEqual(font["hmtx"].metrics["A"][0], 600)
            self.assertNotIn("MATH", font)
            font.close()

    def test_math_is_built_with_math_and_ssty_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            output_path = build_font(
                PROJECT_DIRECTORY,
                "math",
                output_directory=output_directory,
            )

            self.assertEqual(output_path.name, "PL46-Math.otf")
            self.assertEqual(list(output_directory.iterdir()), [output_path])
            font = TTFont(output_path)
            self.assertIn("MATH", font)
            self.assertIn("GSUB", font)
            self.assertEqual(
                font["MATH"].table.MathConstants.AxisHeight.Value,
                225,
            )
            italics_correction = (
                font["MATH"]
                .table.MathGlyphInfo.MathItalicsCorrectionInfo
            )
            serialized_italic_corrections = dict(
                zip(
                    italics_correction.Coverage.glyphs,
                    (
                        value.Value
                        for value in italics_correction.ItalicsCorrection
                    ),
                    strict=True,
                )
            )
            self.assertEqual(
                serialized_italic_corrections["contourintegral.v1"],
                200,
            )
            self.assertEqual(
                set(serialized_italic_corrections.values()),
                {200},
            )
            accent_attachment = (
                font["MATH"]
                .table.MathGlyphInfo.MathTopAccentAttachment
            )
            serialized_accent_attachments = dict(
                zip(
                    accent_attachment.TopAccentCoverage.glyphs,
                    (
                        value.Value
                        for value in accent_attachment.TopAccentAttachment
                    ),
                    strict=True,
                )
            )
            self.assertEqual(serialized_accent_attachments["j"], 400)
            self.assertEqual(serialized_accent_attachments["j.italic"], 400)
            self.assertEqual(serialized_accent_attachments["t"], 200)
            self.assertEqual(serialized_accent_attachments["t.italic"], 200)

            self.assertIsNone(
                font["MATH"].table.MathGlyphInfo.MathKernInfo
            )

            scripts = {
                record.ScriptTag: record.Script
                for record in font["GSUB"].table.ScriptList.ScriptRecord
            }
            self.assertIn("math", scripts)
            feature_records = font["GSUB"].table.FeatureList.FeatureRecord
            math_feature_indexes = scripts["math"].DefaultLangSys.FeatureIndex
            self.assertEqual(
                [feature_records[index].FeatureTag for index in math_feature_indexes],
                ["ssty"],
            )
            ssty_feature = feature_records[math_feature_indexes[0]].Feature
            self.assertEqual(
                [
                    font["GSUB"].table.LookupList.Lookup[index].LookupType
                    for index in ssty_feature.LookupListIndex
                ],
                [1],
            )

            variants = font["MATH"].table.MathVariants
            self.assertEqual(variants.MinConnectorOverlap, 20)
            index = variants.VertGlyphCoverage.glyphs.index("parenleft")
            construction = variants.VertGlyphConstruction[index]
            self.assertEqual(
                [
                    (record.VariantGlyph, record.AdvanceMeasurement)
                    for record in construction.MathGlyphVariantRecord
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
            self.assertIn(
                "parenleft",
                font[
                    "MATH"
                ].table.MathGlyphInfo.ExtendedShapeCoverage.glyphs,
            )
            font.close()

    def test_accent_metrics_apply_without_math(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = build_font(
                PROJECT_DIRECTORY,
                "mono",
                output_directory=Path(temporary_directory),
            )

            font = TTFont(output_path)
            self.assertNotIn("MATH", font)
            self.assertEqual(font["hmtx"].metrics["tildecomb"][0], 0)
            self.assertEqual(font["hmtx"].metrics["circumflexcmb"][0], 0)
            font.close()


if __name__ == "__main__":
    unittest.main()
