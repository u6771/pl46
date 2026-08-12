from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from skeletonfont.errors import ProjectDataError
from skeletonfont.glyph_source_io import load_glyph_source
from tools.skeletonfont_editor.document import (
    EditableStroke,
    EditorDocument,
    glyph_filename,
)
from tools.skeletonfont_editor.app import SkeletonFontEditor
from tools.skeletonfont_editor.identity import GlyphIdentity, GlyphIdentityMap
from tools.skeletonfont_editor.session import Drawing, Editing, EditorSession
from tools.skeletonfont_editor.workspace import SourceWorkspace


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class EditorDocumentTests(unittest.TestCase):
    def test_builder_source_round_trips_through_editable_document(self) -> None:
        source = load_glyph_source(
            PROJECT_DIRECTORY
            / "glyph_sources"
            / "latin"
            / "upright_latin"
            / "A_0041.json"
        )
        document = EditorDocument.from_source(source)

        restored = document.validated_source(source.source_path)

        self.assertEqual(restored, source)

    def test_filled_centerline_requires_supported_simple_shape(self) -> None:
        stroke = EditableStroke(
            centerline=[
                (0.0, 0.0),
                (2.0, 2.0),
                (0.0, 2.0),
                (2.0, 0.0),
                (0.0, 0.0),
            ],
            filled=True,
        )

        with self.assertRaisesRegex(ProjectDataError, "signed area"):
            stroke.to_record()

    def test_filename_uses_explicit_name_and_codepoint(self) -> None:
        self.assertEqual(glyph_filename("A", 0x41), "A_0041.json")
        self.assertEqual(glyph_filename("parenleft.v1", None), "parenleft.v1.json")

    def test_normalization_computes_offsets_without_moving_display(self) -> None:
        document = EditorDocument(
            strokes=[
                EditableStroke(centerline=[(-2.0, 3.0), (2.0, 7.0)])
            ]
        )
        before = [
            document.display_point(point)
            for point in document.strokes[0].centerline
        ]

        document.normalize_skeleton()

        after = [
            document.display_point(point)
            for point in document.strokes[0].centerline
        ]
        self.assertEqual(before, after)
        self.assertEqual(document.monospace_x_offset, -2.0)
        self.assertEqual(document.y_offset, 3.0)
        self.assertEqual(document.strokes[0].centerline, [(0.0, 0.0), (4.0, 4.0)])

    def test_normalization_preserves_offsets_for_empty_glyph(self) -> None:
        document = EditorDocument(
            monospace_x_offset=-3.0,
            y_offset=2.0,
            x_extent=4.0,
        )

        document.normalize_skeleton()

        self.assertEqual(document.monospace_x_offset, -3.0)
        self.assertEqual(document.y_offset, 2.0)

    def test_skeleton_and_x_extent_are_mutually_exclusive(self) -> None:
        document = EditorDocument(
            name="A",
            codepoint=0x41,
            x_extent=4.0,
            strokes=[EditableStroke(centerline=[(0.0, 0.0)])],
        )

        with self.assertRaisesRegex(ProjectDataError, "exactly one"):
            document.validated_source(Path("A_0041.json"))

        with self.assertRaisesRegex(ProjectDataError, "exactly one"):
            EditorDocument(name="space", codepoint=0x20).validated_source(
                Path("space_0020.json")
            )

    def test_loaded_document_identity_cannot_be_changed_in_place(self) -> None:
        source = load_glyph_source(
            PROJECT_DIRECTORY
            / "glyph_sources"
            / "latin"
            / "upright_latin"
            / "A_0041.json"
        )
        document = EditorDocument.from_source(source)
        document.name = "B"
        document.codepoint = 0x42

        with self.assertRaisesRegex(ProjectDataError, "Save As"):
            document.validated_source(source.source_path)


class EditorSessionTests(unittest.TestCase):
    def test_interaction_has_explicit_editing_and_drawing_states(self) -> None:
        session = EditorSession(
            EditorDocument(strokes=[EditableStroke([(0.0, 0.0)])])
        )
        session.selection = (0,)

        session.begin_draft((1.0, 2.0), "flat")

        self.assertIsInstance(session.interaction, Drawing)
        self.assertEqual(session.selection, ())
        self.assertEqual(session.draft.centerline, [(1.0, 2.0)])
        self.assertEqual(session.draft.start_cap, "flat")

    def test_cancelled_draft_returns_to_saved_clean_state(self) -> None:
        session = EditorSession(EditorDocument(name="A", codepoint=0x41))

        session.begin_draft((0.0, 0.0), "round")
        self.assertTrue(session.dirty)

        session.cancel_draft()

        self.assertIsInstance(session.interaction, Editing)
        self.assertFalse(session.dirty)
        self.assertFalse(session.document.dirty)

    def test_undo_to_saved_content_clears_dirty(self) -> None:
        session = EditorSession(EditorDocument(name="A", codepoint=0x41))

        session.apply(lambda current: setattr(current.document, "name", "B"))
        self.assertTrue(session.dirty)

        self.assertTrue(session.undo())
        self.assertEqual(session.document.name, "A")
        self.assertFalse(session.dirty)

        self.assertTrue(session.redo())
        self.assertEqual(session.document.name, "B")
        self.assertTrue(session.dirty)

    def test_tool_state_is_not_part_of_session_history(self) -> None:
        session = EditorSession(EditorDocument(name="A"))
        drawing_cap = "round"
        session.apply(lambda current: setattr(current.document, "name", "B"))
        drawing_cap = "flat"

        session.undo()

        self.assertEqual(session.document.name, "A")
        self.assertEqual(drawing_cap, "flat")


class GlyphIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.identities = GlyphIdentityMap.load(
            PROJECT_DIRECTORY
            / "tools"
            / "skeletonfont_editor"
            / "glyph_identity_map.json"
        )

    def test_name_determines_unicode_and_canonical_filename(self) -> None:
        self.assertEqual(
            self.identities.resolve("A"),
            GlyphIdentity(name="A", codepoint=0x41),
        )
        self.assertEqual(
            self.identities.resolve("radical.v1"),
            GlyphIdentity(name="radical.v1", codepoint=None),
        )
        self.assertEqual(
            self.identities.resolve("0041"),
            GlyphIdentity(name="A", codepoint=0x41),
        )
        self.assertEqual(
            glyph_filename("radical.v1", None),
            "radical.v1.json",
        )

    def test_source_identity_requires_its_canonical_filename(self) -> None:
        source = load_glyph_source(
            PROJECT_DIRECTORY
            / "glyph_sources"
            / "latin"
            / "upright_latin"
            / "A_0041.json"
        )

        with self.assertRaisesRegex(ProjectDataError, "A_0041.json"):
            self.identities.validate_source(source, Path("wrong.json"))


class SourceWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = SourceWorkspace(PROJECT_DIRECTORY)

    def test_directory_tree_contains_nested_math_sources(self) -> None:
        relative = {
            path.relative_to(self.workspace.source_root).as_posix()
            for path in self.workspace.source_directories()
        }

        self.assertIn("math", relative)
        self.assertIn("math/operator/integral", relative)
        self.assertIn("miscellaneous/integral_tall", relative)

    def test_selected_directory_lists_only_direct_glyph_files(self) -> None:
        directory = self.workspace.source_root / "math"

        entries = self.workspace.glyphs_in(directory)

        self.assertTrue(entries)
        self.assertTrue(all(entry.path.parent == directory for entry in entries))
        self.assertNotIn(
            "contourintegral",
            {entry.display_name for entry in entries},
        )

    def test_recursive_index_contains_nested_directories(self) -> None:
        entries = self.workspace.all_glyphs()

        self.assertTrue(entries)
        self.assertIn(
            "math/delimiter_variants/vertical_variant_glyphs/paren",
            {
                entry.path.parent.relative_to(
                    self.workspace.source_root
                ).as_posix()
                for entry in entries
            },
        )


class WorkspaceMoveTests(unittest.TestCase):
    def _workspace(self, temporary: str) -> SourceWorkspace:
        project = Path(temporary)
        for name in ("one", "two", "target"):
            (project / "glyph_sources" / name).mkdir(parents=True)
        return SourceWorkspace(project)

    def test_invalid_json_files_can_be_moved_without_being_rewritten(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = self._workspace(temporary)
            source = workspace.source_root / "one" / "broken.json"
            source.write_text("not json", encoding="utf-8")

            moves = workspace.move_glyphs(
                (source,), workspace.source_root / "target"
            )

            self.assertEqual(len(moves), 1)
            self.assertFalse(source.exists())
            self.assertEqual(
                moves[0].destination.read_text(encoding="utf-8"), "not json"
            )

    def test_unchanged_glyph_entries_are_reused_from_cache(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = self._workspace(temporary)
            path = workspace.source_root / "one" / "A_0041.json"
            path.write_text("{}", encoding="utf-8")
            source = SimpleNamespace(name="A", codepoint=0x41)
            workspace.identity_map = SimpleNamespace(
                validate_source=lambda _source, _path: None
            )

            with patch(
                "tools.skeletonfont_editor.workspace.load_glyph_source",
                return_value=source,
            ) as load:
                first = workspace.all_glyphs()
                second = workspace.all_glyphs()

            self.assertIs(first[0], second[0])
            self.assertEqual(load.call_count, 1)

    def test_existing_or_batch_duplicate_targets_reject_the_whole_move(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = self._workspace(temporary)
            first = workspace.source_root / "one" / "same.json"
            second = workspace.source_root / "two" / "same.json"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")

            with self.assertRaisesRegex(ProjectDataError, "both become"):
                workspace.plan_glyph_moves(
                    (first, second), workspace.source_root / "target"
                )

            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

            existing_source = workspace.source_root / "one" / "existing.json"
            existing_target = workspace.source_root / "target" / "existing.json"
            existing_source.write_text("source", encoding="utf-8")
            existing_target.write_text("target", encoding="utf-8")
            with self.assertRaisesRegex(ProjectDataError, "already exists"):
                workspace.plan_glyph_moves(
                    (existing_source,), workspace.source_root / "target"
                )
            self.assertEqual(existing_source.read_text(encoding="utf-8"), "source")
            self.assertEqual(existing_target.read_text(encoding="utf-8"), "target")

    def test_runtime_failure_rolls_back_already_moved_files(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = self._workspace(temporary)
            first = workspace.source_root / "one" / "first.json"
            second = workspace.source_root / "one" / "second.json"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            moves = workspace.plan_glyph_moves(
                (first, second), workspace.source_root / "target"
            )
            original_rename = Path.rename
            forward_calls = 0

            def rename_with_failure(path: Path, target: Path):
                nonlocal forward_calls
                if path.parent == workspace.source_root / "one":
                    forward_calls += 1
                    if forward_calls == 2:
                        raise OSError("simulated move failure")
                return original_rename(path, target)

            with patch.object(Path, "rename", autospec=True, side_effect=rename_with_failure):
                with self.assertRaisesRegex(ProjectDataError, "simulated"):
                    workspace.execute_glyph_moves(moves)

            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertFalse((workspace.source_root / "target" / "first.json").exists())


class _FakeGlyphTree:
    def __init__(self) -> None:
        self.items = ("first", "second", "third")
        self.selected: tuple[str, ...] = ()

    def get_children(self) -> tuple[str, ...]:
        return self.items

    def selection(self) -> tuple[str, ...]:
        return self.selected

    def selection_set(self, item: str) -> None:
        self.selected = (item,)

    def focus(self, _item: str) -> None:
        pass

    def see(self, _item: str) -> None:
        pass


class _FakeCanvas:
    def __init__(self) -> None:
        self.rectangles: list[tuple[object, ...]] = []
        self.ovals: list[tuple[object, ...]] = []

    def create_line(self, *_args, **_kwargs) -> None:
        pass

    def create_polygon(self, *_args, **_kwargs) -> None:
        pass

    def create_rectangle(self, *args, **kwargs) -> None:
        self.rectangles.append((*args, kwargs))

    def create_oval(self, *args, **kwargs) -> None:
        self.ovals.append((*args, kwargs))


class _FakeVariable:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def set(self, value: object) -> None:
        self.value = value

    def get(self) -> object:
        return self.value


class _FakeClipboardRoot:
    def __init__(self) -> None:
        self.text = ""

    def clipboard_clear(self) -> None:
        self.text = ""

    def clipboard_append(self, text: str) -> None:
        self.text += text

    def clipboard_get(self) -> str:
        return self.text


class _FakeConfigWidget:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


class _FakeStrokeList:
    def __init__(self) -> None:
        self.selected = (0,)
        self.state = "normal"
        self.activated = None

    def size(self) -> int:
        return 2

    def nearest(self, _y: int) -> int:
        return 1

    def bbox(self, _index: int) -> tuple[int, int, int, int]:
        return (2, 20, 100, 18)

    def selection_clear(self, _first, _last) -> None:
        self.selected = ()

    def selection_set(self, index: int) -> None:
        self.selected = (index,)

    def configure(self, *, state: str) -> None:
        self.state = state

    def curselection(self) -> tuple[int, ...]:
        return self.selected

    def activate(self, index: int) -> None:
        self.activated = index


class _FakeGlyphBrowserTree:
    def __init__(self, row_count: int = 0) -> None:
        self.rows = [f"row-{index}" for index in range(row_count)]
        self.selected: list[str] = []
        self.values: dict[str, tuple[str, ...]] = {}

    def delete(self, *items: str) -> None:
        for item in items:
            if item in self.rows:
                self.rows.remove(item)
            self.values.pop(item, None)
        self.selected = [item for item in self.selected if item in self.rows]

    def insert(self, _parent: str, _index: str, *, values) -> str:
        item = f"row-{len(self.rows)}"
        self.rows.append(item)
        self.values[item] = tuple(values)
        return item

    def get_children(self) -> tuple[str, ...]:
        return tuple(self.rows)

    def identify_row(self, y: int) -> str:
        index = y // 24
        return self.rows[index] if 0 <= index < len(self.rows) else ""

    def bbox(self, item: str) -> tuple[int, int, int, int]:
        if item not in self.rows:
            return ()  # type: ignore[return-value]
        return (0, self.rows.index(item) * 24, 300, 24)

    def selection(self) -> tuple[str, ...]:
        return tuple(self.selected)

    def selection_set(self, *items: str) -> None:
        self.selected = list(items)

    def selection_remove(self, *items: str) -> None:
        removed = set(items)
        self.selected = [item for item in self.selected if item not in removed]

    def see(self, _item: str) -> None:
        pass

    def winfo_width(self) -> int:
        return 300

    def winfo_height(self) -> int:
        return 120


class EditorInteractionTests(unittest.TestCase):
    def test_user_directory_selection_clears_glyph_search(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        active = Path("glyph_sources/ascii").resolve()
        target = Path("glyph_sources/math").resolve()
        editor._changing_directory = False
        editor.active_source_directory = active
        editor.directory_tree = SimpleNamespace(selection=lambda: ("math",))
        editor._directory_by_item = {"math": target}
        editor.search_var = _FakeVariable("radical")
        editor._confirm_document_transition = lambda: True
        selections: list[tuple[Path, bool, str]] = []
        editor._select_directory = lambda directory, *, clear_document: (
            selections.append(
                (directory, clear_document, editor.search_var.get())
            )
        )

        editor._on_directory_tree_selected()

        self.assertEqual(editor.search_var.get(), "")
        self.assertEqual(selections, [(target, True, "")])

    def test_programmatic_directory_selection_does_not_clear_search(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor._changing_directory = True
        editor.search_var = _FakeVariable("radical")

        editor._on_directory_tree_selected()

        self.assertEqual(editor.search_var.get(), "radical")

    def test_multi_selection_shows_common_and_mixed_stroke_properties(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.document = EditorDocument(
            strokes=[
                EditableStroke(
                    centerline=[(0.0, 0.0)],
                    thickness_scale=1.6,
                    start_cap="round",
                    end_cap="flat",
                    filled=False,
                ),
                EditableStroke(
                    centerline=[(1.0, 0.0)],
                    thickness_scale=1.6,
                    start_cap="flat",
                    end_cap="flat",
                    filled=True,
                ),
            ]
        )
        editor.draft_centerline = []
        editor.stroke_list = _FakeStrokeList()
        editor.stroke_list.selected = (0, 1)
        editor.selected_stroke_indices = ()
        editor.thickness_scale_var = _FakeVariable()
        editor.start_cap_var = _FakeVariable()
        editor.end_cap_var = _FakeVariable()
        editor.filled_var = _FakeVariable()
        editor.status_var = _FakeVariable()
        editor._redraw = lambda: None

        editor._on_stroke_selected()

        self.assertEqual(editor.selected_stroke_indices, (0, 1))
        self.assertEqual(editor.thickness_scale_var.get(), "1.6")
        self.assertEqual(editor.start_cap_var.get(), "")
        self.assertEqual(editor.end_cap_var.get(), "flat")
        self.assertEqual(editor.filled_var.get(), "")

    def test_apply_stroke_properties_updates_all_selected_strokes_once(self) -> None:
        closed_centerline = [
            (0.0, 0.0),
            (2.0, 0.0),
            (1.0, 2.0),
            (0.0, 0.0),
        ]
        editor = object.__new__(SkeletonFontEditor)
        editor.root = object()
        editor.document = EditorDocument(
            strokes=[
                EditableStroke(centerline=closed_centerline.copy()),
                EditableStroke(centerline=closed_centerline.copy()),
            ]
        )
        editor.selected_stroke_indices = (0, 1)
        editor.thickness_scale_var = _FakeVariable("1.6")
        editor.start_cap_var = _FakeVariable("flat")
        editor.end_cap_var = _FakeVariable("flat")
        editor.filled_var = _FakeVariable("true")
        editor.status_var = _FakeVariable()
        undo_calls: list[bool] = []
        editor._record_undo = lambda: undo_calls.append(True)
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None

        applied = editor._apply_stroke_properties()

        self.assertTrue(applied)
        self.assertEqual(undo_calls, [True])
        for stroke in editor.document.strokes:
            self.assertEqual(stroke.thickness_scale, 1.6)
            self.assertEqual(stroke.start_cap, "flat")
            self.assertEqual(stroke.end_cap, "flat")
            self.assertTrue(stroke.filled)

    def test_blank_mixed_properties_are_not_applied_to_batch(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.root = object()
        editor.document = EditorDocument(
            strokes=[
                EditableStroke(
                    centerline=[(0.0, 0.0)],
                    start_cap="round",
                    end_cap="flat",
                    filled=False,
                ),
                EditableStroke(
                    centerline=[(1.0, 0.0)],
                    start_cap="flat",
                    end_cap="round",
                    filled=False,
                ),
            ]
        )
        editor.selected_stroke_indices = (0, 1)
        editor.thickness_scale_var = _FakeVariable("1.6")
        editor.start_cap_var = _FakeVariable("")
        editor.end_cap_var = _FakeVariable("")
        editor.filled_var = _FakeVariable("")
        editor.status_var = _FakeVariable()
        editor._record_undo = lambda: None
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None

        applied = editor._apply_stroke_properties()

        self.assertTrue(applied)
        self.assertEqual(
            [stroke.thickness_scale for stroke in editor.document.strokes],
            [1.6, 1.6],
        )
        self.assertEqual(
            [stroke.start_cap for stroke in editor.document.strokes],
            ["round", "flat"],
        )
        self.assertEqual(
            [stroke.end_cap for stroke in editor.document.strokes],
            ["flat", "round"],
        )

    def test_unnamed_document_can_start_drawing(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        focus_calls: list[bool] = []
        editor.canvas = SimpleNamespace(
            focus_set=lambda: focus_calls.append(True)
        )
        editor.document = EditorDocument()
        editor.draft_centerline = []
        editor.draft_start_cap = None
        editor.drawing_cap = "round"
        editor.selected_stroke_indices = (0,)
        editor.stroke_list = _FakeStrokeList()
        edit_widget = _FakeConfigWidget()
        editor._stroke_edit_widgets = [(edit_widget, "normal")]
        editor.status_var = _FakeVariable()
        editor._canvas_position_is_in_grid = lambda _x, _y: True
        editor._canvas_to_grid = lambda _x, _y: (2.0, 3.0)
        editor._record_undo = lambda: None
        editor._clear_stroke_fields = lambda: None
        editor._mark_dirty = lambda: None
        editor._redraw = lambda: None

        editor._on_canvas_left_click(SimpleNamespace(x=10, y=10))

        self.assertEqual(editor.draft_centerline, [(2.0, 3.0)])
        self.assertEqual(editor.document.name, "")
        self.assertEqual(editor.selected_stroke_indices, ())
        self.assertEqual(editor.stroke_list.state, "disabled")
        self.assertEqual(edit_widget.state, "disabled")
        self.assertEqual(focus_calls, [True, True])

    def test_first_save_prompts_for_an_unnamed_identity(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.root = object()
        editor.workspace = SimpleNamespace(
            identity_map=GlyphIdentityMap({"A": 0x41})
        )
        editor.active_source_directory = Path("target")
        editor.document = EditorDocument()
        editor.name_var = _FakeVariable("")
        prepared: list[bool] = []
        editor._prepare_document_for_save = (
            lambda *, resolve_identity=True: prepared.append(resolve_identity)
            or True
        )
        editor._request_glyph_identity = lambda **_kwargs: GlyphIdentity("A", 0x41)
        written: list[tuple[GlyphIdentity, Path, bool]] = []
        editor._write_document = lambda identity, target, *, confirm_overwrite: (
            written.append((identity, target, confirm_overwrite)) or True
        )

        self.assertTrue(editor._save_document())
        self.assertEqual(prepared, [False])
        self.assertEqual(
            written,
            [(GlyphIdentity("A", 0x41), Path("target/A_0041.json"), True)],
        )

    def test_glyph_rows_use_their_full_height(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.glyph_tree = _FakeGlyphBrowserTree(row_count=3)
        editor.glyph_tree.selection_set("row-2")
        editor._glyph_press_origin = None
        editor._glyph_press_item = None
        editor._glyph_pointer_mode = None
        editor._glyph_drag_active = False
        editor._glyph_drag_paths = ()
        editor._glyph_drop_target = None
        editor._glyph_preserve_selection_on_press = False
        editor._item_by_directory = {}
        editor._changing_glyph = False

        self.assertEqual(editor._glyph_item_at(12), "row-0")
        self.assertEqual(editor._glyph_item_at(23), "row-0")
        self.assertEqual(editor._glyph_item_at(24), "row-1")
        self.assertIsNone(editor._glyph_item_at(95))
        editor._on_glyph_tree_left_press(
            SimpleNamespace(x=150, y=95, state=0x0004)
        )
        editor._on_glyph_tree_drag(
            SimpleNamespace(x=20, y=40, x_root=20, y_root=40)
        )
        editor._on_glyph_tree_release(SimpleNamespace())
        self.assertEqual(editor.glyph_tree.selection(), ("row-2",))

        editor._on_glyph_tree_left_press(
            SimpleNamespace(x=150, y=95, state=0)
        )
        editor._on_glyph_tree_release(SimpleNamespace())
        self.assertEqual(editor.glyph_tree.selection(), ())

    def test_file_drag_indicator_follows_pointer_with_selection_count(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.glyph_tree = _FakeGlyphBrowserTree(row_count=2)
        editor.glyph_tree.selection_set("row-0", "row-1")
        editor._glyph_by_item = {
            "row-0": SimpleNamespace(path=Path("one.json")),
            "row-1": SimpleNamespace(path=Path("two.json")),
        }
        editor._glyph_press_origin = None
        editor._glyph_press_item = None
        editor._glyph_pointer_mode = None
        editor._glyph_drag_active = False
        editor._glyph_drag_paths = ()
        editor._glyph_drop_target = None
        editor._glyph_preserve_selection_on_press = False
        editor._item_by_directory = {}
        editor._changing_glyph = False
        indicators: list[tuple[int, int, int]] = []
        editor._hide_glyph_drag_indicator = lambda: None
        editor._update_glyph_drag_indicator = (
            lambda x, y, count: indicators.append((x, y, count))
        )
        editor._directory_at_pointer = lambda _x, _y: None
        editor._set_glyph_drop_target = lambda target: setattr(
            editor, "_glyph_drop_target", target
        )

        editor._on_glyph_tree_left_press(
            SimpleNamespace(x=20, y=12, state=0)
        )
        editor._on_glyph_tree_drag(
            SimpleNamespace(x=30, y=20, x_root=130, y_root=220)
        )

        self.assertEqual(indicators, [(130, 220, 2)])

    def test_nonempty_search_uses_global_index_and_directory_column(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.workspace = SourceWorkspace(PROJECT_DIRECTORY)
        editor.active_source_directory = (
            editor.workspace.source_root / "latin" / "upright_latin"
        )
        editor._all_glyph_entries = editor.workspace.all_glyphs()
        editor.glyph_tree = _FakeGlyphBrowserTree()
        editor._glyph_by_item = {}
        editor._changing_glyph = False
        editor.document = EditorDocument()
        editor.search_var = _FakeVariable("")

        editor._filter_glyph_list()
        self.assertTrue(editor._glyph_entries)
        self.assertEqual(
            {values[0] for values in editor.glyph_tree.values.values()},
            {"latin/upright_latin"},
        )

        editor.search_var = _FakeVariable(
            "math/delimiter_variants/vertical_variant_glyphs/paren"
        )
        editor._filter_glyph_list()
        self.assertTrue(editor._glyph_entries)
        directories = {
            values[0] for values in editor.glyph_tree.values.values()
        }
        self.assertIn(
            "math/delimiter_variants/vertical_variant_glyphs/paren",
            directories,
        )
        self.assertTrue(
            all(
                directory.startswith(
                    "math/delimiter_variants/vertical_variant_glyphs/paren"
                )
                for directory in directories
            )
        )

    def test_edit_mode_canvas_right_click_clears_stroke_selection(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.draft_centerline = []
        editor.stroke_list = _FakeStrokeList()
        editor.selected_stroke_indices = (0,)
        editor.status_var = _FakeVariable()
        editor._clear_stroke_fields = lambda: None
        editor._redraw = lambda: None

        editor._on_canvas_right_click()

        self.assertEqual(editor.selected_stroke_indices, ())
        self.assertEqual(editor.stroke_list.curselection(), ())

    def test_moving_open_dirty_glyph_updates_path_without_losing_edits(self) -> None:
        with TemporaryDirectory() as temporary:
            project = Path(temporary)
            source_directory = project / "glyph_sources" / "one"
            target_directory = project / "glyph_sources" / "target"
            source_directory.mkdir(parents=True)
            target_directory.mkdir()
            source = source_directory / "broken.json"
            source.write_text("not json", encoding="utf-8")
            editor = object.__new__(SkeletonFontEditor)
            editor.root = object()
            editor.workspace = SourceWorkspace(project)
            editor.document = EditorDocument(source_path=source, dirty=True)
            editor.status_var = _FakeVariable()
            refreshed: list[tuple[bool, tuple[Path, ...]]] = []
            editor._refresh_glyph_list = (
                lambda *, reload=False, selected_paths=(): refreshed.append(
                    (reload, selected_paths)
                )
            )
            editor._update_title = lambda: None

            with patch(
                "tools.skeletonfont_editor.app.messagebox.askyesno",
                return_value=True,
            ):
                result = editor._move_glyph_paths((source,), target_directory)

            destination = target_directory / "broken.json"
            self.assertTrue(result)
            self.assertEqual(editor.document.source_path, destination.resolve())
            self.assertTrue(editor.document.dirty)
            self.assertEqual(refreshed, [(True, (destination,))])

    def test_save_as_resolves_a_new_identity_and_filename(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.root = object()
        editor.workspace = SimpleNamespace(
            identity_map=GlyphIdentityMap(
                {"A": 0x41, "radical.v1": None}
            )
        )
        editor.active_source_directory = Path("target")
        editor.document = EditorDocument(
            name="A",
            codepoint=0x41,
            source_path=Path("source/A_0041.json"),
            locked_identity=("A", 0x41),
        )
        prepared_with: list[bool] = []

        def prepare_document_for_save(*, resolve_identity: bool = True) -> bool:
            prepared_with.append(resolve_identity)
            return True

        editor._prepare_document_for_save = prepare_document_for_save
        written: list[tuple[GlyphIdentity, Path, bool]] = []

        def write_document(
            identity: GlyphIdentity,
            target: Path,
            *,
            confirm_overwrite: bool,
        ) -> bool:
            written.append((identity, target, confirm_overwrite))
            return True

        editor._write_document = write_document
        with patch(
            "tools.skeletonfont_editor.app.simpledialog.askstring",
            return_value="radical.v1",
        ):
            result = editor._save_document_as()

        self.assertTrue(result)
        self.assertEqual(prepared_with, [False])
        self.assertEqual(
            written,
            [
                (
                    GlyphIdentity("radical.v1", None),
                    Path("target/radical.v1.json"),
                    True,
                )
            ],
        )

    def test_repeated_canvas_wheel_navigation_opens_each_target(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.glyph_tree = _FakeGlyphTree()
        editor._changing_glyph = False
        opened: list[str] = []
        def open_item(item: str) -> bool:
            opened.append(item)
            return True

        editor._open_glyph_item = open_item
        wheel_down = SimpleNamespace(delta=-120, num=None)

        editor._on_canvas_mouse_wheel(wheel_down)
        editor._on_canvas_mouse_wheel(wheel_down)
        editor._on_canvas_mouse_wheel(wheel_down)

        self.assertEqual(opened, ["first", "second", "third"])

    def test_cancelled_glyph_navigation_does_not_preselect_target(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        tree = _FakeGlyphTree()
        tree.selected = ("first",)
        editor.glyph_tree = tree
        editor._changing_glyph = False
        opened: list[str] = []

        def reject_item(item: str) -> bool:
            opened.append(item)
            return False

        editor._open_glyph_item = reject_item

        editor._navigate_glyph(1)

        self.assertEqual(opened, ["second"])
        self.assertEqual(tree.selection(), ("first",))

    def test_clicking_stroke_list_blank_space_clears_selection(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.stroke_list = _FakeStrokeList()
        selection_updates: list[bool] = []
        editor._on_stroke_selected = lambda: selection_updates.append(True)

        result = editor._on_stroke_list_left_click(
            SimpleNamespace(x=150, y=25)
        )

        self.assertEqual(result, "break")
        self.assertEqual(editor.stroke_list.selected, ())
        self.assertEqual(selection_updates, [True])

    def test_clicking_stroke_item_allows_normal_listbox_selection(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.stroke_list = _FakeStrokeList()

        result = editor._on_stroke_list_left_click(
            SimpleNamespace(x=20, y=25)
        )

        self.assertIsNone(result)
        self.assertEqual(editor.stroke_list.selected, (0,))

    def test_mixed_caps_become_round_then_toggle_together(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.document = EditorDocument(
            strokes=[
                EditableStroke(centerline=[(0.0, 0.0)], start_cap="round"),
                EditableStroke(centerline=[(1.0, 0.0)], start_cap="flat"),
            ]
        )
        editor.selected_stroke_indices = (0, 1)
        editor.status_var = _FakeVariable()
        editor._record_undo = lambda: None
        editor._mark_dirty = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None
        event = SimpleNamespace(widget=object())

        editor._toggle_selected_cap(event, "start")
        self.assertEqual(
            [stroke.start_cap for stroke in editor.document.strokes],
            ["round", "round"],
        )

        editor._toggle_selected_cap(event, "start")
        self.assertEqual(
            [stroke.start_cap for stroke in editor.document.strokes],
            ["flat", "flat"],
        )

    def test_edited_strokes_move_to_end_preserving_their_order(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.document = EditorDocument(
            strokes=[
                EditableStroke(centerline=[(0.0, 0.0)]),
                EditableStroke(centerline=[(1.0, 0.0)]),
                EditableStroke(centerline=[(2.0, 0.0)]),
                EditableStroke(centerline=[(3.0, 0.0)]),
            ]
        )
        editor.selected_stroke_indices = (0, 2)

        moved = editor._move_selected_strokes_to_end()

        self.assertTrue(moved)
        self.assertEqual(
            [stroke.centerline[0][0] for stroke in editor.document.strokes],
            [1.0, 3.0, 0.0, 2.0],
        )
        self.assertEqual(editor.selected_stroke_indices, (2, 3))

    def test_strokes_can_be_reordered_as_a_selected_block(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.document = EditorDocument(
            strokes=[
                EditableStroke(centerline=[(0.0, 0.0)]),
                EditableStroke(centerline=[(1.0, 0.0)]),
                EditableStroke(centerline=[(2.0, 0.0)]),
                EditableStroke(centerline=[(3.0, 0.0)]),
            ]
        )
        editor.selected_stroke_indices = (1, 2)
        editor.status_var = _FakeVariable()
        undo_calls: list[bool] = []
        editor._record_undo = lambda: undo_calls.append(True)
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None

        reordered = editor._reorder_selected_strokes(0)

        self.assertTrue(reordered)
        self.assertEqual(undo_calls, [True])
        self.assertEqual(
            [stroke.centerline[0][0] for stroke in editor.document.strokes],
            [1.0, 2.0, 0.0, 3.0],
        )
        self.assertEqual(editor.selected_stroke_indices, (0, 1))

    def test_stroke_drag_release_applies_the_drop_position(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor._stroke_drag_press_index = 1
        editor._stroke_drag_press_y = 20
        editor._stroke_drag_active = True
        editor._stroke_drag_target_index = 0
        editor._stroke_preserve_selection_on_press = True
        drops: list[int] = []
        editor._reorder_selected_strokes = (
            lambda index: (drops.append(index), True)[1]
        )

        result = editor._on_stroke_list_release(SimpleNamespace())

        self.assertEqual(result, "break")
        self.assertEqual(drops, [0])
        self.assertFalse(editor._stroke_drag_active)
        self.assertIsNone(editor._stroke_drag_target_index)

    def test_mixed_scales_become_one_then_toggle_together(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.document = EditorDocument(
            strokes=[
                EditableStroke(
                    centerline=[(0.0, 0.0)], thickness_scale=1.0
                ),
                EditableStroke(
                    centerline=[(1.0, 0.0)], thickness_scale=1.6
                ),
            ]
        )
        editor.selected_stroke_indices = (0, 1)
        editor.status_var = _FakeVariable()
        editor._record_undo = lambda: None
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None
        event = SimpleNamespace(widget=object())

        editor._toggle_selected_scale(event)
        self.assertEqual(
            [stroke.thickness_scale for stroke in editor.document.strokes],
            [1.0, 1.0],
        )

        editor._toggle_selected_scale(event)
        self.assertEqual(
            [stroke.thickness_scale for stroke in editor.document.strokes],
            [1.6, 1.6],
        )

        editor._toggle_selected_scale(event)
        self.assertEqual(
            [stroke.thickness_scale for stroke in editor.document.strokes],
            [1.0, 1.0],
        )

    def test_copy_and_paste_multiple_strokes_at_mouse_origin(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.root = _FakeClipboardRoot()
        editor.document = EditorDocument(
            monospace_x_offset=3.0,
            y_offset=-2.0,
            strokes=[
                EditableStroke(
                    centerline=[(2.0, 3.0), (4.0, 3.0)],
                    thickness_scale=1.6,
                    start_cap="flat",
                ),
                EditableStroke(centerline=[(20.0, 20.0)]),
                EditableStroke(
                    centerline=[(3.0, 5.0), (3.0, 6.0)],
                    end_cap="flat",
                ),
            ],
        )
        editor.draft_centerline = []
        editor.selected_stroke_indices = (0, 2)
        editor.hover_grid_point = (7.0, 8.0)
        editor.status_var = _FakeVariable()
        editor._record_undo = lambda: None
        editor._update_computed_offsets = lambda: None
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None
        event = SimpleNamespace(widget=object())

        editor._copy_selected_stroke(event)
        editor._paste_stroke(event)

        self.assertEqual(len(editor.document.strokes), 5)
        self.assertEqual(editor.selected_stroke_indices, (3, 4))
        pasted = editor.document.strokes[3:]
        self.assertEqual(
            [
                [editor.document.display_point(point) for point in stroke.centerline]
                for stroke in pasted
            ],
            [
                [(7.0, 8.0), (9.0, 8.0)],
                [(8.0, 10.0), (8.0, 11.0)],
            ],
        )
        self.assertEqual(pasted[0].thickness_scale, 1.6)
        self.assertEqual(pasted[0].start_cap, "flat")
        self.assertEqual(pasted[1].end_cap, "flat")

    def test_paste_accepts_legacy_single_stroke_clipboard_format(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.root = _FakeClipboardRoot()
        editor.root.text = (
            '{"type":"skeletonfont-centerline","stroke":'
            '{"centerline":[[4,3],[5,3]]}}'
        )
        editor.document = EditorDocument()
        editor.draft_centerline = []
        editor.selected_stroke_indices = ()
        editor.hover_grid_point = (-2.0, 1.0)
        editor.status_var = _FakeVariable()
        editor._record_undo = lambda: None
        editor._update_computed_offsets = lambda: None
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None

        editor._paste_stroke(SimpleNamespace(widget=object()))

        pasted = editor.document.strokes[0]
        self.assertEqual(
            [editor.document.display_point(point) for point in pasted.centerline],
            [(-2.0, 1.0), (-1.0, 1.0)],
        )
        self.assertEqual(editor.selected_stroke_indices, (0,))

    def test_wasd_moves_only_selected_strokes(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.document = EditorDocument(
            strokes=[
                EditableStroke(centerline=[(0.0, 0.0), (1.0, 0.0)]),
                EditableStroke(centerline=[(10.0, 0.0), (11.0, 0.0)]),
            ]
        )
        editor.draft_centerline = []
        editor.selected_stroke_indices = (0,)
        editor._record_undo = lambda: None
        editor._update_computed_offsets = lambda: None
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None
        before_unselected = [
            editor.document.display_point(point)
            for point in editor.document.strokes[1].centerline
        ]

        editor.status_var = _FakeVariable()
        editor._move_selected_strokes(SimpleNamespace(widget=object()), 1, 0)

        selected = [
            editor.document.display_point(point)
            for point in editor.document.strokes[1].centerline
        ]
        unselected = [
            editor.document.display_point(point)
            for point in editor.document.strokes[0].centerline
        ]
        self.assertEqual(selected, [(1.0, 0.0), (2.0, 0.0)])
        self.assertEqual(unselected, before_unselected)
        self.assertEqual(editor.selected_stroke_indices, (1,))

    def test_deleting_finished_stroke_preserves_active_draft_position(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.document = EditorDocument(
            monospace_x_offset=5.0,
            y_offset=5.0,
            strokes=[
                EditableStroke(centerline=[(0.0, 0.0)]),
                EditableStroke(centerline=[(10.0, 10.0)]),
            ],
        )
        editor.draft_centerline = [(2.0, 3.0), (3.0, 4.0)]
        editor.draft_start_cap = "round"
        editor.selected_stroke_indices = (0,)
        editor._record_undo = lambda: None
        editor._update_computed_offsets = lambda: None
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._clear_stroke_fields = lambda: None
        editor._redraw = lambda: None
        before = [
            editor.document.display_point(point)
            for point in editor.draft_centerline
        ]

        editor._delete_selected_stroke()

        after = [
            editor.document.display_point(point)
            for point in editor.draft_centerline
        ]
        self.assertEqual(after, before)

    def test_flat_caps_are_red_squares_and_completed_points_match_line(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.canvas = _FakeCanvas()
        editor.document = EditorDocument()
        editor._grid_to_canvas = lambda point: point

        editor._draw_centerline(
            [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)],
            color="#2459c4",
            width=2,
            filled=False,
            start_cap="flat",
            end_cap="flat",
        )

        self.assertEqual(len(editor.canvas.rectangles), 2)
        self.assertEqual(len(editor.canvas.ovals), 1)
        self.assertEqual(editor.canvas.rectangles[0][-1]["fill"], "#d62828")
        self.assertEqual(editor.canvas.ovals[0][-1]["fill"], "#2459c4")

    def test_draft_end_uses_black_shape_for_current_cap_mode(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.canvas = _FakeCanvas()
        editor.document = EditorDocument()
        editor._grid_to_canvas = lambda point: point

        editor._draw_centerline(
            [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)],
            color="#222222",
            width=2,
            filled=False,
            start_cap="flat",
            end_cap="flat",
            finalized=False,
        )

        self.assertEqual(len(editor.canvas.rectangles), 2)
        self.assertEqual(len(editor.canvas.ovals), 1)
        self.assertEqual(editor.canvas.rectangles[0][-1]["fill"], "#d62828")
        self.assertEqual(editor.canvas.rectangles[1][-1]["fill"], "#222222")
        self.assertTrue(
            all(oval[-1]["fill"] == "#222222" for oval in editor.canvas.ovals)
        )

    def test_switching_to_flat_mode_does_not_restyle_round_start(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.canvas = _FakeCanvas()
        editor.document = EditorDocument()
        editor._grid_to_canvas = lambda point: point

        editor._draw_centerline(
            [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)],
            color="#222222",
            width=2,
            filled=False,
            start_cap="round",
            end_cap="flat",
            finalized=False,
        )

        self.assertEqual(len(editor.canvas.rectangles), 1)
        self.assertEqual(editor.canvas.rectangles[0][-1]["fill"], "#222222")
        self.assertEqual(len(editor.canvas.ovals), 2)

    def test_hover_shape_follows_current_drawing_mode(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.canvas = _FakeCanvas()
        editor._grid_to_canvas = lambda point: point

        editor.drawing_cap = "flat"
        editor._draw_hover_indicator((1.0, 2.0))
        self.assertEqual(len(editor.canvas.rectangles), 1)
        self.assertEqual(editor.canvas.ovals, [])

        editor.canvas = _FakeCanvas()
        editor.drawing_cap = "round"
        editor._draw_hover_indicator((1.0, 2.0))
        self.assertEqual(editor.canvas.rectangles, [])
        self.assertEqual(len(editor.canvas.ovals), 1)

    def test_round_mode_keeps_circular_points_with_centerline_color(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.canvas = _FakeCanvas()
        editor.document = EditorDocument()
        editor._grid_to_canvas = lambda point: point

        editor._draw_centerline(
            [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)],
            color="#2459c4",
            width=2,
            filled=False,
            start_cap="round",
            end_cap="round",
        )

        self.assertEqual(editor.canvas.rectangles, [])
        self.assertEqual(len(editor.canvas.ovals), 3)
        self.assertTrue(
            all(oval[-1]["fill"] == "#2459c4" for oval in editor.canvas.ovals)
        )

    def test_finish_uses_stored_start_and_current_mode_for_end_cap(self) -> None:
        editor = object.__new__(SkeletonFontEditor)
        editor.document = EditorDocument()
        editor.draft_centerline = [(0.0, 0.0), (1.0, 1.0)]
        editor.draft_start_cap = "round"
        editor.drawing_cap = "flat"
        editor.selected_stroke_indices = ()
        editor.x_extent_var = _FakeVariable()
        editor.status_var = _FakeVariable()
        editor._loading_fields = False
        editor._record_undo = lambda: None
        editor._update_computed_offsets = lambda: None
        editor._mark_dirty = lambda: None
        editor._refresh_stroke_list = lambda: None
        editor._on_stroke_selected = lambda: None
        editor._redraw = lambda: None
        editor.stroke_list = _FakeStrokeList()
        editor._stroke_edit_widgets = []
        editor._clear_stroke_fields = lambda: None

        editor._finish_draft_centerline()

        self.assertEqual(len(editor.document.strokes), 1)
        self.assertEqual(editor.document.strokes[0].start_cap, "round")
        self.assertEqual(editor.document.strokes[0].end_cap, "flat")
        self.assertIsNone(editor.draft_start_cap)
        self.assertEqual(editor.selected_stroke_indices, (0,))


if __name__ == "__main__":
    unittest.main()
