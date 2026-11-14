import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

/// Icon data for a Solar duotone icon.
///
/// Duotone icons are drawn as two glyphs in the same font: a [secondary] layer
/// painted at a reduced opacity, and a [primary] layer painted at full opacity
/// on top of it.
///
/// [IconData] is a final class and cannot be subclassed, so this is a pair of
/// icons rather than an icon. Pass it to a
/// [SolarDuotoneIcon](../solar_duotone_icon/SolarDuotoneIcon-class.html) to get
/// both layers, or reach for [primary] where a plain [IconData] is required.
///
/// ```dart
/// SolarDuotoneIcon(SolarIconsBoldDuotone.home);      // both layers
/// Icon(SolarIconsBoldDuotone.home.primary);          // single tone
/// IconButton(icon: SolarDuotoneIcon(SolarIconsBoldDuotone.home), onPressed: …);
/// ```
@immutable
class SolarDuotoneIconData {
  /// Creates icon data for a two-layer duotone icon.
  const SolarDuotoneIconData({
    required this.primary,
    required this.secondary,
    this.overlaps = const <IconData>[],
  });

  /// The full-opacity layer, drawn on top.
  ///
  /// Usable on its own anywhere an [IconData] is expected, which renders the
  /// icon as a single tone.
  final IconData primary;

  /// The reduced-opacity layer, drawn beneath [primary].
  ///
  /// A few Solar icons have no shaded region; for those this glyph is empty and
  /// the icon renders identically to [primary].
  final IconData secondary;

  /// Extra layers drawn over [secondary] at the same opacity, where Solar
  /// stacks translucent shapes.
  ///
  /// Each layer covers the region where one more shape overlaps, so two shaded
  /// shapes composite to 75% and three to 87.5%, as in the source SVG. Empty
  /// for almost every icon.
  final List<IconData> overlaps;

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is SolarDuotoneIconData &&
          other.primary == primary &&
          other.secondary == secondary &&
          listEquals(other.overlaps, overlaps);

  @override
  int get hashCode => Object.hash(primary, secondary, Object.hashAll(overlaps));

  @override
  String toString() =>
      'SolarDuotoneIconData(U+${primary.codePoint.toRadixString(16).toUpperCase()}'
      ' + U+${secondary.codePoint.toRadixString(16).toUpperCase()})';
}
