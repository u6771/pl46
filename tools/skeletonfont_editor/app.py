from __future__ import annotations

import copy
import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Callable, Literal

from skeletonfont.errors import ProjectDataError
from skeletonfont.glyph_source_io import write_glyph_source
from skeletonfont.loader import parse_stroke_record
from skeletonfont.model import CapStyle

from .document import (
    EditableStroke,
    EditorDocument,
    format_codepoint,
    glyph_filename,
    parse_number,
)
from .identity import GlyphIdentity
from .session import Drawing, Editing, EditorSession, SessionSnapshot
from .workspace import GlyphFileEntry, SourceWorkspace
from .settings import (
    SHORTCUT_ACTIONS,
    EditorSettings,
    format_guide_values,
    load_editor_settings,
    parse_guide_values,
    save_editor_settings,
    shortcut_sequences,
    validate_shortcuts,
)

class SkeletonFontEditor:
    GRID_X_MIN = -12
    GRID_X_MAX = 12
    GRID_Y_MIN = -10
    GRID_Y_MAX = 14
    CELL_SIZE = 40

    @property
    def document(self) -> EditorDocument:
        session = getattr(self, "_session", None)
        if session is not None:
            return session.document
        return self.__dict__["_document"]

    @document.setter
    def document(self, document: EditorDocument) -> None:
        session = getattr(self, "_session", None)
        if session is not None:
            session.document = document
            session.sync_dirty()
        else:
            self.__dict__["_document"] = document

    @property
    def draft_centerline(self) -> list[tuple[float, float]]:
        session = getattr(self, "_session", None)
        if session is not None:
            draft = session.draft
            return [] if draft is None else draft.centerline
        return self.__dict__.setdefault("_draft_centerline", [])

    @draft_centerline.setter
    def draft_centerline(self, centerline: list[tuple[float, float]]) -> None:
        session = getattr(self, "_session", None)
        if session is None:
            self.__dict__["_draft_centerline"] = centerline
            return
        if centerline:
            draft = session.draft
            if draft is None:
                session.interaction = Drawing(list(centerline), "round")
            else:
                draft.centerline[:] = centerline
        else:
            session.interaction = Editing()
        session.sync_dirty()

    @property
    def draft_start_cap(self) -> CapStyle | None:
        session = getattr(self, "_session", None)
        if session is not None:
            draft = session.draft
            return None if draft is None else draft.start_cap
        return self.__dict__.get("_draft_start_cap")

    @draft_start_cap.setter
    def draft_start_cap(self, cap: CapStyle | None) -> None:
        session = getattr(self, "_session", None)
        if session is None:
            self.__dict__["_draft_start_cap"] = cap
            return
        draft = session.draft
        if draft is not None and cap is not None:
            draft.start_cap = cap

    @property
    def selected_stroke_indices(self) -> tuple[int, ...]:
        session = getattr(self, "_session", None)
        if session is not None:
            return session.selection
        return self.__dict__.get("_selected_stroke_indices", ())

    @selected_stroke_indices.setter
    def selected_stroke_indices(self, indices: tuple[int, ...]) -> None:
        session = getattr(self, "_session", None)
        if session is not None:
            session.selection = indices
        else:
            self.__dict__["_selected_stroke_indices"] = indices

    def __init__(self, root: tk.Tk, project_directory: Path) -> None:
        self.root = root
        self.workspace = SourceWorkspace(project_directory)
        self.settings = load_editor_settings()
        self.active_source_directory = self.workspace.source_root
        self._session = EditorSession()
        self.drawing_cap: CapStyle = "round"
        self.hover_grid_point: tuple[float, float] | None = None
        self._stroke_drag_press_index: int | None = None
        self._stroke_drag_press_y: int | None = None
        self._stroke_drag_active = False
        self._stroke_drag_target_index: int | None = None
        self._stroke_preserve_selection_on_press = False
        self._loading_fields = False
        self._glyph_fields_pending = False
        self._loading_stroke_fields = False
        self._stroke_fields_pending = False
        self._changing_directory = False
        self._changing_glyph = False
        self._directory_by_item: dict[str, Path] = {}
        self._item_by_directory: dict[Path, str] = {}
        self._glyph_by_item: dict[str, GlyphFileEntry] = {}
        self._glyph_entries: tuple[GlyphFileEntry, ...] = ()
        self._all_glyph_entries: tuple[GlyphFileEntry, ...] = ()
        self._glyph_press_origin: tuple[int, int] | None = None
        self._glyph_press_item: str | None = None
        self._glyph_pointer_mode: str | None = None
        self._glyph_drag_active = False
        self._glyph_drag_paths: tuple[Path, ...] = ()
        self._glyph_drop_target: Path | None = None
        self._glyph_preserve_selection_on_press = False
        self._glyph_drag_indicator: tk.Toplevel | None = None
        self._glyph_drag_indicator_canvas: tk.Canvas | None = None
        self._bound_shortcut_sequences: set[str] = set()

        self.name_var = tk.StringVar()
        self.unicode_var = tk.StringVar()
        self.monospace_x_offset_var = tk.StringVar(value="0")
        self.y_offset_var = tk.StringVar(value="0")
        self.x_extent_var = tk.StringVar()
        self.thickness_scale_var = tk.StringVar(value="1")
        self.start_cap_var = tk.StringVar(value="round")
        self.end_cap_var = tk.StringVar(value="round")
        self.filled_var = tk.StringVar(value="false")
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar()

        self._build_ui()
        self._bind_events()
        self._build_directory_tree()
        self._load_document(EditorDocument())
        self._select_directory(self.workspace.source_root, clear_document=False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.root.title("SkeletonFont Glyph Editor")
        self.root.minsize(1100, 720)

        toolbar = ttk.Frame(self.root, padding=(8, 8, 8, 5))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="New", command=self._new_document).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="Save", command=self._save_document).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="Save As", command=self._save_document_as).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="Refresh", command=self._refresh_workspace).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="Settings", command=self._open_settings).pack(
            side="left", padx=3
        )
        ttk.Label(
            toolbar,
            text=(
                "Left click: add centerline point   Right click/Enter: finish   "
                "Escape: cancel draft"
            ),
        ).pack(side="right")

        panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 5))

        browser = ttk.Frame(panes, padding=5, width=260)
        browser.rowconfigure(1, weight=2)
        browser.rowconfigure(4, weight=3)
        browser.columnconfigure(0, weight=1)
        panes.add(browser, weight=1)

        ttk.Label(browser, text="Source directories").grid(
            row=0, column=0, sticky="w", pady=(0, 3)
        )
        self.directory_tree = ttk.Treeview(browser, show="tree", selectmode="browse")
        self.directory_tree.grid(row=1, column=0, sticky="nsew")

        ttk.Label(browser, text="Glyph browser").grid(
            row=2, column=0, sticky="w", pady=(8, 3)
        )
        ttk.Entry(browser, textvariable=self.search_var).grid(
            row=3, column=0, sticky="ew", pady=(0, 3)
        )
        self.glyph_tree = ttk.Treeview(
            browser,
            columns=("directory", "glyph", "unicode"),
            show="headings",
            selectmode="extended",
        )
        self.glyph_tree.heading("directory", text="Directory")
        self.glyph_tree.heading("glyph", text="Glyph")
        self.glyph_tree.heading("unicode", text="Unicode")
        self.glyph_tree.column("directory", width=115, stretch=True)
        self.glyph_tree.column("glyph", width=135, stretch=True)
        self.glyph_tree.column("unicode", width=75, stretch=False)
        self.glyph_tree.grid(row=4, column=0, sticky="nsew")
        glyph_scrollbar = ttk.Scrollbar(
            browser,
            orient="vertical",
            command=self.glyph_tree.yview,
        )
        glyph_scrollbar.grid(row=4, column=1, sticky="ns")
        self.glyph_tree.configure(yscrollcommand=glyph_scrollbar.set)
        self.directory_tree.tag_configure("drop-target", background="#cfe3ff")

        canvas_frame = ttk.Frame(panes, padding=5)
        panes.add(canvas_frame, weight=4)
        self.canvas = tk.Canvas(
            canvas_frame,
            background="#f7f7f7",
            highlightthickness=1,
            highlightbackground="#999999",
            takefocus=True,
        )
        self.canvas.pack(fill="both", expand=True)

        inspector = ttk.Frame(panes, padding=8, width=270)
        inspector.columnconfigure(1, weight=1)
        inspector.rowconfigure(8, weight=1)
        panes.add(inspector, weight=1)

        ttk.Label(inspector, text="Glyph", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 5)
        )
        self.name_entry = self._field(inspector, 1, "Name", self.name_var)
        ttk.Label(inspector, text="Unicode").grid(row=2, column=0, sticky="w")
        ttk.Label(
            inspector,
            textvariable=self.unicode_var,
            anchor="e",
        ).grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Label(inspector, text="Mono x offset").grid(row=3, column=0, sticky="w")
        ttk.Label(
            inspector,
            textvariable=self.monospace_x_offset_var,
            anchor="e",
        ).grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Label(inspector, text="Y offset").grid(row=4, column=0, sticky="w")
        ttk.Label(
            inspector,
            textvariable=self.y_offset_var,
            anchor="e",
        ).grid(row=4, column=1, sticky="ew", pady=2)
        self._field(inspector, 5, "X extent", self.x_extent_var)
        ttk.Button(
            inspector,
            text="Apply glyph fields",
            command=self._apply_glyph_fields,
        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 10))

        ttk.Label(
            inspector, text="Strokes", font=("TkDefaultFont", 10, "bold")
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self.stroke_list = tk.Listbox(
            inspector,
            exportselection=False,
            height=8,
            selectmode=tk.EXTENDED,
        )
        self.stroke_list.grid(row=8, column=0, columnspan=2, sticky="nsew")
        stroke_buttons = ttk.Frame(inspector)
        stroke_buttons.grid(row=9, column=0, columnspan=2, sticky="ew", pady=4)
        self._stroke_edit_widgets: list[tuple[tk.Widget, str]] = []
        for text, command in (
            ("Delete", self._delete_selected_stroke),
            ("Reverse", self._reverse_selected_stroke),
            ("Open/close", self._toggle_selected_stroke_closed),
        ):
            button = ttk.Button(stroke_buttons, text=text, command=command)
            button.pack(side="left", padx=2)
            self._stroke_edit_widgets.append((button, "normal"))

        thickness_entry = self._field(
            inspector, 10, "Thickness scale", self.thickness_scale_var
        )
        self._stroke_edit_widgets.append((thickness_entry, "normal"))
        ttk.Label(inspector, text="Start cap").grid(row=11, column=0, sticky="w")
        start_cap_box = ttk.Combobox(
            inspector,
            textvariable=self.start_cap_var,
            values=("round", "flat"),
            state="readonly",
        )
        start_cap_box.grid(row=11, column=1, sticky="ew", pady=2)
        self._stroke_edit_widgets.append((start_cap_box, "readonly"))
        ttk.Label(inspector, text="End cap").grid(row=12, column=0, sticky="w")
        end_cap_box = ttk.Combobox(
            inspector,
            textvariable=self.end_cap_var,
            values=("round", "flat"),
            state="readonly",
        )
        end_cap_box.grid(row=12, column=1, sticky="ew", pady=2)
        self._stroke_edit_widgets.append((end_cap_box, "readonly"))
        self.filled_check = ttk.Checkbutton(
            inspector,
            text="Filled",
            variable=self.filled_var,
            onvalue="true",
            offvalue="false",
        )
        self.filled_check.grid(
            row=13, column=0, columnspan=2, sticky="w", pady=2
        )
        self._stroke_edit_widgets.append((self.filled_check, "normal"))
        apply_stroke_button = ttk.Button(
            inspector,
            text="Apply stroke properties",
            command=self._apply_stroke_properties,
        )
        apply_stroke_button.grid(
            row=14, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        self._stroke_edit_widgets.append((apply_stroke_button, "normal"))

        ttk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            padding=(8, 3, 8, 7),
        ).pack(fill="x")

    @staticmethod
    def _field(
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.Variable,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        return entry

    def _open_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Editor settings")
        window.geometry("560x700")
        window.transient(self.root)

        notebook = ttk.Notebook(window)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        guide_tab = ttk.Frame(notebook, padding=12)
        guide_tab.columnconfigure(1, weight=1)
        notebook.add(guide_tab, text="Grid")
        guide_x_var = tk.StringVar(
            value=format_guide_values(self.settings.guide_x)
        )
        guide_y_var = tk.StringVar(
            value=format_guide_values(self.settings.guide_y)
        )
        ttk.Label(guide_tab, text="Guide X").grid(row=0, column=0, sticky="w")
        ttk.Entry(guide_tab, textvariable=guide_x_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 0), pady=3
        )
        ttk.Label(guide_tab, text="Guide Y").grid(row=1, column=0, sticky="w")
        ttk.Entry(guide_tab, textvariable=guide_y_var).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=3
        )
        ttk.Label(
            guide_tab,
            text="Enter comma-separated grid coordinates, for example: 0, 6, 10",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        shortcut_tab = ttk.Frame(notebook)
        notebook.add(shortcut_tab, text="Shortcuts")
        shortcut_canvas = tk.Canvas(shortcut_tab, highlightthickness=0)
        shortcut_scrollbar = ttk.Scrollbar(
            shortcut_tab, orient="vertical", command=shortcut_canvas.yview
        )
        shortcut_canvas.configure(yscrollcommand=shortcut_scrollbar.set)
        shortcut_canvas.pack(side="left", fill="both", expand=True)
        shortcut_scrollbar.pack(side="right", fill="y")
        shortcut_frame = ttk.Frame(shortcut_canvas, padding=10)
        shortcut_window = shortcut_canvas.create_window(
            (0, 0), window=shortcut_frame, anchor="nw"
        )
        shortcut_frame.bind(
            "<Configure>",
            lambda _event: shortcut_canvas.configure(
                scrollregion=shortcut_canvas.bbox("all")
            ),
        )
        shortcut_canvas.bind(
            "<Configure>",
            lambda event: shortcut_canvas.itemconfigure(
                shortcut_window, width=event.width
            ),
        )
        shortcut_frame.columnconfigure(1, weight=1)
        shortcut_vars: dict[str, tk.StringVar] = {}
        for row, (action, label) in enumerate(SHORTCUT_ACTIONS):
            variable = tk.StringVar(value=self.settings.shortcuts[action])
            shortcut_vars[action] = variable
            ttk.Label(shortcut_frame, text=label).grid(
                row=row, column=0, sticky="w", pady=2
            )
            ttk.Entry(shortcut_frame, textvariable=variable).grid(
                row=row, column=1, sticky="ew", padx=(10, 0), pady=2
            )

        buttons = ttk.Frame(window, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")

        def save_settings() -> None:
            try:
                shortcuts = {
                    action: variable.get().strip()
                    for action, variable in shortcut_vars.items()
                }
                validate_shortcuts(shortcuts)
                settings = EditorSettings(
                    guide_x=parse_guide_values(guide_x_var.get()),
                    guide_y=parse_guide_values(guide_y_var.get()),
                    shortcuts=shortcuts,
                )
                path = save_editor_settings(settings)
            except (OSError, ValueError) as error:
                messagebox.showerror(
                    "Invalid settings", str(error), parent=window
                )
                return
            self.settings = settings
            self._bind_shortcuts()
            self._redraw()
            self.status_var.set(f"Saved editor settings to {path.name}.")
            window.destroy()

        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(
            side="right", padx=3
        )
        ttk.Button(buttons, text="Save", command=save_settings).pack(
            side="right", padx=3
        )

    def _bind_events(self) -> None:
        self.directory_tree.bind(
            "<<TreeviewSelect>>", self._on_directory_tree_selected
        )
        self.glyph_tree.bind(
            "<<TreeviewSelect>>", self._on_glyph_tree_selected
        )
        self.glyph_tree.bind("<ButtonPress-1>", self._on_glyph_tree_left_press)
        self.glyph_tree.bind("<B1-Motion>", self._on_glyph_tree_drag)
        self.glyph_tree.bind("<ButtonRelease-1>", self._on_glyph_tree_release)
        self.stroke_list.bind("<<ListboxSelect>>", self._on_stroke_selected)
        self.stroke_list.bind("<ButtonPress-1>", self._on_stroke_list_left_click)
        self.stroke_list.bind("<B1-Motion>", self._on_stroke_list_drag)
        self.stroke_list.bind("<ButtonRelease-1>", self._on_stroke_list_release)
        self.canvas.bind("<Button-1>", self._on_canvas_left_click)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click)
        self.canvas.bind("<Button-2>", self._on_canvas_right_click)
        self.canvas.bind("<MouseWheel>", self._on_canvas_mouse_wheel)
        self.canvas.bind("<Button-4>", self._on_canvas_mouse_wheel)
        self.canvas.bind("<Button-5>", self._on_canvas_mouse_wheel)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        self.search_var.trace_add("write", lambda *_args: self._filter_glyph_list())
        self._bind_shortcuts()
        self.name_var.trace_add("write", self._on_glyph_name_changed)
        self.x_extent_var.trace_add("write", self._on_glyph_field_changed)
        for variable in (
            self.thickness_scale_var,
            self.start_cap_var,
            self.end_cap_var,
            self.filled_var,
        ):
            variable.trace_add("write", self._on_stroke_field_changed)

    def _bind_shortcuts(self) -> None:
        for sequence in self._bound_shortcut_sequences:
            self.root.unbind(sequence)
        self._bound_shortcut_sequences.clear()

        handlers = {
            "save": lambda _event: (self._save_document(), "break")[1],
            "undo": self._undo,
            "redo": self._redo,
            "copy_stroke": lambda event: self._run_stroke_shortcut(
                event, self._copy_selected_stroke
            ),
            "paste_stroke": lambda event: self._run_stroke_shortcut(
                event, self._paste_stroke
            ),
            "previous_stroke": lambda event: self._run_stroke_shortcut(
                event, lambda item: self._navigate_stroke(item, -1)
            ),
            "next_stroke": lambda event: self._run_stroke_shortcut(
                event, lambda item: self._navigate_stroke(item, 1)
            ),
            "select_all_strokes": lambda event: self._run_stroke_shortcut(
                event, self._select_all_strokes
            ),
            "round_cap": lambda event: self._set_drawing_cap(event, "round"),
            "flat_cap": lambda event: self._set_drawing_cap(event, "flat"),
            "toggle_start_cap": lambda event: self._run_stroke_shortcut(
                event, lambda item: self._toggle_selected_cap(item, "start")
            ),
            "toggle_end_cap": lambda event: self._run_stroke_shortcut(
                event, lambda item: self._toggle_selected_cap(item, "end")
            ),
            "toggle_filled": lambda event: self._run_stroke_shortcut(
                event, self._toggle_selected_filled
            ),
            "toggle_scale": lambda event: self._run_stroke_shortcut(
                event, self._toggle_selected_scale
            ),
            "move_up": lambda event: self._run_stroke_shortcut(
                event, lambda item: self._move_selected_strokes(item, 0, 1)
            ),
            "move_left": lambda event: self._run_stroke_shortcut(
                event, lambda item: self._move_selected_strokes(item, -1, 0)
            ),
            "move_down": lambda event: self._run_stroke_shortcut(
                event, lambda item: self._move_selected_strokes(item, 0, -1)
            ),
            "move_right": lambda event: self._run_stroke_shortcut(
                event, lambda item: self._move_selected_strokes(item, 1, 0)
            ),
            "delete_stroke": lambda event: self._run_stroke_shortcut(
                event, self._delete_selected_stroke
            ),
            "finish_centerline": self._finish_draft_centerline,
            "cancel_centerline": self._cancel_draft_centerline,
        }
        for action, shortcut in self.settings.shortcuts.items():
            for sequence in shortcut_sequences(shortcut):
                self.root.bind(sequence, handlers[action])
                self._bound_shortcut_sequences.add(sequence)

    @staticmethod
    def _event_is_in_text_input(event: tk.Event) -> bool:
        return isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text))

    def _focus_canvas(self) -> None:
        canvas = getattr(self, "canvas", None)
        if canvas is not None:
            canvas.focus_set()

    def _run_stroke_shortcut(self, event: tk.Event, handler) -> str:
        if self.draft_centerline and not self._event_is_in_text_input(event):
            return "break"
        return handler(event)

    def _snapshot(self) -> SessionSnapshot:
        return self._session.snapshot()

    def _record_undo(self) -> None:
        self._session.record_undo()

    def _restore_snapshot(self, snapshot: SessionSnapshot) -> None:
        self._session.restore_snapshot(snapshot)
        self._restore_session_ui()

    def _restore_session_ui(self) -> None:
        self._loading_fields = True
        try:
            self.name_var.set(self.document.name)
            self.unicode_var.set(format_codepoint(self.document.codepoint))
            self.x_extent_var.set(
                "" if self.document.x_extent is None else str(self.document.x_extent)
            )
            self._update_computed_offsets()
        finally:
            self._loading_fields = False
        self._glyph_fields_pending = False
        self._stroke_fields_pending = False
        self._update_identity_field_state()
        self._refresh_stroke_list()
        self._sync_editing_mode()
        if not self.selected_stroke_indices:
            self._clear_stroke_fields()
        else:
            self._on_stroke_selected()
        self._update_title()
        self._redraw()

    def _undo(self, event: tk.Event) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if not self._session.undo():
            self.status_var.set("Nothing to undo.")
            return "break"
        self._restore_session_ui()
        self.status_var.set("Undo.")
        return "break"

    def _redo(self, event: tk.Event) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if not self._session.redo():
            self.status_var.set("Nothing to redo.")
            return "break"
        self._restore_session_ui()
        self.status_var.set("Redo.")
        return "break"

    def _on_canvas_mouse_wheel(self, event: tk.Event) -> str:
        self._focus_canvas()
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            direction = -1
        elif getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            direction = 1
        else:
            return "break"
        return self._navigate_glyph(direction)

    def _navigate_glyph(self, direction: int) -> str:
        items = self.glyph_tree.get_children()
        if not items:
            return "break"
        selection = self.glyph_tree.selection()
        if not selection:
            target_index = 0 if direction > 0 else len(items) - 1
        else:
            target_index = (items.index(selection[0]) + direction) % len(items)
        target = items[target_index]
        if not self._open_glyph_item(target):
            return "break"
        self._changing_glyph = True
        try:
            self.glyph_tree.selection_set(target)
            self.glyph_tree.focus(target)
            self.glyph_tree.see(target)
        finally:
            self._changing_glyph = False
        return "break"

    def _navigate_stroke(self, event: tk.Event, direction: int) -> str:
        if self._event_is_in_text_input(event):
            return ""
        count = len(self.document.strokes)
        if not count:
            return "break"
        if not self.selected_stroke_indices:
            index = 0 if direction > 0 else count - 1
        else:
            edge = (
                max(self.selected_stroke_indices)
                if direction > 0
                else min(self.selected_stroke_indices)
            )
            index = (edge + direction) % count
        self.stroke_list.selection_clear(0, "end")
        self.stroke_list.selection_set(index)
        self.stroke_list.see(index)
        self._on_stroke_selected()
        return "break"

    def _select_all_strokes(self, event: tk.Event) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if self.document.strokes:
            self.stroke_list.selection_set(0, "end")
            self._on_stroke_selected()
        return "break"

    def _set_drawing_cap(self, event: tk.Event, cap: CapStyle) -> str:
        if self._event_is_in_text_input(event):
            return ""
        self.drawing_cap = cap
        self.status_var.set(f"New centerline points use {cap} caps.")
        self._redraw()
        return "break"

    def _move_selected_strokes_to_end(self) -> bool:
        indices = tuple(
            sorted(
                {
                    index
                    for index in self.selected_stroke_indices
                    if 0 <= index < len(self.document.strokes)
                }
            )
        )
        if not indices:
            self.selected_stroke_indices = ()
            return False
        tail_start = len(self.document.strokes) - len(indices)
        if indices == tuple(range(tail_start, len(self.document.strokes))):
            self.selected_stroke_indices = indices
            return False
        selected = set(indices)
        moved = [self.document.strokes[index] for index in indices]
        self.document.strokes[:] = [
            stroke
            for index, stroke in enumerate(self.document.strokes)
            if index not in selected
        ] + moved
        self.selected_stroke_indices = tuple(
            range(tail_start, len(self.document.strokes))
        )
        return True

    def _commit_stroke_mutation(
        self,
        mutation: Callable[[], None],
        *,
        move_to_end: bool = True,
        normalize: bool = False,
        refresh_list: bool | Literal["if-moved"] = True,
        refresh_properties: bool = True,
        clear_properties: bool = False,
    ) -> bool:
        """Commit one completed-stroke edit with consistent side effects."""

        self._record_undo()
        mutation()
        moved = self._move_selected_strokes_to_end() if move_to_end else False
        if normalize:
            self._normalize_skeleton_preserving_draft()
            self._update_computed_offsets()
        self._mark_dirty()
        if refresh_list is True or (refresh_list == "if-moved" and moved):
            self._refresh_stroke_list()
        if clear_properties:
            self._clear_stroke_fields()
        elif refresh_properties:
            self._on_stroke_selected()
        self._redraw()
        return moved

    def _toggle_selected_cap(self, event: tk.Event, end: str) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if not self.selected_stroke_indices:
            return "break"
        attribute = f"{end}_cap"
        current_values = {
            getattr(self.document.strokes[index], attribute)
            for index in self.selected_stroke_indices
        }
        target = (
            "flat" if current_values == {"round"} else "round"
        )
        indices = self.selected_stroke_indices

        def set_caps() -> None:
            for index in indices:
                setattr(self.document.strokes[index], attribute, target)

        self._commit_stroke_mutation(
            set_caps,
            refresh_list="if-moved",
        )
        self.status_var.set(
            f"Set {end}_cap to {target} on "
            f"{len(self.selected_stroke_indices)} selected stroke(s)."
        )
        self._redraw()
        return "break"

    def _toggle_selected_filled(self, event: tk.Event) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if len(self.selected_stroke_indices) != 1:
            self.status_var.set("Toggle filled requires exactly one selected stroke.")
            return "break"
        stroke = self.document.strokes[self.selected_stroke_indices[0]]
        candidate = copy.deepcopy(stroke)
        candidate.filled = not stroke.filled
        try:
            candidate.to_record()
        except ProjectDataError as error:
            self.status_var.set(str(error))
            return "break"
        self._commit_stroke_mutation(
            lambda: setattr(stroke, "filled", candidate.filled)
        )
        return "break"

    def _toggle_selected_scale(self, event: tk.Event) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if not self.selected_stroke_indices:
            return "break"
        current_values = {
            self.document.strokes[index].thickness_scale
            for index in self.selected_stroke_indices
        }
        target = 1.6 if current_values == {1.0} else 1.0
        indices = self.selected_stroke_indices

        def set_scales() -> None:
            for index in indices:
                self.document.strokes[index].thickness_scale = target

        self._commit_stroke_mutation(set_scales)
        self.status_var.set(
            f"Set thickness_scale to {target:g} on "
            f"{len(self.selected_stroke_indices)} selected stroke(s)."
        )
        return "break"

    def _move_selected_strokes(
        self,
        event: tk.Event,
        delta_x: int,
        delta_y: int,
    ) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if not self.selected_stroke_indices:
            return "break"
        indices = self.selected_stroke_indices

        def move() -> None:
            for index in indices:
                stroke = self.document.strokes[index]
                stroke.centerline = [
                    (x + delta_x, y + delta_y) for x, y in stroke.centerline
                ]

        self._commit_stroke_mutation(move, normalize=True)
        self.status_var.set(
            f"Moved {len(self.selected_stroke_indices)} selected stroke(s) "
            f"by ({delta_x}, {delta_y})."
        )
        return "break"

    def _copy_selected_stroke(self, event: tk.Event) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if not self.selected_stroke_indices:
            self.status_var.set("Copy requires at least one selected stroke.")
            return "break"

        selected = [
            self.document.strokes[index]
            for index in self.selected_stroke_indices
        ]
        all_points = [
            point for stroke in selected for point in stroke.centerline
        ]
        if not all_points:
            self.status_var.set("Selected strokes do not contain any points.")
            return "break"
        origin_x = min(x for x, _y in all_points)
        origin_y = min(y for _x, y in all_points)

        records: list[dict[str, object]] = []
        for stroke in selected:
            record: dict[str, object] = {
                "centerline": [
                    [x - origin_x, y - origin_y]
                    for x, y in stroke.centerline
                ]
            }
            if stroke.thickness_scale != 1:
                record["thickness_scale"] = stroke.thickness_scale
            if stroke.start_cap != "round":
                record["start_cap"] = stroke.start_cap
            if stroke.end_cap != "round":
                record["end_cap"] = stroke.end_cap
            if stroke.filled:
                record["filled"] = True
            records.append(record)

        payload = {
            "type": "skeletonfont-centerlines",
            "strokes": records,
        }
        self.root.clipboard_clear()
        self.root.clipboard_append(json.dumps(payload, separators=(",", ":")))
        self.status_var.set(
            f"Copied {len(records)} selected stroke(s) with a shared origin."
        )
        return "break"

    def _paste_stroke(self, event: tk.Event) -> str:
        if self._event_is_in_text_input(event):
            return ""
        if self.hover_grid_point is None:
            self.status_var.set("Move the mouse over the grid before pasting.")
            return "break"
        try:
            payload = json.loads(self.root.clipboard_get())
            if not isinstance(payload, dict):
                raise ValueError("Clipboard does not contain a copied centerline.")
            payload_type = payload.get("type")
            if payload_type == "skeletonfont-centerlines":
                raw_records = payload.get("strokes")
                if not isinstance(raw_records, list) or not raw_records:
                    raise ValueError(
                        "Clipboard does not contain any copied centerlines."
                    )
            elif payload_type == "skeletonfont-centerline":
                # Accept centerlines copied by earlier editor versions.
                raw_records = [payload.get("stroke")]
            else:
                raise ValueError("Clipboard does not contain a copied centerline.")
            records = [
                parse_stroke_record(item, location=f"Clipboard.strokes[{index}]")
                for index, item in enumerate(raw_records)
            ]
        except (tk.TclError, ValueError) as error:
            self.status_var.set(str(error))
            return "break"

        copied = [EditableStroke.from_record(record) for record in records]
        all_points = [
            point for stroke in copied for point in stroke.centerline
        ]
        origin_x = min(x for x, _y in all_points)
        origin_y = min(y for _x, y in all_points)
        anchor_x, anchor_y = self.hover_grid_point
        pasted_display_centerlines = [
            [
                (x - origin_x + anchor_x, y - origin_y + anchor_y)
                for x, y in stroke.centerline
            ]
            for stroke in copied
        ]
        if any(
            not (
                self.GRID_X_MIN <= x <= self.GRID_X_MAX
                and self.GRID_Y_MIN <= y <= self.GRID_Y_MAX
            )
            for centerline in pasted_display_centerlines
            for x, y in centerline
        ):
            self.status_var.set(
                "Cannot paste: the translated strokes would leave the grid."
            )
            return "break"

        for stroke, centerline in zip(copied, pasted_display_centerlines):
            stroke.centerline = [
                self.document.stored_point(point) for point in centerline
            ]
        self._record_undo()
        first_pasted_index = len(self.document.strokes)
        self.document.strokes.extend(copied)
        self.document.x_extent = None
        self._normalize_skeleton_preserving_draft()
        self._update_computed_offsets()
        self.selected_stroke_indices = tuple(
            range(first_pasted_index, len(self.document.strokes))
        )
        self._mark_dirty()
        self._refresh_stroke_list()
        self._on_stroke_selected()
        self.status_var.set(
            f"Pasted {len(copied)} stroke(s) at "
            f"({anchor_x:g}, {anchor_y:g})."
        )
        self._redraw()
        return "break"

    def _build_directory_tree(self) -> None:
        self._changing_directory = True
        try:
            self.directory_tree.delete(*self.directory_tree.get_children())
            self._directory_by_item.clear()
            self._item_by_directory.clear()
            directories = self.workspace.source_directories()
            for directory in directories:
                resolved = directory.resolve()
                if resolved == self.workspace.source_root.resolve():
                    parent_item = ""
                    label = "glyph_sources"
                else:
                    parent_item = self._item_by_directory[directory.parent.resolve()]
                    label = directory.name
                item = self.directory_tree.insert(
                    parent_item,
                    "end",
                    text=label,
                    open=resolved == self.workspace.source_root.resolve(),
                )
                self._directory_by_item[item] = resolved
                self._item_by_directory[resolved] = item
        finally:
            self._changing_directory = False

    def _on_directory_tree_selected(self, _event=None) -> None:
        if self._changing_directory:
            return
        selection = self.directory_tree.selection()
        if not selection:
            return
        directory = self._directory_by_item[selection[0]]
        if directory == self.active_source_directory.resolve():
            self._clear_glyph_search()
            return
        if not self._confirm_document_transition():
            self._changing_directory = True
            try:
                previous = self._item_by_directory[
                    self.active_source_directory.resolve()
                ]
                self.directory_tree.selection_set(previous)
            finally:
                self._changing_directory = False
            return
        self._clear_glyph_search()
        self._select_directory(directory, clear_document=True)

    def _clear_glyph_search(self) -> None:
        if self.search_var.get():
            self.search_var.set("")

    def _select_directory(self, directory: Path, *, clear_document: bool) -> None:
        self.active_source_directory = self.workspace.validate_source_directory(
            directory
        )
        if clear_document:
            self._load_document(EditorDocument())
        item = self._item_by_directory[self.active_source_directory.resolve()]
        self._changing_directory = True
        try:
            self.directory_tree.selection_set(item)
            self.directory_tree.see(item)
        finally:
            self._changing_directory = False
        self._refresh_glyph_list()
        relative = self.active_source_directory.relative_to(
            self.workspace.source_root
        )
        label = "glyph_sources" if not relative.parts else str(relative)
        self.status_var.set(f"Active source directory: {label}")

    def _refresh_glyph_list(
        self,
        *,
        reload: bool = False,
        selected_paths: tuple[Path, ...] = (),
    ) -> None:
        if reload or not self._all_glyph_entries:
            self._all_glyph_entries = self.workspace.all_glyphs()
        self._filter_glyph_list(selected_paths=selected_paths)

    def _filter_glyph_list(
        self,
        *,
        selected_paths: tuple[Path, ...] = (),
    ) -> None:
        query = self.search_var.get().strip().casefold()
        if query:
            entries = self._all_glyph_entries
        else:
            active = self.active_source_directory.resolve()
            entries = tuple(
                entry
                for entry in self._all_glyph_entries
                if entry.path.parent.resolve() == active
            )
        self._glyph_entries = entries
        selected = {path.resolve() for path in selected_paths}
        self._changing_glyph = True
        try:
            self.glyph_tree.delete(*self.glyph_tree.get_children())
            self._glyph_by_item.clear()
            current_item: str | None = None
            selected_items: list[str] = []
            for entry in entries:
                source = entry.source
                relative = entry.path.parent.relative_to(self.workspace.source_root)
                directory_text = (
                    "glyph_sources" if not relative.parts else relative.as_posix()
                )
                searchable = [
                    entry.path.name,
                    entry.display_name,
                    directory_text,
                ]
                if source is not None and source.codepoint is not None:
                    searchable.extend(
                        (
                            f"{source.codepoint:04X}",
                            f"U+{source.codepoint:04X}",
                        )
                    )
                if query and not any(
                    query in value.casefold() for value in searchable
                ):
                    continue
                if entry.source is None:
                    unicode_text = "invalid"
                    name = f"! {entry.display_name}"
                else:
                    unicode_text = (
                        "-"
                        if entry.source.codepoint is None
                        else f"U+{entry.source.codepoint:04X}"
                    )
                    name = entry.source.name
                item = self.glyph_tree.insert(
                    "",
                    "end",
                    values=(directory_text, name, unicode_text),
                )
                self._glyph_by_item[item] = entry
                if entry.path.resolve() in selected:
                    selected_items.append(item)
                if (
                    self.document.source_path is not None
                    and entry.path.resolve() == self.document.source_path.resolve()
                ):
                    current_item = item
            if selected_items:
                self.glyph_tree.selection_set(*selected_items)
                self.glyph_tree.see(selected_items[0])
            elif current_item is not None:
                self.glyph_tree.selection_set(current_item)
                self.glyph_tree.see(current_item)
        finally:
            self._changing_glyph = False

    def _refresh_workspace(self) -> None:
        current = self.active_source_directory
        self._all_glyph_entries = self.workspace.all_glyphs()
        self._build_directory_tree()
        if current.is_dir():
            self._select_directory(current, clear_document=False)
        else:
            self._select_directory(self.workspace.source_root, clear_document=True)

    def _on_glyph_tree_selected(self, _event=None) -> None:
        if self._changing_glyph or self._glyph_pointer_mode is not None:
            return
        selection = self.glyph_tree.selection()
        if len(selection) != 1:
            return
        self._open_glyph_item(selection[0])

    def _glyph_item_at(self, y: int) -> str | None:
        item = self.glyph_tree.identify_row(y)
        if not item:
            return None
        return item

    def _on_glyph_tree_left_press(self, event: tk.Event) -> str | None:
        self._hide_glyph_drag_indicator()
        self._glyph_press_origin = (event.x, event.y)
        self._glyph_drag_active = False
        self._glyph_drag_paths = ()
        self._set_glyph_drop_target(None)
        item = self._glyph_item_at(event.y)
        self._glyph_press_item = item
        if item is None:
            self._glyph_pointer_mode = "ignore"
            self._glyph_press_origin = None
            if not getattr(event, "state", 0) & 0x0004:
                self._changing_glyph = True
                try:
                    self.glyph_tree.selection_remove(
                        *self.glyph_tree.selection()
                    )
                finally:
                    self._changing_glyph = False
            return "break"

        self._glyph_pointer_mode = "move"
        selection = self.glyph_tree.selection()
        modifiers = getattr(event, "state", 0) & (0x0001 | 0x0004)
        self._glyph_preserve_selection_on_press = (
            not modifiers and item in selection and len(selection) > 1
        )
        return "break" if self._glyph_preserve_selection_on_press else None

    def _on_glyph_tree_drag(self, event: tk.Event) -> str:
        if self._glyph_press_origin is None or self._glyph_pointer_mode is None:
            return "break"
        origin_x, origin_y = self._glyph_press_origin
        if not self._glyph_drag_active and (
            abs(event.x - origin_x) < 3 and abs(event.y - origin_y) < 3
        ):
            return "break"
        self._glyph_drag_active = True

        pressed = self._glyph_press_item
        selection = self.glyph_tree.selection()
        if pressed is not None and pressed not in selection:
            self._changing_glyph = True
            try:
                self.glyph_tree.selection_set(pressed)
            finally:
                self._changing_glyph = False
            selection = (pressed,)
        self._glyph_drag_paths = tuple(
            self._glyph_by_item[item].path
            for item in selection
            if item in self._glyph_by_item
        )
        if self._glyph_drag_paths:
            self._update_glyph_drag_indicator(
                event.x_root,
                event.y_root,
                len(self._glyph_drag_paths),
            )
        target = self._directory_at_pointer(event.x_root, event.y_root)
        self._set_glyph_drop_target(target)
        return "break"

    def _on_glyph_tree_release(self, _event: tk.Event) -> str | None:
        mode = self._glyph_pointer_mode
        was_dragging = self._glyph_drag_active
        pressed = self._glyph_press_item
        paths = self._glyph_drag_paths
        target = self._glyph_drop_target
        preserve = self._glyph_preserve_selection_on_press
        self._glyph_press_origin = None
        self._glyph_press_item = None
        self._glyph_pointer_mode = None
        self._glyph_drag_active = False
        self._glyph_drag_paths = ()
        self._glyph_preserve_selection_on_press = False
        self._hide_glyph_drag_indicator()
        self._set_glyph_drop_target(None)

        if mode == "ignore":
            return "break"
        if mode != "move":
            return None
        if was_dragging:
            if target is not None and paths:
                self._move_glyph_paths(paths, target)
            return "break"

        if preserve and pressed is not None:
            self._changing_glyph = True
            try:
                self.glyph_tree.selection_set(pressed)
            finally:
                self._changing_glyph = False
        selection = self.glyph_tree.selection()
        if len(selection) == 1 and selection[0] == pressed:
            self._open_glyph_item(selection[0])
        return "break"

    def _update_glyph_drag_indicator(
        self,
        root_x: int,
        root_y: int,
        count: int,
    ) -> None:
        if self._glyph_drag_indicator is None:
            indicator = tk.Toplevel(self.root)
            indicator.overrideredirect(True)
            try:
                indicator.attributes("-topmost", True)
            except tk.TclError:
                pass
            canvas = tk.Canvas(
                indicator,
                width=54,
                height=30,
                background="#f7fbff",
                highlightthickness=1,
                highlightbackground="#7a9cc6",
            )
            canvas.pack()
            canvas.create_polygon(
                5,
                3,
                18,
                3,
                24,
                9,
                24,
                26,
                5,
                26,
                fill="white",
                outline="#386a9b",
                tags=("file-icon",),
            )
            canvas.create_line(18, 3, 18, 9, 24, 9, fill="#386a9b")
            canvas.create_line(9, 14, 20, 14, fill="#7a9cc6")
            canvas.create_line(9, 18, 20, 18, fill="#7a9cc6")
            canvas.create_text(
                39,
                15,
                text="",
                fill="#1d3557",
                font=("TkDefaultFont", 9, "bold"),
                tags=("drag-count",),
            )
            self._glyph_drag_indicator = indicator
            self._glyph_drag_indicator_canvas = canvas
        if self._glyph_drag_indicator_canvas is not None:
            self._glyph_drag_indicator_canvas.itemconfigure(
                "drag-count", text=f"×{count}"
            )
        self._glyph_drag_indicator.geometry(f"+{root_x + 14}+{root_y + 14}")
        self._glyph_drag_indicator.lift()

    def _hide_glyph_drag_indicator(self) -> None:
        indicator = getattr(self, "_glyph_drag_indicator", None)
        if indicator is not None:
            try:
                indicator.destroy()
            except tk.TclError:
                pass
        self._glyph_drag_indicator = None
        self._glyph_drag_indicator_canvas = None

    def _directory_at_pointer(self, root_x: int, root_y: int) -> Path | None:
        x = root_x - self.directory_tree.winfo_rootx()
        y = root_y - self.directory_tree.winfo_rooty()
        if not (
            0 <= x < self.directory_tree.winfo_width()
            and 0 <= y < self.directory_tree.winfo_height()
        ):
            return None
        item = self.directory_tree.identify_row(y)
        return self._directory_by_item.get(item)

    def _set_glyph_drop_target(self, target: Path | None) -> None:
        if self._glyph_drop_target is not None:
            previous = self._item_by_directory.get(
                self._glyph_drop_target.resolve()
            )
            if previous is not None:
                tags = tuple(
                    tag
                    for tag in self.directory_tree.item(previous, "tags")
                    if tag != "drop-target"
                )
                self.directory_tree.item(previous, tags=tags)
        self._glyph_drop_target = target
        if target is not None:
            item = self._item_by_directory.get(target.resolve())
            if item is not None:
                tags = tuple(self.directory_tree.item(item, "tags"))
                if "drop-target" not in tags:
                    self.directory_tree.item(
                        item, tags=(*tags, "drop-target")
                    )

    def _move_glyph_paths(
        self,
        paths: tuple[Path, ...],
        target: Path,
    ) -> bool:
        try:
            moves = self.workspace.plan_glyph_moves(paths, target)
        except (OSError, ValueError) as error:
            messagebox.showerror("Move failed", str(error), parent=self.root)
            return False
        if not moves:
            self.status_var.set("All selected glyphs are already in that directory.")
            return False

        relative = target.relative_to(self.workspace.source_root)
        directory_name = "glyph_sources" if not relative.parts else relative.as_posix()
        if not messagebox.askyesno(
            "Move glyph sources",
            f"Move {len(moves)} glyph source(s) to {directory_name}?",
            parent=self.root,
        ):
            return False
        try:
            self.workspace.execute_glyph_moves(moves)
        except (OSError, ValueError) as error:
            messagebox.showerror("Move failed", str(error), parent=self.root)
            return False

        moved_paths = {
            move.source.resolve(): move.destination.resolve() for move in moves
        }
        if self.document.source_path is not None:
            replacement = moved_paths.get(self.document.source_path.resolve())
            if replacement is not None:
                self.document.source_path = replacement
        selected_paths = tuple(move.destination for move in moves)
        self._refresh_glyph_list(reload=True, selected_paths=selected_paths)
        self._update_title()
        self.status_var.set(
            f"Moved {len(moves)} glyph source(s) to {directory_name}."
        )
        return True

    def _open_glyph_item(self, item: str) -> bool:
        entry = self._glyph_by_item[item]
        if (
            self.document.source_path is not None
            and entry.path.resolve() == self.document.source_path.resolve()
        ):
            return True
        if entry.source is None:
            messagebox.showerror(
                "Invalid glyph source",
                f"Cannot open {entry.path}:\n\n{entry.error}",
                parent=self.root,
            )
            return False
        if not self._confirm_document_transition():
            self._refresh_glyph_list()
            return False
        self._load_document(EditorDocument.from_source(entry.source))
        if entry.path.parent.resolve() != self.active_source_directory.resolve():
            self._select_directory(entry.path.parent, clear_document=False)
        self.status_var.set(f"Opened {entry.path.name}")
        return True

    def _new_document(self) -> None:
        if not self._confirm_document_transition():
            return
        self._load_document(EditorDocument())
        self.status_var.set("New glyph in the selected source directory.")

    def _load_document(self, document: EditorDocument) -> None:
        self._session.load(document)
        self.hover_grid_point = None
        self._loading_fields = True
        try:
            self.name_var.set(document.name)
            self.unicode_var.set(format_codepoint(document.codepoint))
            self._update_computed_offsets()
            self.x_extent_var.set(
                "" if document.x_extent is None else str(document.x_extent)
            )
        finally:
            self._loading_fields = False
        self._glyph_fields_pending = False
        self._stroke_fields_pending = False
        self._update_identity_field_state()
        self._refresh_stroke_list()
        self._sync_editing_mode()
        self._clear_stroke_fields()
        self._update_title()
        self._redraw()

    def _on_glyph_field_changed(self, *_args) -> None:
        if not self._loading_fields:
            self._glyph_fields_pending = True
            self._update_title()

    def _sync_editing_mode(self) -> None:
        drawing = bool(self.draft_centerline)
        self.stroke_list.configure(state="normal")
        if drawing:
            self._focus_canvas()
            self.stroke_list.selection_clear(0, "end")
            self.selected_stroke_indices = ()
            self._clear_stroke_fields()
        self.stroke_list.configure(state="disabled" if drawing else "normal")
        for widget, normal_state in self._stroke_edit_widgets:
            widget.configure(state="disabled" if drawing else normal_state)

    def _on_glyph_name_changed(self, *_args) -> None:
        if self._loading_fields:
            return
        self._update_unicode_preview()
        self._glyph_fields_pending = True
        self._update_title()

    def _on_stroke_field_changed(self, *_args) -> None:
        if not getattr(self, "_loading_stroke_fields", False):
            self._stroke_fields_pending = True
            self._update_title()

    def _update_unicode_preview(self) -> None:
        identity = self.workspace.identity_map.resolve(self.name_var.get())
        if identity is None:
            self.unicode_var.set("not found")
        elif identity.codepoint is None:
            self.unicode_var.set("unencoded")
        else:
            self.unicode_var.set(f"U+{identity.codepoint:04X}")

    def _update_identity_field_state(self) -> None:
        self.name_entry.configure(
            state=("normal" if self.document.source_path is None else "readonly")
        )
        if self.document.source_path is None:
            self._update_unicode_preview()
        elif self.document.codepoint is None:
            self.unicode_var.set("unencoded")
        else:
            self.unicode_var.set(f"U+{self.document.codepoint:04X}")

    def _apply_glyph_fields(self, *, resolve_identity: bool = True) -> bool:
        try:
            x_extent_text = self.x_extent_var.get().strip()
            x_extent = (
                None
                if not x_extent_text
                else parse_number(x_extent_text, field_name="x_extent")
            )
        except ValueError as error:
            messagebox.showerror("Invalid glyph field", str(error), parent=self.root)
            return False

        if bool(self.document.strokes) == (x_extent is not None):
            messagebox.showerror(
                "Invalid glyph field",
                "Define exactly one of skeleton and x_extent: a glyph with "
                "strokes must leave x_extent blank, and a glyph without strokes "
                "must provide x_extent.",
                parent=self.root,
            )
            return False

        if self.document.source_path is None and resolve_identity:
            identity = self.workspace.identity_map.resolve(self.name_var.get())
            if identity is None:
                messagebox.showerror(
                    "Unknown glyph name",
                    "Enter a glyph name from the identity map or a valid "
                    "uniXXXX name.",
                    parent=self.root,
                )
                return False
            name = identity.name
            codepoint = identity.codepoint
            self._loading_fields = True
            try:
                self.name_var.set(name)
                self.unicode_var.set(
                    "unencoded"
                    if codepoint is None
                    else f"U+{codepoint:04X}"
                )
            finally:
                self._loading_fields = False
        else:
            name = self.document.name
            codepoint = self.document.codepoint
        if (
            name,
            codepoint,
            x_extent,
        ) != (
            self.document.name,
            self.document.codepoint,
            self.document.x_extent,
        ):
            self._record_undo()
            self.document.name = name
            self.document.codepoint = codepoint
            self.document.x_extent = x_extent
            self._mark_dirty()
        self._glyph_fields_pending = False
        self._update_title()
        self._redraw()
        return True

    def _update_computed_offsets(self) -> None:
        self.monospace_x_offset_var.set(
            f"{self.document.monospace_x_offset:g} (automatic)"
        )
        self.y_offset_var.set(f"{self.document.y_offset:g} (automatic)")

    def _normalize_skeleton_preserving_draft(self) -> None:
        session = getattr(self, "_session", None)
        if session is not None:
            session.normalize_skeleton_preserving_draft()
            return
        draft_display_points = [
            self.document.display_point(point) for point in self.draft_centerline
        ]
        self.document.normalize_skeleton()
        self.draft_centerline = [
            self.document.stored_point(point) for point in draft_display_points
        ]

    def _refresh_stroke_list(self) -> None:
        self.stroke_list.delete(0, "end")
        for index, stroke in enumerate(self.document.strokes):
            closed = len(stroke.centerline) > 1 and (
                stroke.centerline[0] == stroke.centerline[-1]
            )
            flags = []
            if closed:
                flags.append("closed")
            if stroke.filled:
                flags.append("filled")
            if stroke.thickness_scale != 1:
                flags.append(f"×{stroke.thickness_scale:g}")
            suffix = f" ({', '.join(flags)})" if flags else ""
            self.stroke_list.insert(
                "end", f"{index + 1}: {len(stroke.centerline)} points{suffix}"
            )
        self.selected_stroke_indices = tuple(
            index
            for index in self.selected_stroke_indices
            if index < len(self.document.strokes)
        )
        for index in self.selected_stroke_indices:
            self.stroke_list.selection_set(index)

    def _on_stroke_selected(self, _event=None) -> None:
        if self.draft_centerline:
            self.selected_stroke_indices = ()
            return
        selection = tuple(int(index) for index in self.stroke_list.curselection())
        previous = self.selected_stroke_indices
        if (
            getattr(self, "_stroke_fields_pending", False)
            and previous
            and selection != previous
        ):
            requested_strokes = [
                self.document.strokes[index]
                for index in selection
                if 0 <= index < len(self.document.strokes)
            ]
            if not self._apply_stroke_properties(focus_canvas=False):
                self.stroke_list.selection_clear(0, "end")
                for index in self.selected_stroke_indices:
                    self.stroke_list.selection_set(index)
                return
            selection = tuple(
                index
                for index, stroke in enumerate(self.document.strokes)
                if any(stroke is requested for requested in requested_strokes)
            )
            self.stroke_list.selection_clear(0, "end")
            for index in selection:
                self.stroke_list.selection_set(index)
        if not selection:
            self.selected_stroke_indices = ()
            self._clear_stroke_fields()
            self._redraw()
            return
        self.selected_stroke_indices = selection
        selected = [
            self.document.strokes[index]
            for index in self.selected_stroke_indices
        ]

        def common_value(attribute: str):
            values = {getattr(stroke, attribute) for stroke in selected}
            return next(iter(values)) if len(values) == 1 else None

        scale = common_value("thickness_scale")
        start_cap = common_value("start_cap")
        end_cap = common_value("end_cap")
        filled = common_value("filled")
        self._loading_stroke_fields = True
        try:
            self.thickness_scale_var.set("" if scale is None else f"{scale:g}")
            self.start_cap_var.set("" if start_cap is None else start_cap)
            self.end_cap_var.set("" if end_cap is None else end_cap)
            self.filled_var.set(
                "" if filled is None else ("true" if filled else "false")
            )
        finally:
            self._loading_stroke_fields = False
        self._stroke_fields_pending = False
        self._set_filled_mixed_state(filled is None)
        if len(self.selected_stroke_indices) != 1:
            self.status_var.set(
                f"Selected {len(self.selected_stroke_indices)} strokes; "
                "blank properties have mixed values."
            )
            self._redraw()
            return
        self._redraw()

    def _on_stroke_list_left_click(self, event: tk.Event) -> str | None:
        self._stroke_drag_press_index = None
        self._stroke_drag_press_y = None
        self._stroke_drag_active = False
        self._stroke_drag_target_index = None
        self._stroke_preserve_selection_on_press = False
        if self.stroke_list.size() == 0:
            self.stroke_list.selection_clear(0, "end")
            self._on_stroke_selected()
            return "break"
        index = self.stroke_list.nearest(event.y)
        bounds = self.stroke_list.bbox(index)
        if bounds is None:
            is_blank = True
        else:
            left, top, width, height = bounds
            is_blank = not (
                left <= event.x < left + width
                and top <= event.y < top + height
            )
        if not is_blank:
            self._stroke_drag_press_index = index
            self._stroke_drag_press_y = event.y
            selection = tuple(int(item) for item in self.stroke_list.curselection())
            modifiers = getattr(event, "state", 0) & (0x0001 | 0x0004)
            self._stroke_preserve_selection_on_press = (
                not modifiers and index in selection and len(selection) > 1
            )
            return (
                "break"
                if self._stroke_preserve_selection_on_press
                else None
            )
        self.stroke_list.selection_clear(0, "end")
        self._on_stroke_selected()
        return "break"

    def _stroke_drop_insertion_index(self, y: int) -> int:
        count = self.stroke_list.size()
        if count == 0:
            return 0
        index = max(0, min(int(self.stroke_list.nearest(y)), count - 1))
        bounds = self.stroke_list.bbox(index)
        if bounds is None:
            return count
        _left, top, _width, height = bounds
        return index + (1 if y >= top + height / 2 else 0)

    def _on_stroke_list_drag(self, event: tk.Event) -> str:
        pressed = getattr(self, "_stroke_drag_press_index", None)
        press_y = getattr(self, "_stroke_drag_press_y", None)
        if pressed is None or press_y is None:
            return "break"
        if not self._stroke_drag_active and abs(event.y - press_y) < 3:
            return "break"
        self._stroke_drag_active = True
        height_getter = getattr(self.stroke_list, "winfo_height", None)
        scroll = getattr(self.stroke_list, "yview_scroll", None)
        if callable(height_getter) and callable(scroll):
            height = height_getter()
            if event.y < 0:
                scroll(-1, "units")
            elif event.y >= height:
                scroll(1, "units")
        selection = tuple(int(item) for item in self.stroke_list.curselection())
        if pressed not in selection:
            self.stroke_list.selection_clear(0, "end")
            self.stroke_list.selection_set(pressed)
            selection = (pressed,)
        self.selected_stroke_indices = selection
        self._stroke_drag_target_index = self._stroke_drop_insertion_index(
            event.y
        )
        self.stroke_list.activate(
            min(
                self._stroke_drag_target_index,
                max(self.stroke_list.size() - 1, 0),
            )
        )
        return "break"

    def _on_stroke_list_release(self, _event: tk.Event) -> str | None:
        pressed = getattr(self, "_stroke_drag_press_index", None)
        was_dragging = getattr(self, "_stroke_drag_active", False)
        target = getattr(self, "_stroke_drag_target_index", None)
        preserve = getattr(
            self, "_stroke_preserve_selection_on_press", False
        )
        self._stroke_drag_press_index = None
        self._stroke_drag_press_y = None
        self._stroke_drag_active = False
        self._stroke_drag_target_index = None
        self._stroke_preserve_selection_on_press = False
        if was_dragging and target is not None:
            self._reorder_selected_strokes(target)
            return "break"
        if preserve and pressed is not None:
            self.stroke_list.selection_clear(0, "end")
            self.stroke_list.selection_set(pressed)
            self._on_stroke_selected()
            return "break"
        return None

    def _reorder_selected_strokes(self, insertion_index: int) -> bool:
        count = len(self.document.strokes)
        indices = tuple(
            sorted(
                {
                    index
                    for index in self.selected_stroke_indices
                    if 0 <= index < count
                }
            )
        )
        if not indices:
            return False
        insertion_index = max(0, min(insertion_index, count))
        selected = set(indices)
        remaining_indices = [
            index for index in range(count) if index not in selected
        ]
        adjusted_index = insertion_index - sum(
            index < insertion_index for index in indices
        )
        adjusted_index = max(0, min(adjusted_index, len(remaining_indices)))
        reordered_indices = (
            remaining_indices[:adjusted_index]
            + list(indices)
            + remaining_indices[adjusted_index:]
        )
        if reordered_indices == list(range(count)):
            self._refresh_stroke_list()
            return False
        original = self.document.strokes.copy()

        def reorder() -> None:
            self.document.strokes[:] = [
                original[index] for index in reordered_indices
            ]
            self.selected_stroke_indices = tuple(
                range(adjusted_index, adjusted_index + len(indices))
            )

        self._commit_stroke_mutation(reorder, move_to_end=False)
        self.status_var.set(
            f"Moved {len(indices)} stroke(s) to position "
            f"{adjusted_index + 1}."
        )
        return True

    def _clear_stroke_fields(self) -> None:
        self._loading_stroke_fields = True
        try:
            self.thickness_scale_var.set("1")
            self.start_cap_var.set("round")
            self.end_cap_var.set("round")
            self.filled_var.set("false")
        finally:
            self._loading_stroke_fields = False
        self._stroke_fields_pending = False
        self._set_filled_mixed_state(False)

    def _set_filled_mixed_state(self, mixed: bool) -> None:
        checkbutton = getattr(self, "filled_check", None)
        if checkbutton is not None:
            checkbutton.state(["alternate"] if mixed else ["!alternate"])

    def _apply_stroke_properties(self, *, focus_canvas: bool = True) -> bool:
        if not self.selected_stroke_indices:
            self.status_var.set("Select one or more strokes to edit their properties.")
            return False
        multiple = len(self.selected_stroke_indices) > 1
        try:
            scale_text = str(self.thickness_scale_var.get()).strip()
            scale = None if multiple and not scale_text else parse_number(
                scale_text, field_name="thickness_scale"
            )
            if scale is not None and scale <= 0:
                raise ValueError("thickness_scale must be positive.")

            start_cap_text = str(self.start_cap_var.get()).strip()
            end_cap_text = str(self.end_cap_var.get()).strip()
            start_cap = None if multiple and not start_cap_text else start_cap_text
            end_cap = None if multiple and not end_cap_text else end_cap_text
            if start_cap not in (None, "round", "flat"):
                raise ValueError("start_cap must be round or flat.")
            if end_cap not in (None, "round", "flat"):
                raise ValueError("end_cap must be round or flat.")

            filled_text = str(self.filled_var.get()).strip().lower()
            if multiple and not filled_text:
                filled = None
            elif filled_text in ("true", "1"):
                filled = True
            elif filled_text in ("false", "0"):
                filled = False
            else:
                raise ValueError("filled must be true or false.")
        except ValueError as error:
            messagebox.showerror("Invalid stroke field", str(error), parent=self.root)
            return False

        candidates: list[tuple[int, EditableStroke]] = []
        for index in self.selected_stroke_indices:
            candidate = copy.deepcopy(self.document.strokes[index])
            if scale is not None:
                candidate.thickness_scale = scale
            if start_cap is not None:
                candidate.start_cap = start_cap  # type: ignore[assignment]
            if end_cap is not None:
                candidate.end_cap = end_cap  # type: ignore[assignment]
            if filled is not None:
                candidate.filled = filled
            try:
                candidate.to_record()
            except ProjectDataError as error:
                messagebox.showerror("Invalid stroke", str(error), parent=self.root)
                return False
            candidates.append((index, candidate))

        changed = [
            (index, candidate)
            for index, candidate in candidates
            if candidate != self.document.strokes[index]
        ]
        self._stroke_fields_pending = False
        if changed:
            def replace_strokes() -> None:
                for index, candidate in changed:
                    self.document.strokes[index] = candidate

            self._commit_stroke_mutation(replace_strokes)
        else:
            self._refresh_stroke_list()
            self._on_stroke_selected()
        if changed:
            self.status_var.set(
                "Applied stroke properties to "
                f"{len(self.selected_stroke_indices)} selected stroke(s)."
            )
        if focus_canvas:
            self._focus_canvas()
        self._redraw()
        return True

    def _delete_selected_stroke(self, event=None) -> str:
        if event is not None and isinstance(event.widget, (tk.Entry, ttk.Entry)):
            return ""
        if not self.selected_stroke_indices:
            return "break"
        indices = self.selected_stroke_indices

        def delete_strokes() -> None:
            for index in reversed(indices):
                del self.document.strokes[index]
            self.selected_stroke_indices = ()

        self._commit_stroke_mutation(
            delete_strokes,
            move_to_end=False,
            normalize=True,
            refresh_properties=False,
            clear_properties=True,
        )
        return "break"

    def _reverse_selected_stroke(self) -> None:
        if not self.selected_stroke_indices:
            return
        indices = self.selected_stroke_indices

        def reverse_strokes() -> None:
            for index in indices:
                stroke = self.document.strokes[index]
                stroke.centerline.reverse()
                stroke.start_cap, stroke.end_cap = (
                    stroke.end_cap,
                    stroke.start_cap,
                )

        self._commit_stroke_mutation(reverse_strokes)

    def _toggle_selected_stroke_closed(self) -> None:
        if not self.selected_stroke_indices:
            return
        selected = [
            self.document.strokes[index] for index in self.selected_stroke_indices
        ]
        if any(
            not (
                len(stroke.centerline) > 1
                and stroke.centerline[0] == stroke.centerline[-1]
            )
            and len(stroke.centerline) < 3
            for stroke in selected
        ):
            self.status_var.set("A closed centerline needs at least three points.")
            return
        def toggle_closed() -> None:
            for stroke in selected:
                if (
                    len(stroke.centerline) > 1
                    and stroke.centerline[0] == stroke.centerline[-1]
                ):
                    stroke.centerline.pop()
                    stroke.filled = False
                else:
                    stroke.centerline.append(stroke.centerline[0])

        self._commit_stroke_mutation(toggle_closed)

    def _canvas_metrics(self) -> tuple[float, float, float]:
        width = max(self.canvas.winfo_width(), 600)
        height = max(self.canvas.winfo_height(), 650)
        padding = 25.0
        cell_size = min(
            self.CELL_SIZE,
            (width - 2 * padding) / (self.GRID_X_MAX - self.GRID_X_MIN),
            (height - 2 * padding) / (self.GRID_Y_MAX - self.GRID_Y_MIN),
        )
        return padding, padding, cell_size

    def _grid_to_canvas(self, point: tuple[float, float]) -> tuple[float, float]:
        left, top, cell_size = self._canvas_metrics()
        return (
            left + (point[0] - self.GRID_X_MIN) * cell_size,
            top + (self.GRID_Y_MAX - point[1]) * cell_size,
        )

    def _canvas_to_grid(self, x: float, y: float) -> tuple[float, float]:
        left, top, cell_size = self._canvas_metrics()
        return (
            round(self.GRID_X_MIN + (x - left) / cell_size),
            round(self.GRID_Y_MAX - (y - top) / cell_size),
        )

    def _canvas_position_is_in_grid(self, x: float, y: float) -> bool:
        left, top, cell_size = self._canvas_metrics()
        right = left + (self.GRID_X_MAX - self.GRID_X_MIN) * cell_size
        bottom = top + (self.GRID_Y_MAX - self.GRID_Y_MIN) * cell_size
        return left <= x <= right and top <= y <= bottom

    def _on_canvas_motion(self, event: tk.Event) -> None:
        hover = (
            self._canvas_to_grid(event.x, event.y)
            if self._canvas_position_is_in_grid(event.x, event.y)
            else None
        )
        if hover != self.hover_grid_point:
            self.hover_grid_point = hover
            self._redraw()

    def _on_canvas_leave(self, _event=None) -> None:
        if self.hover_grid_point is not None:
            self.hover_grid_point = None
            self._redraw()

    def _on_canvas_left_click(self, event: tk.Event) -> None:
        self._focus_canvas()
        if (
            not self.draft_centerline
            and getattr(self, "_stroke_fields_pending", False)
            and not self._apply_stroke_properties()
        ):
            return
        if not self._canvas_position_is_in_grid(event.x, event.y):
            self.status_var.set("Points can only be added inside the grid.")
            return
        display_point = self._canvas_to_grid(event.x, event.y)
        stored_point = self.document.stored_point(display_point)
        if self.draft_centerline and stored_point == self.draft_centerline[-1]:
            return
        self._record_undo()
        if not self.draft_centerline:
            self.stroke_list.selection_clear(0, "end")
            self.selected_stroke_indices = ()
            self._clear_stroke_fields()
            session = getattr(self, "_session", None)
            if session is not None:
                session.begin_draft(stored_point, self.drawing_cap)
            else:
                self.draft_start_cap = self.drawing_cap
                self.draft_centerline.append(stored_point)
        else:
            session = getattr(self, "_session", None)
            if session is not None:
                session.append_draft_point(stored_point)
            else:
                self.draft_centerline.append(stored_point)
        self._sync_editing_mode()
        self._mark_dirty()
        self.status_var.set(
            f"Draft centerline: {len(self.draft_centerline)} point(s)."
        )
        self._redraw()

    def _finish_draft_centerline(self, _event=None) -> str:
        if _event is not None and self._event_is_in_text_input(_event):
            return ""
        if not self.draft_centerline:
            return "break"
        if self.draft_start_cap is None:
            raise RuntimeError("Draft centerline is missing its start cap.")
        self._record_undo()
        self.document.strokes.append(
            EditableStroke(
                centerline=self.draft_centerline.copy(),
                start_cap=self.draft_start_cap,
                end_cap=self.drawing_cap,
            )
        )
        session = getattr(self, "_session", None)
        if session is not None:
            session.interaction = Editing(
                (len(self.document.strokes) - 1,)
            )
        else:
            self.draft_centerline.clear()
            self.draft_start_cap = None
            self.selected_stroke_indices = (
                len(self.document.strokes) - 1,
            )
        self.document.x_extent = None
        self._loading_fields = True
        try:
            self.x_extent_var.set("")
        finally:
            self._loading_fields = False
        self._normalize_skeleton_preserving_draft()
        self._update_computed_offsets()
        self._mark_dirty()
        self._sync_editing_mode()
        self._refresh_stroke_list()
        self._on_stroke_selected()
        self.status_var.set("Centerline added.")
        self._redraw()
        return "break"

    def _cancel_draft_centerline(self, _event=None) -> str:
        if _event is not None and self._event_is_in_text_input(_event):
            return ""
        if self.draft_centerline:
            self._record_undo()
            session = getattr(self, "_session", None)
            if session is not None:
                session.cancel_draft()
            else:
                self.draft_centerline.clear()
                self.draft_start_cap = None
            self._sync_editing_mode()
            self._mark_dirty()
            self.status_var.set("Draft centerline cancelled.")
            self._redraw()
        return "break"

    def _on_canvas_right_click(self, event=None) -> str:
        self._focus_canvas()
        if self.draft_centerline:
            return self._finish_draft_centerline(event)
        self.stroke_list.selection_clear(0, "end")
        self._on_stroke_selected()
        self.status_var.set("Stroke selection cleared.")
        self._redraw()
        return "break"

    def _redraw(self) -> None:
        self.canvas.delete("all")
        for x in range(self.GRID_X_MIN, self.GRID_X_MAX + 1):
            start = self._grid_to_canvas((x, self.GRID_Y_MIN))
            end = self._grid_to_canvas((x, self.GRID_Y_MAX))
            self.canvas.create_line(*start, *end, fill="#dddddd")
        for y in range(self.GRID_Y_MIN, self.GRID_Y_MAX + 1):
            start = self._grid_to_canvas((self.GRID_X_MIN, y))
            end = self._grid_to_canvas((self.GRID_X_MAX, y))
            self.canvas.create_line(*start, *end, fill="#dddddd")
        for x in self.settings.guide_x:
            if self.GRID_X_MIN <= x <= self.GRID_X_MAX:
                start = self._grid_to_canvas((x, self.GRID_Y_MIN))
                end = self._grid_to_canvas((x, self.GRID_Y_MAX))
                self.canvas.create_line(*start, *end, fill="#c74c4c", width=2)
        for y in self.settings.guide_y:
            if self.GRID_Y_MIN <= y <= self.GRID_Y_MAX:
                start = self._grid_to_canvas((self.GRID_X_MIN, y))
                end = self._grid_to_canvas((self.GRID_X_MAX, y))
                self.canvas.create_line(*start, *end, fill="#c74c4c", width=2)

        origin_x, origin_y = self._grid_to_canvas((0, 0))
        self.canvas.create_oval(
            origin_x - 5,
            origin_y - 5,
            origin_x + 5,
            origin_y + 5,
            outline="#111111",
            width=2,
        )
        self.canvas.create_line(
            origin_x - 8,
            origin_y,
            origin_x + 8,
            origin_y,
            fill="#111111",
            width=2,
        )
        self.canvas.create_line(
            origin_x,
            origin_y - 8,
            origin_x,
            origin_y + 8,
            fill="#111111",
            width=2,
        )
        self.canvas.create_text(
            origin_x + 8,
            origin_y + 8,
            text="(0, 0)",
            anchor="nw",
            fill="#333333",
        )

        for index, stroke in enumerate(self.document.strokes):
            color = (
                "#16875d"
                if index in self.selected_stroke_indices
                else "#2459c4"
            )
            self._draw_centerline(
                stroke.centerline,
                color=color,
                width=max(2.0, 3.0 * stroke.thickness_scale),
                filled=stroke.filled,
                start_cap=stroke.start_cap,
                end_cap=stroke.end_cap,
            )
        if self.draft_centerline:
            if self.draft_start_cap is None:
                raise RuntimeError("Draft centerline is missing its start cap.")
            self._draw_centerline(
                self.draft_centerline,
                color="#222222",
                width=2,
                filled=False,
                start_cap=self.draft_start_cap,
                end_cap=self.drawing_cap,
                finalized=False,
            )
        if self.hover_grid_point is not None:
            hover_canvas = self._grid_to_canvas(self.hover_grid_point)
            if self.draft_centerline:
                draft_end = self._grid_to_canvas(
                    self.document.display_point(self.draft_centerline[-1])
                )
                if hover_canvas != draft_end:
                    self.canvas.create_line(
                        *draft_end,
                        *hover_canvas,
                        fill="#666666",
                        dash=(6, 4),
                        width=2,
                    )
            self._draw_hover_indicator(self.hover_grid_point)

    def _draw_hover_indicator(self, point: tuple[float, float]) -> None:
        x, y = self._grid_to_canvas(point)
        if self.drawing_cap == "flat":
            self.canvas.create_rectangle(
                x - 6,
                y - 6,
                x + 6,
                y + 6,
                outline="#d62828",
                width=2,
            )
        else:
            self.canvas.create_oval(
                x - 6,
                y - 6,
                x + 6,
                y + 6,
                outline="#222222",
                width=2,
            )

    def _draw_centerline(
        self,
        centerline: list[tuple[float, float]],
        *,
        color: str,
        width: float,
        filled: bool,
        start_cap: CapStyle,
        end_cap: CapStyle,
        finalized: bool = True,
    ) -> None:
        coordinates: list[float] = []
        for point in centerline:
            coordinates.extend(
                self._grid_to_canvas(self.document.display_point(point))
            )
        if filled and len(centerline) >= 4 and centerline[0] == centerline[-1]:
            self.canvas.create_polygon(*coordinates, fill="#b8c9ed", outline="")
        if len(centerline) >= 2:
            self.canvas.create_line(
                *coordinates,
                fill=color,
                width=width,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
            )
        closed = len(centerline) > 1 and centerline[0] == centerline[-1]
        last_index = len(centerline) - 1
        for index, point in enumerate(centerline):
            x, y = self._grid_to_canvas(self.document.display_point(point))
            is_active_draft_end = (
                not finalized and not closed and index == last_index
            )
            is_flat_start = not closed and index == 0 and start_cap == "flat"
            is_flat_end = (
                finalized
                and not closed
                and index == last_index
                and end_cap == "flat"
            )
            if is_active_draft_end and end_cap == "flat":
                self.canvas.create_rectangle(
                    x - 5,
                    y - 5,
                    x + 5,
                    y + 5,
                    fill=color,
                    outline=color,
                )
            elif is_flat_start or is_flat_end:
                self.canvas.create_rectangle(
                    x - 5,
                    y - 5,
                    x + 5,
                    y + 5,
                    fill="#d62828",
                    outline="#d62828",
                )
            else:
                self.canvas.create_oval(
                    x - 4,
                    y - 4,
                    x + 4,
                    y + 4,
                    fill=color,
                    outline=color,
                )

    def _prepare_document_for_save(self, *, resolve_identity: bool = True) -> bool:
        if self.draft_centerline:
            messagebox.showwarning(
                "Unfinished centerline",
                "Finish or cancel the draft centerline before saving.",
                parent=self.root,
            )
            return False
        if not self._apply_glyph_fields(resolve_identity=resolve_identity):
            return False
        if self.selected_stroke_indices and not self._apply_stroke_properties():
            return False
        return True

    def _write_document(
        self,
        identity: GlyphIdentity,
        target: Path,
        *,
        confirm_overwrite: bool,
    ) -> bool:
        if (
            confirm_overwrite
            and target.exists()
            and not messagebox.askyesno(
                "Overwrite glyph",
                f"{target.name} already exists. Overwrite it?",
                parent=self.root,
            )
        ):
            return False

        self._normalize_skeleton_preserving_draft()
        self._update_computed_offsets()

        output_document = copy.deepcopy(self.document)
        output_document.name = identity.name
        output_document.codepoint = identity.codepoint
        output_document.source_path = None
        output_document.locked_identity = None

        try:
            source = output_document.validated_source(target)
            written = write_glyph_source(source, target)
        except (OSError, ValueError) as error:
            messagebox.showerror("Save failed", str(error), parent=self.root)
            return False

        self._load_document(EditorDocument.from_source(written))
        self._refresh_glyph_list(reload=True)
        self.status_var.set(f"Saved {target}")
        return True

    def _save_document(self) -> bool:
        if not self._prepare_document_for_save(resolve_identity=False):
            return False

        if self.document.source_path is None:
            identity = self.workspace.identity_map.resolve(self.name_var.get())
            if identity is None:
                identity = self._request_glyph_identity(
                    title="Name new glyph",
                    initial_name=self.name_var.get(),
                )
                if identity is None:
                    return False
            target = self.active_source_directory / glyph_filename(
                identity.name,
                identity.codepoint,
            )
            confirm_overwrite = True
        else:
            identity = self.workspace.identity_map.resolve(self.document.name)
            if identity is None or (
                identity.name,
                identity.codepoint,
            ) != (
                self.document.name,
                self.document.codepoint,
            ):
                messagebox.showerror(
                    "Invalid glyph identity",
                    "The glyph name and Unicode do not match the glyph identity "
                    "map.",
                    parent=self.root,
                )
                return False
            target = self.document.source_path
            confirm_overwrite = False
        return self._write_document(
            identity,
            target,
            confirm_overwrite=confirm_overwrite,
        )

    def _save_document_as(self) -> bool:
        if not self._prepare_document_for_save(resolve_identity=False):
            return False

        identity = self._request_glyph_identity(
            title="Save glyph as",
            initial_name=(
                self.name_var.get()
                if self.document.source_path is None
                else self.document.name
            ),
        )
        if identity is None:
            return False

        target = self.active_source_directory / glyph_filename(
            identity.name,
            identity.codepoint,
        )
        if (
            self.document.source_path is not None
            and target.resolve() == self.document.source_path.resolve()
        ):
            messagebox.showerror(
                "Save As needs a new identity",
                "Choose a different glyph name; Save updates the current file.",
                parent=self.root,
            )
            return False
        return self._write_document(
            identity,
            target,
            confirm_overwrite=True,
        )

    def _request_glyph_identity(
        self,
        *,
        title: str,
        initial_name: str,
    ) -> GlyphIdentity | None:
        raw_name = simpledialog.askstring(
            title,
            "Glyph name from the identity map or uniXXXX:",
            initialvalue=initial_name,
            parent=self.root,
        )
        if raw_name is None:
            return None
        identity = self.workspace.identity_map.resolve(raw_name)
        if identity is None:
            messagebox.showerror(
                "Unknown glyph name",
                f"{raw_name!r} is not in the glyph identity map and is not a valid "
                "uniXXXX name.",
                parent=self.root,
            )
        return identity

    def _confirm_document_transition(self) -> bool:
        if (
            not self.document.dirty
            and not self.draft_centerline
            and not getattr(self, "_glyph_fields_pending", False)
            and not getattr(self, "_stroke_fields_pending", False)
        ):
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            "Save the current glyph before continuing?",
            parent=self.root,
        )
        if answer is None:
            return False
        if answer:
            return self._save_document()
        return True

    def _mark_dirty(self) -> None:
        session = getattr(self, "_session", None)
        if session is not None:
            session.sync_dirty()
        else:
            self.document.dirty = True
        self._update_title()

    def _update_title(self) -> None:
        name = (
            self.document.source_path.name
            if self.document.source_path is not None
            else "Untitled"
        )
        marker = (
            " *"
            if (
                self.document.dirty
                or self.draft_centerline
                or getattr(self, "_glyph_fields_pending", False)
                or getattr(self, "_stroke_fields_pending", False)
            )
            else ""
        )
        self.root.title(f"{name}{marker} — SkeletonFont Glyph Editor")

    def _on_close(self) -> None:
        if self._confirm_document_transition():
            self.root.destroy()
