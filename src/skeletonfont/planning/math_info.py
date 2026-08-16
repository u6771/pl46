from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..errors import PlanError
from ..model import (
    AssembledGlyph,
    GlyphParameters,
    GlyphPlan,
    MathGlyphKernData,
)
from .glyphs import _transformed_strokes
from .roles import _GlyphRoleGroups


@dataclass(frozen=True, slots=True)
class _TopAccentAttachmentInputs:
    ordinary: Mapping[str, float]
    vertical_variant_glyphs: Mapping[str, float]
    horizontal_variant_glyphs: Mapping[str, float]

def _inherited_top_accent_attachments(
    source_attachments: Mapping[str, int],
    source_by_target: Mapping[str, str],
) -> Mapping[str, int]:
    return {
        target_name: source_attachments[source_name]
        for target_name, source_name in source_by_target.items()
        if source_name in source_attachments
    }


def _with_ssty_top_accent_attachments(
    authored_attachments: Mapping[str, float],
    source_by_target: Mapping[str, str],
) -> Mapping[str, float]:
    """Give each ssty glyph its source's authored grid coordinate.

    The target glyph later converts this coordinate using its own planned
    metrics.  An explicitly authored target value takes precedence over the
    inherited source value.
    """

    inherited = {
        target_name: authored_attachments[source_name]
        for target_name, source_name in source_by_target.items()
        if source_name in authored_attachments
        and target_name not in authored_attachments
    }
    return MappingProxyType({**inherited, **authored_attachments})


def _plan_accent_glyphs(
    glyphs: Mapping[str, AssembledGlyph],
    parameters: GlyphParameters,
) -> Mapping[str, GlyphPlan]:
    """Plan zero-advance combining accents around their authored origin."""

    return MappingProxyType(
        {
            name: GlyphPlan(
                name=glyph.name,
                codepoint=glyph.codepoint,
                source_path=glyph.source_path,
                width=0,
                strokes=_transformed_strokes(
                    glyph.skeleton,
                    grid=parameters.grid,
                    radius=parameters.radius,
                    grid_x_offset=glyph.monospace_x_offset,
                    grid_y_offset=glyph.y_offset,
                    font_x_shift=0,
                    font_y_shift=parameters.y_shift + parameters.radius,
                ),
            )
            for name, glyph in glyphs.items()
        }
    )


def _validate_italic_corrections(
    italic_corrections: Mapping[str, int],
    glyph_names: set[str],
) -> None:
    missing = set(italic_corrections) - glyph_names
    if missing:
        raise PlanError(
            "Math italic corrections reference unknown glyphs: "
            f"{sorted(missing)}"
        )


def _group_top_accent_attachments_by_role(
    accent_attachments: Mapping[str, float],
    roles: _GlyphRoleGroups,
) -> _TopAccentAttachmentInputs:
    """Validate exact glyph names and divide authored points by role."""

    grouped: dict[str, dict[str, float]] = {
        "ordinary": {},
        "vertical_variant_glyph": {},
        "horizontal_variant_glyph": {},
    }
    for name, attachment in accent_attachments.items():
        role = roles.role_by_name.get(name)
        if role is None:
            raise PlanError(
                "Math top accent attachment references a name not planned "
                f"as an assembled glyph: {name!r}."
            )
        if role not in grouped:
            raise PlanError(
                f"Math top accent attachment glyph {name!r} has unsupported "
                f"planning role {role!r}; expected an ordinary or discrete "
                "variant glyph."
            )
        grouped[role][name] = attachment
    return _TopAccentAttachmentInputs(
        ordinary=MappingProxyType(grouped["ordinary"]),
        vertical_variant_glyphs=MappingProxyType(
            grouped["vertical_variant_glyph"]
        ),
        horizontal_variant_glyphs=MappingProxyType(
            grouped["horizontal_variant_glyph"]
        ),
    )


def _validate_math_kerns_by_role(
    kerns: Mapping[str, MathGlyphKernData],
    roles: _GlyphRoleGroups,
) -> None:
    """Validate exact math-kern names against supported glyph roles."""

    supported_roles = {
        "ordinary",
        "vertical_variant_glyph",
        "horizontal_variant_glyph",
    }
    for name in kerns:
        role = roles.role_by_name.get(name)
        if role is None:
            raise PlanError(
                "Math kern references a name not planned as an assembled "
                "glyph: "
                f"{name!r}."
            )
        if role not in supported_roles:
            raise PlanError(
                f"Math kern glyph {name!r} has unsupported planning role "
                f"{role!r}; expected an ordinary or discrete variant glyph."
            )
