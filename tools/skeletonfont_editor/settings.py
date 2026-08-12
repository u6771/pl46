from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from skeletonfont.errors import ProjectDataError


EDITOR_SETTINGS_PATH = Path(__file__).with_name("editor_settings.json")


SHORTCUT_ACTIONS: tuple[tuple[str, str], ...] = (
    ("save", "Save"),
    ("undo", "Undo"),
    ("redo", "Redo"),
    ("copy_stroke", "Copy selected strokes"),
    ("paste_stroke", "Paste strokes"),
    ("previous_stroke", "Previous stroke"),
    ("next_stroke", "Next stroke"),
    ("select_all_strokes", "Select all strokes"),
    ("round_cap", "Draw round cap"),
    ("flat_cap", "Draw flat cap"),
    ("toggle_start_cap", "Toggle start cap"),
    ("toggle_end_cap", "Toggle end cap"),
    ("toggle_filled", "Toggle filled"),
    ("toggle_scale", "Toggle thickness scale"),
    ("move_up", "Move selected strokes up"),
    ("move_left", "Move selected strokes left"),
    ("move_down", "Move selected strokes down"),
    ("move_right", "Move selected strokes right"),
    ("delete_stroke", "Delete stroke"),
    ("finish_centerline", "Finish centerline"),
    ("cancel_centerline", "Cancel centerline"),
)

_ACTION_NAMES = frozenset(action for action, _label in SHORTCUT_ACTIONS)
_MODIFIER_NAMES = {
    "CTRL": "Control",
    "CONTROL": "Control",
    "ALT": "Alt",
    "SHIFT": "Shift",
}
_KEY_NAMES = {
    "LEFT": "Left",
    "RIGHT": "Right",
    "UP": "Up",
    "DOWN": "Down",
    "ENTER": "Return",
    "RETURN": "Return",
    "ESC": "Escape",
    "ESCAPE": "Escape",
    "DELETE": "Delete",
    "BACKSPACE": "BackSpace",
    "SPACE": "space",
    "TAB": "Tab",
}


def parse_guide_values(text: str) -> tuple[float, ...]:
    if not text.strip():
        return ()
    values: list[float] = []
    for item in text.split(","):
        try:
            value = float(item.strip())
        except ValueError as error:
            raise ValueError("Guidelines must be comma-separated numbers.") from error
        if not math.isfinite(value):
            raise ValueError("Guidelines must contain finite numbers.")
        if value not in values:
            values.append(value)
    return tuple(values)


def format_guide_values(values: tuple[float, ...]) -> str:
    return ", ".join(f"{value:g}" for value in values)


def shortcut_sequences(shortcut: str) -> tuple[str, ...]:
    """Translate a readable shortcut such as Ctrl+S into Tk sequences."""

    text = shortcut.strip()
    if not text:
        return ()
    parts = [part.strip() for part in text.split("+")]
    if any(not part for part in parts):
        raise ValueError(f"Invalid shortcut {shortcut!r}.")

    modifiers: list[str] = []
    for part in parts[:-1]:
        modifier = _MODIFIER_NAMES.get(part.upper())
        if modifier is None:
            raise ValueError(f"Unknown shortcut modifier {part!r}.")
        if modifier not in modifiers:
            modifiers.append(modifier)

    raw_key = parts[-1]
    key = _KEY_NAMES.get(raw_key.upper())
    if key is None:
        if len(raw_key) == 1 and raw_key.isalnum():
            key = raw_key.lower()
        elif raw_key.upper().startswith("F") and raw_key[1:].isdigit():
            number = int(raw_key[1:])
            if not 1 <= number <= 24:
                raise ValueError("Function keys must be between F1 and F24.")
            key = f"F{number}"
        else:
            raise ValueError(f"Unknown shortcut key {raw_key!r}.")

    prefix = "-".join((*modifiers, "KeyPress"))
    sequences = [f"<{prefix}-{key}>"]
    if not modifiers and len(raw_key) == 1 and raw_key.isalpha():
        sequences.append(f"<KeyPress-{raw_key.upper()}>")
    return tuple(sequences)


def validate_shortcuts(shortcuts: dict[str, str]) -> None:
    owners: dict[str, str] = {}
    for action, shortcut in shortcuts.items():
        for sequence in shortcut_sequences(shortcut):
            other = owners.get(sequence)
            if other is not None:
                raise ValueError(
                    f"Shortcut {shortcut!r} is assigned to both {other!r} "
                    f"and {action!r}."
                )
            owners[sequence] = action


@dataclass(slots=True)
class EditorSettings:
    guide_x: tuple[float, ...]
    guide_y: tuple[float, ...]
    shortcuts: dict[str, str]


def load_editor_settings() -> EditorSettings:
    path = EDITOR_SETTINGS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectDataError(f"Cannot read editor settings {path}: {error}") from error
    if not isinstance(data, dict):
        raise ProjectDataError(f"Editor settings must contain an object: {path}")
    expected = {"guide_x", "guide_y", "shortcuts"}
    unknown = set(data) - expected
    if unknown:
        raise ProjectDataError(f"Unknown editor settings: {sorted(unknown)}")
    missing = expected - set(data)
    if missing:
        raise ProjectDataError(f"Missing editor settings: {sorted(missing)}")

    def guides(name: str) -> tuple[float, ...]:
        raw = data[name]
        if not isinstance(raw, list) or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in raw
        ):
            raise ProjectDataError(f"{name} must be an array of finite numbers.")
        return tuple(float(value) for value in raw)

    raw_shortcuts = data["shortcuts"]
    if not isinstance(raw_shortcuts, dict):
        raise ProjectDataError("shortcuts must contain an object.")
    unknown_actions = set(raw_shortcuts) - _ACTION_NAMES
    if unknown_actions:
        raise ProjectDataError(
            f"Unknown shortcut actions: {sorted(unknown_actions)}"
        )
    missing_actions = _ACTION_NAMES - set(raw_shortcuts)
    if missing_actions:
        raise ProjectDataError(
            f"Missing shortcut actions: {sorted(missing_actions)}"
        )
    shortcuts: dict[str, str] = {}
    for action, shortcut in raw_shortcuts.items():
        if not isinstance(shortcut, str):
            raise ProjectDataError(f"Shortcut {action!r} must be a string.")
        shortcuts[action] = shortcut.strip()
    try:
        validate_shortcuts(shortcuts)
    except ValueError as error:
        raise ProjectDataError(str(error)) from error
    return EditorSettings(
        guide_x=guides("guide_x"),
        guide_y=guides("guide_y"),
        shortcuts=shortcuts,
    )


def save_editor_settings(settings: EditorSettings) -> Path:
    validate_shortcuts(settings.shortcuts)
    path = EDITOR_SETTINGS_PATH
    data = {
        "guide_x": list(settings.guide_x),
        "guide_y": list(settings.guide_y),
        "shortcuts": settings.shortcuts,
    }
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return path
