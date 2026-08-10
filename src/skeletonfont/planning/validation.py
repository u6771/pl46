from __future__ import annotations

import math

from ..errors import PlanError
from ..model import KerningData, MathTableData
from ..opentype import FWORD_MAX, FWORD_MIN, UFWORD_MAX


def _validate_kerning(
    glyph_names: set[str],
    kerning: KerningData | None,
) -> None:
    if kerning is None:
        return
    group_by_member_and_side: dict[tuple[int, str], str] = {}
    for group_name, members in kerning.groups.items():
        if group_name.startswith("public.kern1."):
            side = 1
        elif group_name.startswith("public.kern2."):
            side = 2
        else:
            raise PlanError(
                f"Kerning group {group_name!r} must use a public.kern1.* "
                "or public.kern2.* name."
            )
        missing = set(members) - glyph_names
        if missing:
            raise PlanError(
                f"Kerning group {group_name!r} contains unknown glyphs: "
                f"{sorted(missing)}"
            )
        for member in members:
            key = (side, member)
            previous = group_by_member_and_side.get(key)
            if previous is not None:
                raise PlanError(
                    f"Glyph {member!r} belongs to multiple side-{side} "
                    f"kerning groups: {previous!r} and {group_name!r}."
                )
            group_by_member_and_side[key] = group_name
    valid_sides = glyph_names | set(kerning.groups)
    for pair in kerning.pairs:
        missing = {pair.left, pair.right} - valid_sides
        if missing:
            raise PlanError(
                "Kerning pair contains unknown glyphs or groups: "
                f"{sorted(missing)}"
            )
        if pair.left in kerning.groups and not pair.left.startswith(
            "public.kern1."
        ):
            raise PlanError(
                f"Kerning pair uses right-side group {pair.left!r} on "
                "the left."
            )
        if pair.right in kerning.groups and not pair.right.startswith(
            "public.kern2."
        ):
            raise PlanError(
                f"Kerning pair uses left-side group {pair.right!r} on "
                "the right."
            )
        if (
            not math.isfinite(pair.value)
            or not FWORD_MIN <= pair.value <= FWORD_MAX
        ):
            raise PlanError(
                f"Kerning pair {(pair.left, pair.right)!r} has value "
                f"{pair.value!r} outside the OpenType FWORD range."
            )


def _require_integer_range(
    value: object,
    *,
    location: str,
    minimum: int,
    maximum: int,
) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise PlanError(
            f"{location} must be an integer between {minimum} and "
            f"{maximum}."
        )


def _validate_math_table_ranges(data: MathTableData) -> None:
    ufword_constants = {
        "DelimitedSubFormulaMinHeight",
        "DisplayOperatorMinHeight",
    }
    for name, value in data.constants.items():
        _require_integer_range(
            value,
            location=f"Math constant {name!r}",
            minimum=0 if name in ufword_constants else FWORD_MIN,
            maximum=UFWORD_MAX if name in ufword_constants else FWORD_MAX,
        )
    _require_integer_range(
        data.min_connector_overlap,
        location="Math minConnectorOverlap",
        minimum=0,
        maximum=UFWORD_MAX,
    )
    for name, correction in data.italic_corrections.items():
        _require_integer_range(
            correction,
            location=f"Math italic correction for {name!r}",
            minimum=0,
            maximum=FWORD_MAX,
        )
    for axis, assemblies in (
        ("vertical", data.vertical_assemblies),
        ("horizontal", data.horizontal_assemblies),
    ):
        for base, assembly in assemblies.items():
            _require_integer_range(
                assembly.italic_correction,
                location=(
                    f"Math {axis} assembly italic correction for {base!r}"
                ),
                minimum=FWORD_MIN,
                maximum=FWORD_MAX,
            )
    for name, kern in data.kerns.items():
        for corner in (
            "top_right",
            "top_left",
            "bottom_right",
            "bottom_left",
        ):
            table = getattr(kern, corner)
            if table is None:
                continue
            for index, height in enumerate(table.correction_height):
                _require_integer_range(
                    height,
                    location=(
                        f"Math kern {name!r}.{corner} correction height "
                        f"{index}"
                    ),
                    minimum=FWORD_MIN,
                    maximum=FWORD_MAX,
                )
            for index, value in enumerate(table.kern_values):
                _require_integer_range(
                    value,
                    location=(
                        f"Math kern {name!r}.{corner} value {index}"
                    ),
                    minimum=FWORD_MIN,
                    maximum=FWORD_MAX,
                )


