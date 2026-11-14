# solar_icons_flutter

The complete [Solar Icon Set](https://solar-icons.vercel.app) for Flutter — **9,313 icons**
across all six Solar styles, as plain `IconData` backed by icon fonts. No dependencies.

```dart
Icon(SolarIconsBold.home);
Icon(SolarIconsLinear.homeSmile, size: 32, color: Colors.indigo);
SolarDuotoneIcon(SolarIconsBoldDuotone.home);
```

| Style | Class | Icons | Font |
| --- | --- | --: | --- |
| Linear | `SolarIconsLinear` | 1,542 | 585 KB |
| Outline | `SolarIconsOutline` | 1,539 | 719 KB |
| Bold | `SolarIconsBold` | 1,551 | 446 KB |
| Broken | `SolarIconsBroken` | 1,543 | 677 KB |
| Line Duotone | `SolarIconsLineDuotone` | 1,554 | 640 KB |
| Bold Duotone | `SolarIconsBoldDuotone` | 1,584 | 504 KB |

Solar does not draw every icon in every style, so the counts differ and a name that
exists in one class may be missing from another.

## Install

```bash
flutter pub add solar_icons_flutter
```

```dart
import 'package:solar_icons_flutter/solar_icons_flutter.dart';
```

That is all — the fonts ship with the package and need no `pubspec.yaml` changes in your app.

## Usage

Icons are `const IconData`, so they work anywhere Flutter expects one:

```dart
Icon(SolarIconsBold.settings)
IconButton(icon: const Icon(SolarIconsLinear.trashBinTrash), onPressed: _delete)
ListTile(leading: Icon(SolarIconsOutline.user))
NavigationDestination(icon: Icon(SolarIconsBroken.compass), label: 'Explore')
Text.rich(TextSpan(children: [WidgetSpan(child: Icon(SolarIconsBold.star, size: 14))]))
```

Size and colour fall back to the ambient `IconTheme`, exactly like Material icons.

### Naming

Solar's kebab-case names become lowerCamelCase members: `home-smile` → `homeSmile`,
`trash-bin-trash` → `trashBinTrash`. Two names cannot be spelled directly in Dart:

| Solar name | Dart member | Why |
| --- | --- | --- |
| `case` | `caseIcon` | `case` is a reserved word |
| `4k` | `icon4k` | identifiers cannot start with a digit, and Solar also ships a separate `four-k` |

### Duotone

Duotone icons are two glyphs: a shaded layer at half opacity with a solid layer on top.
`IconData` is a `final class` and cannot be subclassed, so duotone icons are a
`SolarDuotoneIconData` pair rather than an `IconData`:

```dart
SolarDuotoneIcon(SolarIconsBoldDuotone.wallet)
SolarDuotoneIcon(SolarIconsLineDuotone.wallet, size: 40, color: Colors.teal)

// Tint the layers separately.
SolarDuotoneIcon(
  SolarIconsBoldDuotone.wallet,
  color: Colors.teal.shade700,
  secondaryColor: Colors.teal.shade100,
)

// Or take just the solid layer where a real IconData is required.
Icon(SolarIconsBoldDuotone.wallet.primary)
IconButton(
  icon: SolarDuotoneIcon(SolarIconsBoldDuotone.wallet),
  onPressed: _openWallet,
)
```

Note that `SolarIconsBoldDuotone.wallet.primary` is a field read, not a constant
expression, so it cannot go inside a `const Icon(...)`. Drop the `const`.

### Looking icons up by name

For an icon picker, or an icon name coming from a CMS or config file, import the
opt-in index library:

```dart
import 'package:solar_icons_flutter/solar_icons_index.dart';

Icon(solarBoldIcons['home-smile']!);
Icon(solarIconByName(nameFromApi, SolarIconStyle.linear) ?? SolarIconsLinear.question);
SolarDuotoneIcon(solarDuotoneIconByName(name, SolarIconStyle.boldDuotone));
```

Keys are the original Solar names as shown on
[solar-icons.vercel.app](https://solar-icons.vercel.app). This library is deliberately
not exported by the main one: a map that mentions every icon defeats tree shaking, so
touching a style's map pins that style's whole font.

## Bundle size

Release builds run `--tree-shake-icons` by default, and it works on these fonts:
an app that uses three icons ships them as three subset fonts of **under 1 KB each**,
duotone included.

The catch is Flutter's, not this package's: the subsetter only rewrites fonts that have
at least one referenced glyph. A style you never touch is still copied into the bundle at
full size. So an app using icons from one style ships that style subset to a few hundred
bytes plus roughly 3 MB of untouched fonts; using all six brings that to zero. If that
matters for your app, reference at least one icon from each style you ship, or vendor the
single `.ttf` you need out of `fonts/` and declare it yourself.

## Fidelity

Four of Solar's six styles are drawn with strokes, and fonts can only carry filled
contours, so the build pipeline outlines every stroke rather than approximating it. Every
generated glyph is checked against its source SVG by rasterising both and comparing
pixels:

| Style | Mean difference | 99th percentile | Worst |
| --- | --: | --: | --: |
| Bold | 0.20% | 0.38% | 0.65% |
| Bold Duotone | 0.18% | 0.33% | 3.7% |
| Outline | 0.31% | 0.50% | 0.65% |
| Line Duotone | 0.73% | 2.0% | 2.7% |
| Broken | 0.85% | 2.2% | 2.7% |
| Linear | 0.93% | 2.3% | 2.8% |

The baseline for the stroke-drawn styles is antialiasing along outlined strokes, not
shape error.

Where a duotone icon stacks translucent shapes, the overlap composites darker than either
shape alone. Those icons carry extra `overlaps` layers, drawn at the same half opacity, so
two stacked shapes render at 75% and three at 87.5%, as in the SVG. The one known
deviation is `winrar` in Bold Duotone, whose top band is 30% opaque in the source: the
lightest shade a layer can draw is 50%.

## Regenerating

The fonts and all Dart bindings are generated from
[`@iconify-json/solar`](https://www.npmjs.com/package/@iconify-json/solar) by
[`tool/generate.py`](tool/generate.py):

```bash
python3 -m venv .venv && .venv/bin/pip install -r tool/requirements.txt
.venv/bin/python tool/generate.py
```

It downloads the pinned icon set, flattens each icon with
[picosvg](https://github.com/googlefonts/picosvg) (resolving groups, transforms, masks
and strokes), splits duotone icons into their two opacity layers, and builds one
TrueType font plus one Dart class per style. Glyphs live in the Private Use Area from
`U+E000`; duotone secondaries sit at the primary code point plus one.

[`tool/codepoints.json`](tool/codepoints.json) records every code point ever assigned.
Regeneration keeps them and appends new icons after the highest one, and a name Solar
renames into an alias keeps shipping under its old name. The generator formats the
bindings with the `dart` on your `PATH`; use a Dart 3.6 SDK so the output matches the
package's language version.

## Example

[`example/`](example) is a browsable gallery of all 9,313 icons with search, a style
switcher, a size slider, light/dark mode, and copy-to-clipboard for the Dart snippet.

```bash
cd example && flutter run
```

## Licence

The Dart code, build tooling and generated bindings are MIT licensed.

The icon artwork is the **Solar Icon Set by [480 Design](https://www.figma.com/community/file/1166831539721848736)**,
licensed **[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)**. The fonts in
`fonts/` are derived from that artwork, so if you ship them you must carry the
attribution. See [NOTICE](NOTICE) for the full attribution terms, and
[LICENSE](LICENSE) for the MIT text.
