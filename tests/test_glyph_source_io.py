from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from skeletonfont.glyph_source_io import (
    load_glyph_source,
    serialize_glyph_source,
    write_glyph_source,
)
from skeletonfont.errors import ProjectDataError


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class GlyphSourceIOTests(unittest.TestCase):
    def test_serialization_writes_outer_fields_and_omits_record_defaults(self) -> None:
        source = load_glyph_source(
            PROJECT_DIRECTORY / "glyph_sources" / "ascii" / "A_0041.json"
        )

        text = serialize_glyph_source(source)

        self.assertIn('"centerline"', text)
        self.assertIn(
            '"centerline": [[0, 0], [0, 3], [2, 6], [4, 3], [4, 0]]',
            text,
        )
        self.assertIn('"monospace_x_offset": -2', text)
        self.assertIn('"y_offset": 0', text)
        self.assertNotIn('"polyline"', text)
        self.assertNotIn('"thickness_scale": 1', text)
        self.assertNotIn('"filled": false', text)

    def test_atomic_write_can_be_loaded_by_the_builder(self) -> None:
        source = load_glyph_source(
            PROJECT_DIRECTORY / "glyph_sources" / "ascii" / "A_0041.json"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "A_0041.json"

            written = write_glyph_source(replace(source, source_path=path), path)
            loaded = load_glyph_source(path)

        self.assertEqual(written, loaded)

    def test_empty_glyph_serializes_grid_advance_as_x_extent(self) -> None:
        source = load_glyph_source(
            PROJECT_DIRECTORY / "glyph_sources" / "ascii" / "space_0020.json"
        )

        text = serialize_glyph_source(source)

        self.assertIn('"x_extent": 4', text)
        self.assertNotIn('"skeleton"', text)
        self.assertNotIn('"length"', text)

    def test_serialization_rejects_inconsistent_skeleton_extents(self) -> None:
        source = load_glyph_source(
            PROJECT_DIRECTORY / "glyph_sources" / "ascii" / "A_0041.json"
        )

        with self.assertRaisesRegex(ProjectDataError, "inconsistent"):
            serialize_glyph_source(replace(source, y_extent=None))


if __name__ == "__main__":
    unittest.main()
