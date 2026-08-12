from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skeletonfont.errors import ProjectDataError

from tools.skeletonfont_editor.settings import (
    EditorSettings,
    load_editor_settings,
    parse_guide_values,
    save_editor_settings,
    shortcut_sequences,
    validate_shortcuts,
)


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class EditorSettingsTests(unittest.TestCase):
    def test_bundled_settings_define_requested_guidelines(self) -> None:
        settings = load_editor_settings()

        self.assertEqual(settings.guide_x, (-8.0, -4.0, 0.0, 4.0, 8.0))
        self.assertEqual(
            settings.guide_y,
            (-8.0, -4.0, 0.0, 4.0, 8.0, 12.0),
        )

    def test_readable_shortcuts_are_translated_to_tk_sequences(self) -> None:
        self.assertEqual(
            shortcut_sequences("Ctrl+S"),
            ("<Control-KeyPress-s>",),
        )
        self.assertEqual(
            shortcut_sequences("Z"),
            ("<KeyPress-z>", "<KeyPress-Z>"),
        )
        self.assertEqual(shortcut_sequences("Left"), ("<KeyPress-Left>",))
        shortcuts = load_editor_settings().shortcuts
        self.assertEqual(shortcuts["select_all_strokes"], "Ctrl+A")
        self.assertNotIn("previous_glyph", shortcuts)
        self.assertNotIn("next_glyph", shortcuts)

    def test_duplicate_shortcuts_are_rejected(self) -> None:
        shortcuts = dict(load_editor_settings().shortcuts)
        shortcuts["redo"] = shortcuts["undo"]

        with self.assertRaisesRegex(ValueError, "both"):
            validate_shortcuts(shortcuts)

    def test_missing_settings_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "missing.json"
            with patch(
                "tools.skeletonfont_editor.settings.EDITOR_SETTINGS_PATH",
                path,
            ), self.assertRaisesRegex(ProjectDataError, "Cannot read"):
                load_editor_settings()

    def test_incomplete_settings_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "editor_settings.json"
            path.write_text('{"guide_x": []}', encoding="utf-8")
            with patch(
                "tools.skeletonfont_editor.settings.EDITOR_SETTINGS_PATH",
                path,
            ), self.assertRaisesRegex(ProjectDataError, "Missing editor settings"):
                load_editor_settings()

    def test_settings_are_saved_and_loaded(self) -> None:
        configured_shortcuts = load_editor_settings().shortcuts
        settings = EditorSettings(
            guide_x=parse_guide_values("0, 5.5"),
            guide_y=parse_guide_values("-2, 0, 9"),
            shortcuts={**configured_shortcuts, "save": "Ctrl+F12"},
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "editor_settings.json"

            with patch(
                "tools.skeletonfont_editor.settings.EDITOR_SETTINGS_PATH",
                path,
            ):
                save_editor_settings(settings)
                loaded = load_editor_settings()

        self.assertEqual(loaded, settings)


if __name__ == "__main__":
    unittest.main()
