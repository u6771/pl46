from __future__ import annotations

from collections.abc import Mapping

from ..errors import PlanError


def _ssty_feature(
    ssty: Mapping[str, tuple[str, ...]],
    glyph_names: set[str],
) -> str | None:
    if not ssty:
        return None
    rules: list[str] = []
    for base, alternates in sorted(ssty.items()):
        missing = {base, *alternates} - glyph_names
        if missing:
            raise PlanError(
                f"Ssty rule for {base!r} references unknown glyphs: "
                f"{sorted(missing)}"
            )
        if len(alternates) == 1:
            rules.append(f"    sub {base} by {alternates[0]};")
        else:
            rules.append(
                f"    sub {base} from [{alternates[0]} {alternates[1]}];"
            )
    return (
        "feature ssty {\n"
        "    script math;\n"
        "\n"
        + "\n".join(rules)
        + "\n} ssty;\n"
    )


def _merge_ssty_substitutions(
    automatic: Mapping[str, tuple[str, ...]],
    explicit: Mapping[str, tuple[str, ...]],
) -> Mapping[str, tuple[str, ...]]:
    overlap = set(automatic) & set(explicit)
    if overlap:
        raise PlanError(
            "Automatic and explicit ssty substitutions both define: "
            f"{sorted(overlap)}"
        )
    return {**automatic, **explicit}

