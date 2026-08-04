from __future__ import annotations

from fontTools.otlLib.builder import buildMathTable
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables

from .errors import CompileError
from .model import MathTablePlan


def _empty_langsys() -> otTables.LangSys:
    langsys = otTables.LangSys()
    langsys.LookupOrder = None
    langsys.ReqFeatureIndex = 0xFFFF
    langsys.FeatureIndex = []
    return langsys


def _math_script() -> otTables.Script:
    script = otTables.Script()
    script.DefaultLangSys = _empty_langsys()
    script.LangSysRecord = []
    return script


def ensure_math_script(font: TTFont) -> None:
    """Ensure GSUB contains a math/default language system."""

    if "GSUB" not in font:
        table = newTable("GSUB")
        gsub = otTables.GSUB()
        gsub.Version = 0x00010000
        gsub.ScriptList = otTables.ScriptList()
        gsub.ScriptList.ScriptRecord = []
        gsub.FeatureList = otTables.FeatureList()
        gsub.FeatureList.FeatureRecord = []
        gsub.LookupList = otTables.LookupList()
        gsub.LookupList.Lookup = []
        table.table = gsub
        font["GSUB"] = table

    gsub = font["GSUB"].table
    if gsub.ScriptList is None:
        gsub.ScriptList = otTables.ScriptList()
        gsub.ScriptList.ScriptRecord = []
    if gsub.FeatureList is None:
        gsub.FeatureList = otTables.FeatureList()
        gsub.FeatureList.FeatureRecord = []
    if gsub.LookupList is None:
        gsub.LookupList = otTables.LookupList()
        gsub.LookupList.Lookup = []

    records = gsub.ScriptList.ScriptRecord
    for record in records:
        if record.ScriptTag == "math":
            if record.Script.DefaultLangSys is None:
                record.Script.DefaultLangSys = _empty_langsys()
            return

    record = otTables.ScriptRecord()
    record.ScriptTag = "math"
    record.Script = _math_script()
    records.append(record)
    records.sort(key=lambda item: item.ScriptTag)


def apply_math_table(font: TTFont, plan: MathTablePlan) -> None:
    """Add resolved MATH data and the required GSUB math script in memory."""

    vertical = {
        base: [
            (record.glyph_name, record.full_advance)
            for record in records
        ]
        for base, records in plan.vertical_variant_records.items()
    }
    horizontal = {
        base: [
            (record.glyph_name, record.full_advance)
            for record in records
        ]
        for base, records in plan.horizontal_variant_records.items()
    }
    vertical_assemblies = {
        base: (
            tuple(
                (
                    part.glyph_name,
                    1 if part.extender else 0,
                    part.start_connector_length,
                    part.end_connector_length,
                    part.full_advance,
                )
                for part in assembly.parts
            ),
            assembly.italic_correction,
        )
        for base, assembly in plan.vertical_assemblies.items()
    }
    horizontal_assemblies = {
        base: (
            tuple(
                (
                    part.glyph_name,
                    1 if part.extender else 0,
                    part.start_connector_length,
                    part.end_connector_length,
                    part.full_advance,
                )
                for part in assembly.parts
            ),
            assembly.italic_correction,
        )
        for base, assembly in plan.horizontal_assemblies.items()
    }
    math_kerns = {}
    for glyph_name, glyph_kern in plan.kerns.items():
        corners = {}
        for attribute, table_name in (
            ("top_right", "TopRight"),
            ("top_left", "TopLeft"),
            ("bottom_right", "BottomRight"),
            ("bottom_left", "BottomLeft"),
        ):
            kern_table = getattr(glyph_kern, attribute)
            if kern_table is not None:
                corners[table_name] = (
                    list(kern_table.correction_height),
                    list(kern_table.kern_values),
                )
        math_kerns[glyph_name] = corners

    try:
        buildMathTable(
            font,
            constants=dict(plan.constants),
            italicsCorrections=dict(plan.italic_corrections) or None,
            topAccentAttachments=(
                dict(plan.top_accent_attachments) or None
            ),
            mathKerns=math_kerns or None,
            extendedShapes=set(plan.extended_shapes),
            minConnectorOverlap=plan.min_connector_overlap,
            vertGlyphVariants=vertical or None,
            horizGlyphVariants=horizontal or None,
            vertGlyphAssembly=vertical_assemblies or None,
            horizGlyphAssembly=horizontal_assemblies or None,
        )
        ensure_math_script(font)
    except Exception as error:
        raise CompileError(f"Cannot build OpenType math tables: {error}") from error
