from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.skeletonfont_editor.identity import GlyphIdentityMap


class GlyphIdentityMapTests(unittest.TestCase):
    def test_null_unicode_value_means_unencoded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "identities.json"
            path.write_text(
                '{"A": "0041", "unencoded": null}',
                encoding="utf-8",
            )

            identity_map = GlyphIdentityMap.load(path)

        self.assertEqual(identity_map.identities["A"], 0x0041)
        self.assertIsNone(identity_map.identities["unencoded"])


if __name__ == "__main__":
    unittest.main()
