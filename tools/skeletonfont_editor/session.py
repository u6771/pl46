from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable, TypeAlias

from skeletonfont.model import CapStyle, Point

from .document import EditorDocument


@dataclass(slots=True)
class Editing:
    """The editor is inspecting one or more completed strokes."""

    selection: tuple[int, ...] = ()


@dataclass(slots=True)
class Drawing:
    """The editor is collecting points for one unfinished stroke."""

    centerline: list[Point] = field(default_factory=list)
    start_cap: CapStyle = "round"


InteractionState: TypeAlias = Editing | Drawing


@dataclass(slots=True)
class SessionSnapshot:
    document: EditorDocument
    interaction: InteractionState


def _document_content(document: EditorDocument) -> tuple[object, ...]:
    """Return only state that is persisted in a glyph-source file."""

    return (
        document.name,
        document.codepoint,
        document.monospace_x_offset,
        document.y_offset,
        document.x_extent,
        tuple(
            (
                tuple(stroke.centerline),
                stroke.thickness_scale,
                stroke.start_cap,
                stroke.end_cap,
                stroke.filled,
            )
            for stroke in document.strokes
        ),
    )


class EditorSession:
    """Headless editing state, history, and saved-content tracking."""

    HISTORY_LIMIT = 200

    def __init__(self, document: EditorDocument | None = None) -> None:
        self.document = document if document is not None else EditorDocument()
        self.interaction: InteractionState = Editing()
        self._undo_stack: list[SessionSnapshot] = []
        self._redo_stack: list[SessionSnapshot] = []
        self._saved_content = _document_content(self.document)
        self._sync_dirty_flag()

    @property
    def is_drawing(self) -> bool:
        return isinstance(self.interaction, Drawing)

    @property
    def selection(self) -> tuple[int, ...]:
        if isinstance(self.interaction, Editing):
            return self.interaction.selection
        return ()

    @selection.setter
    def selection(self, indices: tuple[int, ...]) -> None:
        if isinstance(self.interaction, Drawing):
            if indices:
                raise RuntimeError("Cannot select completed strokes while drawing.")
            return
        count = len(self.document.strokes)
        self.interaction.selection = tuple(
            sorted({index for index in indices if 0 <= index < count})
        )

    @property
    def draft(self) -> Drawing | None:
        return self.interaction if isinstance(self.interaction, Drawing) else None

    @property
    def dirty(self) -> bool:
        return self.is_drawing or _document_content(self.document) != self._saved_content

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def load(self, document: EditorDocument) -> None:
        self.document = document
        self.interaction = Editing()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._saved_content = _document_content(document)
        self._sync_dirty_flag()

    def mark_saved(self) -> None:
        self._saved_content = _document_content(self.document)
        self._sync_dirty_flag()

    def sync_dirty(self) -> None:
        """Refresh the compatibility dirty flag after an external mutation."""

        self._sync_dirty_flag()

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            document=copy.deepcopy(self.document),
            interaction=copy.deepcopy(self.interaction),
        )

    def record_undo(self) -> None:
        self._push_undo(self.snapshot())
        self._redo_stack.clear()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self.snapshot())
        self._restore(self._undo_stack.pop())
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._push_undo(self.snapshot())
        self._restore(self._redo_stack.pop())
        return True

    def restore_snapshot(self, snapshot: SessionSnapshot) -> None:
        self._restore(snapshot)

    def apply(self, mutation: Callable[[EditorSession], None]) -> bool:
        """Apply one mutation as one undo command, if it changes session state."""

        before = self.snapshot()
        mutation(self)
        self._sanitize_selection()
        if self._matches(before):
            self._sync_dirty_flag()
            return False
        self._push_undo(before)
        self._redo_stack.clear()
        self._sync_dirty_flag()
        return True

    def begin_draft(self, point: Point, start_cap: CapStyle) -> None:
        if self.is_drawing:
            raise RuntimeError("A draft is already active.")
        self.interaction = Drawing([point], start_cap)
        self._sync_dirty_flag()

    def append_draft_point(self, point: Point) -> bool:
        draft = self.draft
        if draft is None:
            raise RuntimeError("No draft is active.")
        if draft.centerline and point == draft.centerline[-1]:
            return False
        draft.centerline.append(point)
        self._sync_dirty_flag()
        return True

    def cancel_draft(self) -> bool:
        if not self.is_drawing:
            return False
        self.interaction = Editing()
        self._sync_dirty_flag()
        return True

    def normalize_skeleton_preserving_draft(self) -> None:
        draft = self.draft
        draft_display_points = (
            [self.document.display_point(point) for point in draft.centerline]
            if draft is not None
            else []
        )
        self.document.normalize_skeleton()
        if draft is not None:
            draft.centerline[:] = [
                self.document.stored_point(point) for point in draft_display_points
            ]
        self._sync_dirty_flag()

    def _push_undo(self, snapshot: SessionSnapshot) -> None:
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self.HISTORY_LIMIT:
            del self._undo_stack[0]

    def _restore(self, snapshot: SessionSnapshot) -> None:
        self.document = copy.deepcopy(snapshot.document)
        self.interaction = copy.deepcopy(snapshot.interaction)
        self._sanitize_selection()
        self._sync_dirty_flag()

    def _matches(self, snapshot: SessionSnapshot) -> bool:
        return (
            _document_content(self.document) == _document_content(snapshot.document)
            and self.interaction == snapshot.interaction
        )

    def _sanitize_selection(self) -> None:
        if isinstance(self.interaction, Editing):
            self.selection = self.interaction.selection

    def _sync_dirty_flag(self) -> None:
        self.document.dirty = self.dirty
