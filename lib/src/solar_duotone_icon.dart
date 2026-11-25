import 'package:flutter/widgets.dart';

import 'solar_duotone_icon_data.dart';

/// The default opacity of a duotone icon's secondary layer.
const double kSolarSecondaryOpacity = 0.5;

/// Renders a Solar duotone icon: its secondary layer at [secondaryOpacity],
/// with the primary layer painted on top at full opacity.
///
/// Behaves like [Icon] otherwise — unspecified [size] and [color] fall back to
/// the ambient [IconTheme].
///
/// ```dart
/// SolarDuotoneIcon(SolarIconsBoldDuotone.home, size: 32, color: Colors.indigo)
/// ```
class SolarDuotoneIcon extends StatelessWidget {
  /// Creates a two-layer duotone icon.
  const SolarDuotoneIcon(
    this.icon, {
    super.key,
    this.size,
    this.color,
    this.secondaryColor,
    this.secondaryOpacity = kSolarSecondaryOpacity,
    this.semanticLabel,
    this.textDirection,
  }) : assert(secondaryOpacity >= 0.0 && secondaryOpacity <= 1.0);

  /// The duotone icon to draw. Null renders blank space of the correct size.
  final SolarDuotoneIconData? icon;

  /// Icon width and height in logical pixels. Defaults to [IconThemeData.size].
  final double? size;

  /// Colour of the primary layer. Defaults to [IconThemeData.color].
  final Color? color;

  /// Colour of the secondary layer. Defaults to [color], which is the standard
  /// Solar duotone look; set it to tint the two layers differently.
  final Color? secondaryColor;

  /// Opacity applied to the secondary layer. Ignored when [secondaryColor] is
  /// set, since that colour carries its own alpha.
  final double secondaryOpacity;

  /// Semantic description of the icon, announced by screen readers.
  final String? semanticLabel;

  /// The text direction to resolve the icon against.
  final TextDirection? textDirection;

  @override
  Widget build(BuildContext context) {
    final iconTheme = IconTheme.of(context);
    final resolvedSize = size ?? iconTheme.size ?? 24.0;
    final resolvedColor = color ?? iconTheme.color ?? const Color(0xFF000000);
    final data = icon;

    Widget content;
    if (data == null) {
      content = SizedBox(width: resolvedSize, height: resolvedSize);
    } else {
      final shade = secondaryColor ??
          resolvedColor.withValues(alpha: resolvedColor.a * secondaryOpacity);
      content = Stack(
        alignment: Alignment.center,
        children: <Widget>[
          for (final layer in <IconData>[data.secondary, ...data.overlaps])
            Icon(
              layer,
              size: resolvedSize,
              color: shade,
              textDirection: textDirection,
            ),
          Icon(
            data.primary,
            size: resolvedSize,
            color: resolvedColor,
            textDirection: textDirection,
          ),
        ],
      );
    }

    content =
        SizedBox(width: resolvedSize, height: resolvedSize, child: content);
    if (semanticLabel == null) {
      return ExcludeSemantics(child: content);
    }
    return Semantics(
        label: semanticLabel, child: ExcludeSemantics(child: content));
  }
}
