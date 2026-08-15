# The skeletonfont Handbook

`skeletonfont` is a command-line font builder for projects that describe glyph
strokes as normalized skeleton data. It selects and transforms those sources,
expands their centerlines into outlines, adds optional layout and publication
data, and compiles the result as a CFF OpenType font.

This handbook documents the package's project-data formats and internal build
stages for font-project authors and developers. The [root README](../README.md)
describes the PL46 font family that uses the package.

## How skeletonfont is used

In this handbook, `<project>` means the project root containing `meta/`,
`glyph_sources/`, and `data/`. Each `meta/<meta-name>.json` describes one output
font: it supplies font-wide settings, selects reusable glyph sources, and may
reference auxiliary data files.

```text
meta/<meta-name>.json
    |-- font-wide settings
    |-- source_rules ------------> glyph_sources/
    `-- optional file references -> data/
                    |
        skeletonfont-build <meta-name>
                    |
        build/otf/<output_stem>.otf
```

From `<project>`, a single font is built by passing its meta name to the CLI:

```text
skeletonfont-build <meta-name>
```

For example, `skeletonfont-build math` reads `meta/math.json`, loads the glyph
sources and auxiliary files selected by that meta, and writes
`build/otf/PL46-Math.otf`. For environment setup, batch builds, output-directory
selection, and complete CLI syntax, see [The skeletonfont Build
Guide](building.md). The remaining sections describe the data formats and each
stage of this process.

## Contents

- [How skeletonfont is used](#how-skeletonfont-is-used)
- [Build pipeline](#build-pipeline)
  - [Module boundaries](#module-boundaries)
- [Project data](#project-data)
  - [Directory layout](#directory-layout)
  - [Units](#units)
  - [JSON conventions](#json-conventions)
- [Glyph-source schema](#glyph-source-schema)
- [Meta schema](#meta-schema)
  - [File-field path resolution](#file-field-path-resolution)
  - [MATH table references](#math-table-references)
  - [Release-info schema](#release-info-schema)
- [Assembly](#assembly)
  - [Source rules, domains, and mappings](#source-rules-domains-and-mappings)
  - [Glyph aliases](#glyph-aliases)
  - [ssty generators](#ssty-generators)
- [Planning](#planning)
  - [Planning roles](#planning-roles)
  - [Coordinates, widths, and edge scales](#coordinates-widths-and-edge-scales)
  - [Glyph spacing configuration](#glyph-spacing-configuration)
  - [Kerning](#kerning)
- [MATH planning](#math-planning)
  - [Math constants](#math-constants)
  - [Discrete variants and assemblies](#discrete-variants-and-assemblies)
  - [Italic corrections](#italic-corrections)
  - [Top accent attachments](#top-accent-attachments)
  - [MathKern](#mathkern)
- [Rendering and geometry](#rendering-and-geometry)
  - [UFO rendering](#ufo-rendering)
  - [Stroke expansion](#stroke-expansion)
- [Compilation and output](#compilation-and-output)
- [Batch orchestration and testing](#batch-orchestration-and-testing)

## Build pipeline

One build passes through five stages:

```text
JSON files
    -> load
    -> assemble
    -> plan
    -> render
    -> compile and save
```

| Stage | Input | Responsibility | Output |
| --- | --- | --- | --- |
| load | project JSON | parse, normalize, and validate individual files | immutable input objects |
| assemble | `FontMeta` and glyph catalogs | select, map, replace, alias, and generate the glyph set | `AssembledFont` |
| plan | assembled glyphs and loaded auxiliary data | resolve roles, metrics, transforms, spacing, and MATH records | `FontPlan` |
| render | `FontPlan` and optional `ReleaseInfo` | expand skeletons and create an in-memory UFO with font metadata | `ufoLib2.Font` |
| compile | UFO and optional MATH plan | compile CFF OpenType data and attach MATH | `TTFont`, then one OTF file |

No stage reads a file that belongs to a later stage. In particular,
`plan_font()` performs no file I/O, and rendering does not recalculate metrics.

### Module boundaries

`loader.py` and `planner.py` are the package's facade modules. Their
implementations are split by domain:

```text
loading/
  _json.py   meta.py   release.py   glyphs.py   layout.py   math.py

planning/
  core.py    glyphs.py   roles.py   spacing.py   ssty.py
  math_info.py   assemblies.py   validation.py
```

Callers should import loading and planning entry points from
`skeletonfont.loader` and `skeletonfont.planner`. The internal module layout is
not a compatibility promise.

## Project data

### Directory layout

The project directories consumed by the package are:

| Directory | Contents |
| --- | --- |
| `meta/` | one JSON file per font build |
| `glyph_sources/` | reusable glyph-source directories |
| `data/accent/` | combining-accent role lists |
| `data/glyph_config/` | per-glyph spacing adjustments |
| `data/kerning/` | kerning groups and pairs |
| `data/release_info/` | optional shared publication metadata |
| `data/ssty/` | explicitly authored ssty substitutions |
| `data/math_table/constants/` | complete MathConstants objects |
| `data/math_table/variants/` | discrete variants and assemblies |
| `data/math_table/italics_correction/` | per-glyph italic corrections |
| `data/math_table/accent_attachment/` | per-glyph top-accent attachment points |
| `data/math_table/kern/` | per-glyph MathKern records |

### Units

The schemas use three kinds of values:

| Unit | Examples |
| --- | --- |
| design grid units | skeleton points, `x_extent`, glyph offsets, top-accent authored points, connector extents |
| font units | `thickness`, spacing, `monospace_width`, `y_shift`, MATH constants, italic corrections, MathKern values, `min_connector_overlap` |
| dimensionless scales | stroke and source-rule `thickness_scale`, assembly edge scales, `point_radius_scale` |

`grid` converts design coordinates to font units. Authored `thickness` is the
full stroke thickness; loading stores `GlyphParameters.radius = thickness / 2`.

### JSON conventions

All JSON objects reject duplicate keys. Unknown fields are rejected rather than
ignored. Glyph-like names use the characters `[A-Za-z0-9_.-]` only; they cannot
be empty and cannot contain whitespace, `/`, or `@`. A filename field may omit
the `.json` suffix, which the loader adds during normalization. An optional
field uses its default only when the field is omitted; an explicit `null` is an
error unless the schema documents a data-specific meaning. The project-schema
exception is glyph-source `unicode`, where `null` means unencoded.

## Glyph-source schema

Every source has `name` and `unicode`, followed by exactly one geometry form.
`unicode` accepts a hexadecimal string, an integer, or `null`.

A stroked glyph writes explicit offsets and a non-empty skeleton. This is the
repository's [`A_0041.json`](../glyph_sources/latin/upright_latin/A_0041.json),
with optional stroke fields expanded to their defaults:

```json
{
  "name": "A",
  "unicode": "0041",
  "monospace_x_offset": -2,
  "y_offset": 0,
  "skeleton": [
    {
      "centerline": [[0, 0], [0, 3], [2, 6], [4, 3], [4, 0]],
      "thickness_scale": 1,
      "start_cap": "round",
      "end_cap": "round",
      "filled": false
    },
    {
      "centerline": [[0, 2], [4, 2]],
      "thickness_scale": 1,
      "start_cap": "flat",
      "end_cap": "flat",
      "filled": false
    }
  ]
}
```

`centerline` is required. The other stroke fields default to `1`, `"round"`,
`"round"`, and `false`. Across the whole glyph, the minimum authored x and y
coordinates must both be zero. Loading derives `x_extent` and `y_extent` from
the skeleton; they are not authored for a stroked glyph.

A glyph without strokes instead writes only its horizontal design extent, as in
the repository's [`space_0020.json`](../glyph_sources/latin/space_0020.json):

```json
{
  "name": "space",
  "unicode": "0020",
  "x_extent": 4
}
```

For this form, `x_extent` must be non-negative. `skeleton`,
`monospace_x_offset`, and `y_offset` are forbidden because the offsets cannot
move any outline. The immutable `GlyphSource` still has both offset attributes,
normalized to zero, so later code does not need a second object type.

`load_glyph_source_directory()` searches a selected directory recursively.
Within that directory, duplicate glyph names and duplicate non-null Unicode
codepoints are errors.

## Meta schema

Each meta file describes one output font and provides the build's font-wide
settings, glyph-selection rules, and auxiliary-data references. Project meta
files use the following canonical field order for consistency. JSON parsing
does not otherwise depend on object-key order.

| Group | Fields, in order |
| --- | --- |
| build output | `output_stem` |
| font identity | `family`, `style`, `weight_class` |
| font metrics | `units_per_em`, `ascender`, `descender`, `cap_height`, `x_height` |
| geometry | `grid`, `thickness`, `point_radius_scale`, `y_shift`, `use_scaled_edge_thickness` |
| horizontal metrics | `monospace_width`, `left_spacing`, `right_spacing` |
| glyph set | `source_rules`, `glyph_alias_generators`, `ssty_generators` |
| glyph-related OpenType data | `accent_file`, `ssty_file`, `math_table` |
| glyph adjustments | `glyph_config_file` |
| inter-glyph layout | `kerning_file` |
| publication | `release_info_file` |

The required fields are `family`, `style`, `weight_class`, `units_per_em`,
`ascender`, `descender`, `cap_height`, `x_height`, `grid`, `thickness`, and a
non-empty `source_rules` array. `weight_class` is written explicitly in every
meta and must be 1 through 1000; there is no default or inherited family value.
The conventional values include 400 for Regular and 700 for Bold.
`units_per_em` must be 16 through 16384. Serialized font metrics must fit the
signed OpenType FWORD range.

For example, the repository's [minimal project
fixture](../tests/fixtures/minimal_project/) uses this complete build meta. The
first source rule selects its required unencoded `.notdef`; the second selects
the encoded glyphs used by the test build:

```json
{
  "family": "Test",
  "style": "Regular",
  "weight_class": 400,
  "units_per_em": 1000,
  "ascender": 850,
  "descender": -200,
  "cap_height": 650,
  "x_height": 450,
  "grid": 100,
  "thickness": 50,
  "monospace_width": 600,
  "source_rules": [
    {
      "source_directory": "notdef",
      "include_unencoded": true
    },
    {
      "source_directory": "basic"
    }
  ]
}
```

Optional defaults are:

| Field | Default when omitted |
| --- | --- |
| `output_stem` | normalized from `family` and `style` |
| `point_radius_scale` | `1.6` |
| `y_shift` | `0` |
| `use_scaled_edge_thickness` | `true` |
| `monospace_width` | absent; use proportional ordinary metrics |
| `left_spacing`, `right_spacing` | `0` |
| `glyph_alias_generators` | no aliases |
| `ssty_generators` | no generated script-style alternates |
| `accent_file`, `ssty_file` | no file |
| `math_table` | MATH disabled |
| `glyph_config_file`, `kerning_file`, `release_info_file` | no file |

These defaults apply only when the field is omitted. Explicit `null` does not
select a default. `monospace_width` is enabled by presence.

`monospace_width` controls ordinary-glyph layout, while the font-wide
`post.isFixedPitch` classification is derived rather than authored. It is
non-zero only when `monospace_width` is present and MATH is disabled. A
non-empty `math_table` always makes the font non-fixed because variant bases,
discrete variants, and assembly parts may use proportional advances. Zero-width
combining accents do not prevent a non-MATH monospace build from being fixed
pitch.

### File-field path resolution

All file fields are resolved relative to the project directory, not relative to
the meta file or the installed Python package. A missing `.json` suffix is
added automatically.

| Meta field | Resolved path |
| --- | --- |
| meta name `<name>` | `meta/<name>.json` |
| `source_rules[].source_directory` | `glyph_sources/<source_directory>/` |
| `accent_file` | `data/accent/<accent_file>` |
| `ssty_file` | `data/ssty/<ssty_file>` |
| `math_table.constants_file` | `data/math_table/constants/<constants_file>` |
| `math_table.variants_file` | `data/math_table/variants/<variants_file>` |
| `math_table.italics_correction_file` | `data/math_table/italics_correction/<italics_correction_file>` |
| `math_table.accent_attachment_file` | `data/math_table/accent_attachment/<accent_attachment_file>` |
| `math_table.kern_file` | `data/math_table/kern/<kern_file>` |
| `glyph_config_file` | `data/glyph_config/<glyph_config_file>` |
| `kerning_file` | `data/kerning/<kerning_file>` |
| `release_info_file` | `data/release_info/<release_info_file>` |

For example, `"kerning_file": "script"` loads
`<project>/data/kerning/script.json`. Directory-valued
`source_directory` is different: it is not a filename and may identify a safe
nested path such as `"math/delimiters"`.

### MATH table references

`math_table` is either absent or an object containing filenames. Absence
disables MATH. An object enables MATH and must explicitly contain
`constants_file`; an empty object is invalid. The optional fields are
`variants_file`, `italics_correction_file`, `accent_attachment_file`, and
`kern_file`. For example, [`meta/math.json`](../meta/math.json) uses:

```json
{
  "math_table": {
    "constants_file": "math.json",
    "variants_file": "math.json",
    "italics_correction_file": "math.json",
    "accent_attachment_file": "math.json"
  }
}
```

There is no separate MATH `enabled` switch. The referenced file schemas and
their compilation into the OpenType MATH table are described under [MATH
planning](#math-planning).

### Release-info schema

`release_info_file` is optional because publication metadata is not needed to
design or test a font. A referenced file is a non-empty collection of
independent optional fields: `skeletonfont` validates and writes only the
fields that appear. Unknown fields, duplicate JSON keys, and explicit `null`
values are errors. There is no separate release-mode CLI switch.

This fixture supplies every supported field:
[`data/release_info/ofl.json`](../tests/fixtures/minimal_project/data/release_info/ofl.json):

```json
{
  "version": "1.000",
  "copyright": "Copyright 2026 Test Author",
  "designer": "Test Author",
  "designer_url": "https://example.com/designer",
  "manufacturer": "Test Foundry",
  "manufacturer_url": "https://example.com/foundry",
  "description": "A release-info integration test font.",
  "trademark": "Test is a trademark of Test Author.",
  "vendor_id": "TEST",
  "license": {
    "identifier": "OFL-1.1",
    "url": "https://openfontlicense.org"
  },
  "embedding_permissions": "installable"
}
```

The fields map independently to font metadata:

| Release-info field | Output |
| --- | --- |
| `version` | name ID 5, CFF version, and `head.fontRevision` |
| `copyright` | name ID 0 and CFF Copyright |
| `designer`, `designer_url` | name IDs 9 and 12 |
| `manufacturer`, `manufacturer_url` | name IDs 8 and 11 |
| `description` | name ID 10 |
| `trademark` | name ID 7 |
| `vendor_id` | `OS/2.achVendID` |
| `license` | name ID 13 and optional name ID 14 |
| `embedding_permissions` | `OS/2.fsType` |

All text values must be non-empty strings. URLs must be absolute HTTP or HTTPS
URLs. `vendor_id` must contain exactly four ASCII letters or digits. A field
that is not needed is omitted rather than set to `null`.

The release `version` is the single authored version source. For example,
`"1.023"` becomes name ID 5 `Version 1.023`, the corresponding CFF version,
and the nearest representable 16.16 fixed-point `head.fontRevision`. Name ID 5
preserves the authored three decimal digits exactly; `head.fontRevision` may
show binary fixed-point rounding when read back—for example, `0.100` becomes
approximately `0.1000061`. The major component must be at most 32767. The minor
component is always exactly three decimal digits in JSON, including trailing
zeros.

The `license` object requires `identifier`; its optional `url` produces name ID
14. Identifiers are resolved to known name-table text, and the current
implementation supports `OFL-1.1`. The old field name `id` is not accepted.
When `OFL-1.1` is selected, `embedding_permissions` must also be present and
equal `installable`; this requirement prevents the compiler's default `fsType`
from contradicting the selected license. Without a license,
`embedding_permissions` remains independently optional.

The authored `copyright` string is written unchanged. When a project declares
Reserved Font Names, it must include the complete RFN statement directly in
`copyright`; `skeletonfont` does not parse or generate that statement. The full
standalone license remains a project packaging responsibility: release-info
loading neither reads nor generates `OFL.txt`.

`embedding_permissions` accepts the following readable values:

| Value | OS/2 `fsType` |
| --- | ---: |
| `installable` | 0 |
| `restricted` | 2 |
| `preview_and_print` | 4 |
| `editable` | 8 |

Release information is shared by reference, so several build metas can name
the same file without duplicating version or licensing text. Once a meta names
a release-info file, a missing file, empty object, unsupported identifier, or
invalid value is a build error.

Omitting `release_info_file`, or omitting an individual field from a referenced
file, leaves that field unset. The current `ufo2ft` defaults include name ID 5
`Version 0.000`, `head.fontRevision` 0.0, vendor ID `NONE`, and `fsType` 4 when
their corresponding release fields are absent. These are compiler defaults,
not values inferred by `skeletonfont`.

## Assembly

### Source rules, domains, and mappings

`GlyphCatalog` loads each `glyph_sources/<source_directory>` at most once and
caches its immutable glyph mapping across builds. Source rules are evaluated in
meta order. This source rule is taken from [`meta/math.json`](../meta/math.json):

```json
{
  "source_directory": "script",
  "unicode_domain": [
    ["0041", "005A"]
  ],
  "mapping_name": "upright_latin_to_script_latin"
}
```

Only `source_directory` is required. An encoded source matches when its
codepoint is in `unicode_domain`; omitting the domain accepts every encoded
source. An unencoded source is controlled independently by `include_unencoded`,
whose default is `false`. Explicit `null` is invalid. An empty domain array
selects no encoded glyphs, so `[]` together with `include_unencoded: true`
selects only unencoded glyphs.

`unicode_domain` accepts either one registered name or an array containing
registered names and literal ranges. The source rule above uses this literal
range:

```json
{
  "unicode_domain": [
    ["0041", "005A"]
  ]
}
```

A one-element nested array is a literal singleton. A bare string is always a
registered name. The loader unions overlapping and adjacent ranges into a
minimal sorted `UnicodeDomain`; it never expands a range into a set of all its
codepoints. The registered names are `ascii_digits`, `upright_latin`,
`upright_greek`, `italic_latin`, `italic_greek`, `script_latin`,
`fraktur_latin`, `blackboard_latin`, `bold_latin`, `bold_digits`, and
`bold_greek`. Their
explicit definitions in `unicode_domains.py` are authoritative.

If `mapping_name` is present, the selected source's `(name, codepoint)` identity
is passed through a `GlyphMapping`. A source outside that mapping is skipped; an
unencoded source cannot pass through a codepoint mapping. Mathematical alphabet
mapping names state both sides, such as `upright_latin_to_italic_latin`, and
produce semantic glyph names such as `A.italic`, `A.script`, and `A.fraktur`.
Mappings declare optional source and target domains, which are validated once
when the registry is created. An internal mapping may omit either domain
constraint, which skips that registry check. Encoded mapping targets must be
one-to-one.

The registered mappings are:

| Mapping name | Source domain | Target domain | Target-name suffix |
| --- | --- | --- | --- |
| `upright_latin_to_italic_latin` | `upright_latin` | `italic_latin` | `.italic` |
| `upright_greek_to_italic_greek` | `upright_greek` | `italic_greek` | `.italic` |
| `upright_latin_to_script_latin` | `upright_latin` | `script_latin` | `.script` |
| `upright_latin_to_fraktur_latin` | `upright_latin` | `fraktur_latin` | `.fraktur` |
| `upright_latin_to_blackboard_latin` | `upright_latin` | `blackboard_latin` | `.blackboard` |
| `upright_latin_to_bold_latin` | `upright_latin` | `bold_latin` | `.bold` |
| `ascii_digits_to_bold_digits` | `ascii_digits` | `bold_digits` | `.bold` |
| `upright_greek_to_bold_greek` | `upright_greek` | `bold_greek` | `.bold` |

`thickness_scale` defaults to `1` and must be positive. A non-unit value is
multiplied into every selected stroke's own `thickness_scale` while creating the
immutable `AssembledGlyph`. The unit case reuses the existing skeleton tuple.

As each result is merged, both its glyph name and non-null Unicode are checked.
Without `replace_existing`, either conflict is an error. With
`replace_existing: true`, the later result removes all conflicting earlier
entries before it is inserted.

### Glyph aliases

After source rules, ordered `glyph_alias_generators` run registered mappings over
the assembled encoded glyphs. Missing source codepoints are ignored. A target
codepoint that is already occupied is also skipped; a target name collision is
an error. The resulting `GlyphAlias` contains only a source name and target
identity. It has no skeleton and is not assigned a planning role. Generator
names use the same registered-mapping table listed above.

For example, [`meta/math.json`](../meta/math.json) configures these two alias
generators:

```json
{
  "glyph_alias_generators": [
    "upright_latin_to_italic_latin",
    "upright_greek_to_italic_greek"
  ]
}
```

If the assembled set contains `A` at U+0041 but does not already contain the
mapping target, this creates an alias named `A.italic` at U+1D434 whose
`source_name` is `A`. It does not create a second `AssembledGlyph` or rescale
the source skeleton.

After normal glyphs have been rendered, an alias copies the rendered source
glyph, including its width and outlines, and changes only its name and Unicode.
This avoids repeating stroke expansion and boolean operations.

### ssty generators

Ordered `ssty_generators` create real unencoded `AssembledGlyph` alternates and
the GSUB substitutions that refer to them. [`meta/math.json`](../meta/math.json)
uses this generator:

```json
{
  "ssty_generators": [
    {
      "unicode_domain": [
        "ascii_digits",
        "upright_latin",
        "upright_greek",
        "italic_latin",
        "italic_greek",
        "script_latin",
        "fraktur_latin"
      ],
      "ssty_alternate_name": "st",
      "thickness_scale": 1.2
    }
  ]
}
```

All three fields are required and cannot be `null`. `unicode_domain` accepts the
same names, ranges, and unions as a source-rule domain. An empty array is an
explicit no-op and generates no alternates. Current alternate namers are `st`
and `sts`, which append `.st` and `.sts` to the base name. Eligible bases include
both assembled encoded glyphs and encoded aliases; an alias uses its assembled
source's geometry but its own target name as the GSUB base. Each generator
selects bases by Unicode, scales the original assembled skeleton, and creates an
unencoded alternate. Generated alternates are not fed into later generators.

A base may receive at most two alternates. Generator order defines their ssty
levels. Any generated-name collision is an error. `AssembledFont` carries the
generated glyphs, automatic substitution mapping, and each alternate's
assembled source name into planning.

An optional `ssty_file` under `data/ssty/` supplies an explicit mapping from a
base to one or two alternates. Automatic and explicit mappings may coexist, but
they cannot both define the same base. ssty is a GSUB feature and does not
require a MATH table. For example, these entries are taken from
[`data/ssty/math.json`](../data/ssty/math.json):

```json
{
  "minute": ["minute.st"],
  "uni2033": ["uni2033.st"]
}
```

Unlike an ssty generator, this file creates no glyphs. Every base and alternate
in it must already exist in the final assembled-or-alias glyph set.

## Planning

`plan_font()` receives an `AssembledFont` and already-loaded auxiliary data. It
returns a `FontPlan` in which every glyph width, transformed centerline, stroke
radius, MATH advance, and table value has been resolved. It performs no file
I/O.

### Planning roles

Aliases are excluded because they copy a rendered glyph. Every assembled glyph,
including an ssty alternate, receives one of these roles:

| Role | Membership | Metric behavior |
| --- | --- | --- |
| ordinary | not referenced by a special role | proportional or monospace according to meta |
| accent | listed by `accent_file` | zero advance; positioned around the combining origin |
| vertical variant glyph | base or discrete alternate in a vertical construction | proportional; vertical MATH FullAdvance |
| horizontal variant glyph | base or discrete alternate in a horizontal construction | proportional; horizontal MATH FullAdvance |
| vertical part | used by a vertical assembly | shared owner layout and vertical FullAdvance |
| horizontal part | used by a horizontal assembly | width equals horizontal FullAdvance |

Unknown role references are rejected. Roles are otherwise disjoint, including
between vertical and horizontal constructions. The one exception is an accent
that is itself the base key of a horizontal construction: it remains in the
accent role and is planned once at zero width, while planning separately measures
only the horizontal FullAdvance needed by its construction. Its discrete
alternates remain horizontal variant glyphs.

An `accent_file` is a non-empty array of exact assembled glyph names under
`data/accent/`. The following entries occur together in
[`data/accent/math.json`](../data/accent/math.json). Accent outlines are transformed with
`monospace_x_offset` around the combining origin. Accents cannot receive glyph
spacing adjustments, top-accent attachments, or MathKern data.

```json
[
  "circumflexcmb",
  "tildecomb"
]
```

### Coordinates, widths, and edge scales

Source centerlines and offsets are in design grid units. `StrokePlan`
centerlines are in font units. During transformation, consecutive coincident
points are removed. A repeated endpoint produces a closed stroke when neither
end cap is flat; the repeated endpoint itself is then omitted. `filled: true`
is legal only for a closed stroke. Each final stroke radius is:

```text
font radius * effective stroke thickness_scale
```

Ordinary proportional width is:

```text
x_extent * grid
+ left edge contribution + right edge contribution
+ effective left spacing + effective right spacing
```

A stroked proportional glyph is shifted right by its left spacing and left edge
contribution. Its `monospace_x_offset` does not move the outline. A no-stroke
glyph has no edge contributions, so its width is
`x_extent * grid + left spacing + right spacing`.

Ordinary monospace glyphs instead use:

```text
width = monospace_width + left_spacing + right_spacing
x = (source_x + monospace_x_offset) * grid
    + left_spacing + monospace_width / 2
```

This makes authored x=0 the centered monospace design axis. Per-glyph spacing
adjustments are not allowed for ordinary monospace glyphs, so every ordinary
glyph retains the same advance.

For accents:

```text
width = 0
x = (source_x + monospace_x_offset) * grid
```

Discrete MATH variants always use proportional planning, even in a monospace
font. Their glyph width contains horizontal spacing, but their MATH FullAdvance
measures only the construction axis and does not include spacing. Horizontal
assembly parts have no horizontal spacing. Vertical parts receive the common
width and spacing of their owner layout.

`y_offset` is applied in design units to ordinary glyphs, accents, discrete
variants, and both kinds of assembly part. Ordinary glyphs, accents, discrete
variants, and horizontal parts then use:

```text
y = (source_y + y_offset) * grid + y_shift + radius
```

Vertical parts instead align the start edge of their vertical FullAdvance and
therefore do not use the ordinary meta-level `y_shift` formula.

When `use_scaled_edge_thickness` is `true`, normal horizontal glyph metrics and
vertical-part common widths use the greatest stroke `thickness_scale` touching
each relevant x edge. When it is `false`, those two horizontal edge
contributions use scale `1`. MATH growth-axis FullAdvances still use measured or
explicitly authored part-edge scales; the option does not erase construction
geometry.

`point_radius_scale` affects only the rendered outline of an isolated-point
stroke; it does not participate in edge-scale measurement or scaled-edge metric
contributions.

### Glyph spacing configuration

A `glyph_config_file` under `data/glyph_config/` maps a glyph selector to
optional additive `left_adjustment` and `right_adjustment` values. These are
font units added to the meta-level spacings. The following entries come from
[`data/glyph_config/math.json`](../data/glyph_config/math.json):

```json
{
  "parenleft@variants": {
    "left_adjustment": 50
  },
  "bar@variants": {
    "left_adjustment": 50,
    "right_adjustment": 50
  }
}
```

Selectors have these meanings:

| Selector | Members | Supported constructions |
| --- | --- | --- |
| exact glyph name | that glyph only | ordinary proportional and discrete variants |
| `base@variant_glyphs` | base plus all discrete variants | vertical or horizontal |
| `base@parts` | assembly parts, excluding the base | vertical only |
| `base@variants` | discrete variants plus assembly parts | vertical only |

A base that names both a vertical and horizontal construction is ambiguous and
cannot use a group selector. Assembly parts cannot be configured by exact name.
Horizontal parts, accents, and ordinary monospace glyphs cannot receive spacing
adjustments. A variant group containing an accent base is rejected as a whole;
its discrete variants may still be configured individually.

Configuration order never creates precedence. Exact and group assignments may
not overlap. `variant_glyphs` and `parts` are the only permitted pair of groups
on one base because their members are disjoint. If a group assignment contains a
variant or part shared by multiple owner constructions, every owner must receive
the same effective group adjustment. A missing owner assignment or a different
value is an error. An exact assignment to a shared discrete variant is exempt
because its target is unambiguous.

### Kerning

Kerning JSON has optional `groups` and `pairs` fields. Left groups must be named
`public.kern1.*`; right groups must be named `public.kern2.*`. A glyph may belong
to at most one group on each side, and every named group must contain at least
one glyph. The `groups` object and `pairs` array may themselves be empty. A pair
is `[left, right, value]`; it cannot put a right group on the left or a left
group on the right, and duplicate pairs are rejected. This self-contained
subset comes from
[`data/kerning/fraktur.json`](../data/kerning/fraktur.json):

```json
{
  "groups": {
    "public.kern1.spur": ["a", "i", "l", "m", "n", "u"],
    "public.kern2.spur": ["i", "j", "m", "n", "r"]
  },
  "pairs": [
    ["public.kern1.spur", "public.kern2.spur", -100],
    ["public.kern1.spur", "z", -100],
    ["s", "public.kern2.spur", -50],
    ["f", "z", -50]
  ]
}
```

Group names may appear only on their matching side; exact glyph names may be
used directly on either side.

Loading validates the structure and signed FWORD range. Planning repeats the
structural validation for directly constructed `KerningData` and verifies every
glyph and group reference against the final assembled-or-alias glyph set. The
renderer then copies the validated groups and pairs into the UFO.

## MATH planning

The data described in this section is compiled into the OpenType MATH table.
The OpenType [MATH table
specification](https://learn.microsoft.com/en-us/typography/opentype/spec/math)
defines the typographic meaning of its constants, per-glyph information,
variants, and assemblies. This handbook describes how `skeletonfont`
represents, validates, and processes that information in project JSON.

### Math constants

Enabling `math_table` always loads a complete MathConstants object. The file
must contain exactly the names in `math_schema.MATH_CONSTANT_NAMES`; see the
project's complete [`math.json`](../data/math_table/constants/math.json) for an
authored example. Device-table adjustments are not authored in this JSON
schema. `DelimitedSubFormulaMinHeight` and
`DisplayOperatorMinHeight` use unsigned UFWORD; the other constants use signed
FWORD.

### Discrete variants and assemblies

An optional variants file has this outer form. This self-contained subset uses
the `integral` construction from
[`data/math_table/variants/math.json`](../data/math_table/variants/math.json):

```json
{
  "min_connector_overlap": 25,
  "vertical": {
    "integral": {
      "variant_glyphs": ["integral.v1"]
    }
  },
  "horizontal": {}
}
```

`min_connector_overlap` is required when the file exists and is already in font
units. The axis mappings may be omitted. Every construction key is its base.
`variant_glyphs` may be omitted or empty; the resulting construction still has
a base record. Variant records contain the base and discrete variants sorted by
resolved FullAdvance.

An assembly adds a non-empty `parts` array. Without `parts`,
`italic_correction` is forbidden. With parts, assembly italic correction
defaults to zero. Each part requires `glyph`, grid-unit
`start_connector_extent`, grid-unit `end_connector_extent`, and `extender`.
Optional vertical edge fields are `bottom_scale` and `top_scale`; optional
horizontal fields are `left_scale` and `right_scale`. An omitted scale is
measured from strokes touching that edge, while an explicit non-negative value,
including zero, overrides the measurement.

For example, the same file's `parenleft` construction has seven discrete
variants and a three-part assembly. Part order is preserved in the emitted
assembly:

```json
{
  "min_connector_overlap": 25,
  "vertical": {
    "parenleft": {
      "variant_glyphs": [
        "parenleft.v1",
        "parenleft.v2",
        "parenleft.v3",
        "parenleft.v4",
        "parenleft.v5",
        "parenleft.v6",
        "parenleft.v7"
      ],
      "parts": [
        {
          "glyph": "uni239D",
          "start_connector_extent": 0,
          "end_connector_extent": 2,
          "top_scale": 0,
          "extender": false
        },
        {
          "glyph": "uni239C",
          "start_connector_extent": 4,
          "end_connector_extent": 4,
          "top_scale": 0,
          "bottom_scale": 0,
          "extender": true
        },
        {
          "glyph": "uni239B",
          "start_connector_extent": 2,
          "end_connector_extent": 0,
          "bottom_scale": 0,
          "extender": false
        }
      ]
    }
  },
  "horizontal": {}
}
```

Connector extents are multiplied by `grid`, must not exceed the part's
FullAdvance, and must be able to provide `min_connector_overlap` for adjacent
parts and self-overlapping extenders. A construction cannot use its own base as
a part.

Vertical planning overlays all parts after applying their
`monospace_x_offset`, finds common centerline x bounds, and resolves common left
and right edge scales. Every part in the construction receives the same width
and x layout. If a vertical part is shared, all owner layouts must be identical.
For either axis, every use of a shared part must provide identical optional
growth-axis edge scales. Connector lengths and `extender` remain properties of
each part occurrence and may differ.

Each unique part is transformed once. Each construction retains its own ordered
part records. Bases of vertical constructions are emitted in MATH
`ExtendedShapeCoverage`.

### Italic corrections

An optional italics-correction file is a non-empty mapping from exact final glyph
names to non-negative font-unit integers. These entries are taken from
[`data/math_table/italics_correction/math.json`](../data/math_table/italics_correction/math.json):

```json
{
  "integral": 200,
  "integral.v1": 200
}
```

There is no selector expansion. Every required glyph, including each discrete
variant, must be listed explicitly. References may name any final assembled or
alias glyph and are written to `MathItalicsCorrectionInfo`.

### Top accent attachments

An optional accent-attachment file maps exact assembled glyph names to authored
grid-coordinate points. These entries are taken from
[`data/math_table/accent_attachment/math.json`](../data/math_table/accent_attachment/math.json):

```json
{
  "f": 0.5,
  "f.italic": 1,
  "j": 1
}
```

Only ordinary and vertical/horizontal discrete-variant roles are supported.
Combining accents and assembly parts are rejected. An ssty-generated glyph is an
ordinary assembled glyph and may be listed explicitly. Otherwise, if its source
has an authored point, it inherits that grid coordinate and recalculates the
final point using its own scaled outline; an explicitly authored target value
wins.

For proportional ordinary and discrete-variant glyphs:

```text
(attachment - monospace_x_offset) * grid
+ resolved left edge scale * radius
+ effective left spacing
```

For ordinary monospace glyphs:

```text
(attachment + monospace_x_offset) * grid
+ left_spacing + monospace_width / 2
```

A no-stroke proportional glyph has normalized zero offsets and no edge radius,
so it uses `attachment * grid + effective left spacing`. Final points are
rounded and checked as signed FWORD values before being written to
`MathTopAccentAttachment`.

Aliases cannot be configured directly. An alias inherits its assembled source's
already planned font-unit attachment through one direct source-to-alias step.

### MathKern

An optional MathKern file uses exact assembled glyph names. Selectors are not
accepted, and only ordinary or vertical/horizontal discrete-variant roles are
supported. Combining accents and parts are rejected. Aliases cannot be
configured directly; each alias inherits its configured assembled source's
complete MathKern value. ssty glyphs do not receive special inheritance because
they are independently planned assembled glyphs and can be configured by their
own exact names.

Each glyph defines at least one of `top_right`, `top_left`, `bottom_right`, and
`bottom_left`. This entry comes from
[`data/math_table/kern/sample.json`](../data/math_table/kern/sample.json):

```json
{
  "F": {
    "bottom_right": {
      "correction_height": [],
      "kern_values": [-200]
    }
  }
}
```

`correction_height` must be a strictly increasing signed-FWORD integer array.
`kern_values` is another signed-FWORD integer array containing exactly one more
entry. An empty height array therefore describes a constant kern.

## Rendering and geometry

### UFO rendering

`render_font()` creates an in-memory `ufoLib2.Font`, writes the explicit
`weight_class`, writes the derived fixed-pitch classification, copies font
metrics and planned widths, expands every `StrokePlan`, then creates glyph
aliases. When supplied, `ReleaseInfo` is mapped to UFO version, name, vendor,
and embedding-permission fields before compilation. Rendering does not load
configuration, recalculate metrics, save a UFO, or compile an OTF. Kerning and
the planned ssty feature text are copied into the UFO.

`.notdef` is a normal unencoded source glyph through assembly, planning, and
rendering. Assembly fails if it is absent.

### Stroke expansion

The cubic geometry layer expands each stroke independently. Open centerlines use
cubic round joins and independently selected round or flat caps. An isolated
point becomes a cubic circle using `point_radius_scale`. A closed centerline
produces either a hollow stroke or a filled shape. Expanded strokes enter one
n-ary pathops union and are simplified once, avoiding order-dependent pairwise
boolean results.

For a filled closed centerline, signed area determines winding and which offset
side is the outer contour. Only the outer contour is emitted. Such input must
have non-zero signed area and is expected to be simple and non-self-intersecting.
Circular arcs preserve their supplied endpoints and compute only their cubic
control points trigonometrically.

`geometry.py` is the stable rendering boundary and delegates to the cubic
stroke-expansion implementation. `skia-pathops` is used for path storage, n-ary
union, and final simplification; it is not a second stroke-expansion backend.

## Compilation and output

`compile_font()` passes the in-memory UFO directly to `ufo2ft.compileOTF()` and
returns an in-memory CFF `TTFont`. UFO publication metadata becomes OpenType
name records, `head.fontRevision`, OS/2 `usWeightClass`, `achVendID`, and
`fsType`, plus `post.isFixedPitch`. Compilation keeps overlaps because
rendering has already unioned each glyph, preserves planned glyph names, and
does not mutate the input UFO.

`.notdef` is explicitly ordered at GID 0. Other encoded glyphs are ordered by
ascending Unicode, followed by unencoded glyphs in glyph-name order. GID
assignment is therefore independent of source-rule, source-file, and planning
role order.

When a MATH plan exists, `apply_math_table()` writes constants, italic
corrections, top-accent attachments, MathKern records, extended-shape coverage,
vertical and horizontal variant records, and optional assemblies through
`fontTools.otlLib.builder.buildMathTable()`. It also ensures that GSUB contains a
`math/dflt` language system. ssty feature text itself is produced during
planning and compiled with the UFO's other GSUB data.

`save_otf()` saves to a temporary `.otf` in the destination directory and then
atomically replaces the requested output. A failure removes the temporary file
and leaves an existing output untouched.

## Batch orchestration and testing

For installation, command-line usage, and the test command, see
[The skeletonfont Build Guide](building.md).

The CLI passes explicitly supplied meta names to the batch builder, or reads
them from the non-empty `build_list.json` when no names are supplied. Before a
batch reads glyph sources or writes fonts, it normalizes all meta names,
rejects duplicate names, loads every meta and referenced release-info file, and
rejects case-insensitive `output_stem` collisions. A failure during an
individual build includes that meta name in the error.

Unit tests use the fixed `tests/fixtures/minimal_project` catalog where possible;
integration tests assemble the repository's production project data.
