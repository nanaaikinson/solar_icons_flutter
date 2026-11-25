## 1.1.0

- Updates the icon set to `@iconify-json/solar@1.2.15`: 1,554 new icons (259 names
  such as `blocks`, `shield-off`, `git-branch` and `table`), for 9,313 in total. Solar
  also redrew some existing icons in this release.
- Every 1.0.0 icon keeps its name and code point. The 58 icons Solar renamed (for
  example `chat-dots`, now `chat-square-dots`) ship under both names.
- `tool/generate.py` resolves `<use href>` references and shapes clipped by a white
  mask, both new in this Solar release, and records code points in
  `tool/codepoints.json`.
- Duotone icons whose translucent shapes overlap now render the overlap darker, as the
  SVG does. `SolarDuotoneIconData.overlaps` holds the extra layers, which
  `SolarDuotoneIcon` draws between the secondary and primary layers. 37 icons use it,
  including `skirt`, `leaf`, `bookmark-opened` and `palette`.
- Fonts put the baseline at the bottom of the em. Flutter rounds the baseline to a whole
  pixel, so at 1000/1200 of the icon size glyphs sat up to half a pixel off their
  outlines (at 16, 28, 40 and 64 px, for example). Glyph shapes are unchanged.

## 1.0.0

Initial release.

- All 7,759 Solar icons across the six Solar styles — Linear, Outline, Bold, Broken,
  Line Duotone and Bold Duotone — as `const IconData` backed by one TrueType font per
  style. No dependencies.
- `SolarDuotoneIcon` renders duotone icons as their two layers; `SolarDuotoneIconData`
  exposes each layer as a plain `IconData`.
- `SolarIconStyle` enumerates the six styles for style pickers.
- Opt-in `package:solar_icons_flutter/solar_icons_index.dart` maps every Solar name to
  its icon for dynamic lookup.
- Works with `--tree-shake-icons`: a style you draw from is subset to the glyphs you use.
- `tool/generate.py` regenerates the fonts and bindings from `@iconify-json/solar@1.2.10`.
