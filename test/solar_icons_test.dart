import 'dart:convert';
import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:solar_icons_flutter/solar_icons_index.dart';

const _package = 'solar_icons_flutter';

void main() {
  group('icon data', () {
    test('every style is populated and points at its own font', () {
      final expected = <String, Map<String, IconData>>{
        'SolarIconsLinear': solarLinearIcons,
        'SolarIconsOutline': solarOutlineIcons,
        'SolarIconsBold': solarBoldIcons,
        'SolarIconsBroken': solarBrokenIcons,
      };
      for (final MapEntry(key: family, value: icons) in expected.entries) {
        expect(icons, hasLength(greaterThan(1200)), reason: family);
        for (final icon in icons.values) {
          expect(icon.fontFamily, family);
          expect(icon.fontPackage, _package);
        }
      }
    });

    test('duotone layers share a font and sit on adjacent code points', () {
      final duotone = <String, Map<String, SolarDuotoneIconData>>{
        'SolarIconsLineDuotone': solarLineDuotoneIcons,
        'SolarIconsBoldDuotone': solarBoldDuotoneIcons,
      };
      for (final MapEntry(key: family, value: icons) in duotone.entries) {
        expect(icons, hasLength(greaterThan(1200)), reason: family);
        for (final icon in icons.values) {
          expect(icon.primary.fontFamily, family);
          expect(icon.secondary.fontFamily, family);
          expect(icon.primary.fontPackage, _package);
          expect(icon.secondary.codePoint, icon.primary.codePoint + 1);
        }
      }
    });

    test('code points are unique within a style', () {
      for (final icons in <Iterable<IconData>>[
        solarLinearIcons.values,
        solarOutlineIcons.values,
        solarBoldIcons.values,
        solarBrokenIcons.values,
        solarLineDuotoneIcons.values.map((i) => i.primary),
        solarBoldDuotoneIcons.values.map((i) => i.primary),
      ]) {
        final points = icons.map((i) => i.codePoint).toList();
        expect(points.toSet(), hasLength(points.length));
      }
    });

    test('the six styles total 9,313 icons', () {
      final total = solarLinearIcons.length +
          solarOutlineIcons.length +
          solarBoldIcons.length +
          solarBrokenIcons.length +
          solarLineDuotoneIcons.length +
          solarBoldDuotoneIcons.length;
      expect(total, 9313);
    });

    test('named lookups resolve, and unknown names return null', () {
      for (final style in SolarIconStyle.values) {
        expect(solarIconByName('home', style), isNotNull, reason: style.name);
        expect(solarIconByName('definitely-not-an-icon', style), isNull);
      }
      expect(solarDuotoneIconByName('home', SolarIconStyle.boldDuotone),
          isNotNull);
      expect(solarDuotoneIconByName('home', SolarIconStyle.bold), isNull);
    });

    test('generated constants agree with the index', () {
      expect(solarBoldIcons['home'], SolarIconsBold.home);
      expect(solarLinearIcons['home-smile'], SolarIconsLinear.homeSmile);
      expect(solarBoldDuotoneIcons['home'], SolarIconsBoldDuotone.home);
      // `case` is a reserved word and `4k` starts with a digit.
      expect(solarBoldIcons['case'], SolarIconsBold.caseIcon);
      expect(solarLinearIcons['4k'], SolarIconsLinear.icon4k);
      // `4k` and `four-k` are different Solar icons.
      expect(SolarIconsLinear.icon4k, isNot(SolarIconsLinear.fourK));
    });
  });

  group('code points', () {
    test('icons keep their 1.0.0 code points', () {
      expect(SolarIconsLinear.icon4k.codePoint, 0xe000);
      expect(SolarIconsLinear.shield.codePoint, 0xe3ac);
      expect(SolarIconsLinear.tuning2.codePoint, 0xe483);
      expect(SolarIconsOutline.tuning2.codePoint, 0xe480);
      expect(SolarIconsLineDuotone.chatDots.primary.codePoint, 0xe1ae);
    });

    test('renamed icons keep their old names', () {
      expect(solarLinearIcons['chat-dots'], isNotNull);
      expect(solarLinearIcons['chat-square-dots'], isNotNull);
    });

    test('bindings agree with tool/codepoints.json', () {
      final lock = jsonDecode(File('tool/codepoints.json').readAsStringSync())
          as Map<String, dynamic>;
      final styles = <String, Map<String, int>>{
        'Linear': solarLinearIcons.map((k, v) => MapEntry(k, v.codePoint)),
        'Outline': solarOutlineIcons.map((k, v) => MapEntry(k, v.codePoint)),
        'Bold': solarBoldIcons.map((k, v) => MapEntry(k, v.codePoint)),
        'Broken': solarBrokenIcons.map((k, v) => MapEntry(k, v.codePoint)),
        'LineDuotone': solarLineDuotoneIcons
            .map((k, v) => MapEntry(k, v.primary.codePoint)),
        'BoldDuotone': solarBoldDuotoneIcons
            .map((k, v) => MapEntry(k, v.primary.codePoint)),
      };
      for (final MapEntry(key: style, value: icons) in styles.entries) {
        final locked = lock[style] as Map<String, dynamic>;
        for (final MapEntry(key: name, value: codePoint) in icons.entries) {
          expect(codePoint, int.parse(locked[name] as String), reason: name);
        }
      }
    });

    test('blocks ships in every style', () {
      for (final style in SolarIconStyle.values) {
        expect(solarIconByName('blocks', style), isNotNull, reason: style.name);
      }
    });
  });

  group('fonts', () {
    test('every declared font ships with the package', () {
      for (final style in SolarIconStyle.values) {
        final file = File('fonts/${style.fontFamily}.ttf');
        expect(file.existsSync(), isTrue, reason: file.path);
        expect(file.lengthSync(), greaterThan(100 * 1024), reason: file.path);
      }
    });

    test('pubspec declares all six font families', () {
      final pubspec = File('pubspec.yaml').readAsStringSync();
      for (final style in SolarIconStyle.values) {
        expect(pubspec, contains('family: ${style.fontFamily}'));
        expect(pubspec, contains('fonts/${style.fontFamily}.ttf'));
      }
    });
  });

  group('SolarIconStyle', () {
    test('duotone styles are flagged', () {
      expect(
        SolarIconStyle.values.where((s) => s.isDuotone),
        <SolarIconStyle>[
          SolarIconStyle.lineDuotone,
          SolarIconStyle.boldDuotone
        ],
      );
    });
  });

  group('SolarDuotoneIcon', () {
    Widget host(Widget child, {IconThemeData? iconTheme}) => Directionality(
          textDirection: TextDirection.ltr,
          child: IconTheme(
            data: iconTheme ??
                const IconThemeData(size: 24, color: Color(0xFF000000)),
            // Without this the test surface's tight constraints would stretch
            // the icon to fill the window.
            child: Center(child: child),
          ),
        );

    testWidgets('draws both layers, secondary beneath primary', (tester) async {
      await tester.pumpWidget(host(
        const SolarDuotoneIcon(SolarIconsBoldDuotone.home, size: 40),
      ));

      final icons = tester.widgetList<Icon>(find.byType(Icon)).toList();
      expect(icons, hasLength(2));
      expect(icons[0].icon, SolarIconsBoldDuotone.home.secondary);
      expect(icons[1].icon, SolarIconsBoldDuotone.home.primary);
      expect(icons.every((i) => i.size == 40), isTrue);
      expect(tester.getSize(find.byType(SolarDuotoneIcon)), const Size(40, 40));
    });

    testWidgets('stacked layers sit between secondary and primary',
        (tester) async {
      const skirt = SolarIconsBoldDuotone.skirt;
      expect(skirt.overlaps, hasLength(2));
      await tester.pumpWidget(host(
        const SolarDuotoneIcon(skirt, color: Color(0xFF2244FF)),
      ));

      final icons = tester.widgetList<Icon>(find.byType(Icon)).toList();
      expect(icons.map((i) => i.icon),
          [skirt.secondary, ...skirt.overlaps, skirt.primary]);
      for (final layer in icons.take(3)) {
        expect(layer.color!.a, closeTo(0.5, 0.001));
      }
    });

    test('overlap layers are equality-relevant', () {
      const skirt = SolarIconsBoldDuotone.skirt;
      expect(
        SolarDuotoneIconData(
            primary: skirt.primary, secondary: skirt.secondary),
        isNot(skirt),
      );
      expect(SolarIconsBoldDuotone.home.overlaps, isEmpty);
    });

    testWidgets('secondary is drawn at half alpha by default', (tester) async {
      await tester.pumpWidget(host(
        const SolarDuotoneIcon(SolarIconsBoldDuotone.home,
            color: Color(0xFF2244FF)),
      ));

      final icons = tester.widgetList<Icon>(find.byType(Icon)).toList();
      expect(icons[1].color, const Color(0xFF2244FF));
      expect(icons[0].color!.a, closeTo(0.5, 0.001));
      expect(icons[0].color!.r, closeTo(icons[1].color!.r, 0.001));
    });

    testWidgets('secondaryColor overrides the derived tint', (tester) async {
      await tester.pumpWidget(host(
        const SolarDuotoneIcon(
          SolarIconsBoldDuotone.home,
          color: Color(0xFF2244FF),
          secondaryColor: Color(0x33FF0000),
        ),
      ));
      final icons = tester.widgetList<Icon>(find.byType(Icon)).toList();
      expect(icons[0].color, const Color(0x33FF0000));
    });

    testWidgets('falls back to the ambient IconTheme', (tester) async {
      await tester.pumpWidget(host(
        const SolarDuotoneIcon(SolarIconsBoldDuotone.home),
        iconTheme: const IconThemeData(size: 33, color: Color(0xFF00AA00)),
      ));
      final icons = tester.widgetList<Icon>(find.byType(Icon)).toList();
      expect(icons[1].size, 33);
      expect(icons[1].color, const Color(0xFF00AA00));
    });

    testWidgets('a null icon still occupies its box', (tester) async {
      await tester.pumpWidget(host(const SolarDuotoneIcon(null, size: 28)));
      expect(find.byType(Icon), findsNothing);
      expect(tester.getSize(find.byType(SolarDuotoneIcon)), const Size(28, 28));
    });

    testWidgets('semanticLabel is exposed to assistive tech', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(host(
        const SolarDuotoneIcon(SolarIconsBoldDuotone.home,
            semanticLabel: 'Home'),
      ));
      expect(find.bySemanticsLabel('Home'), findsOneWidget);
      handle.dispose();
    });

    testWidgets('primary layer works as a plain Icon', (tester) async {
      // Not `const Icon(...)`: reading a field off a constant is not itself a
      // constant expression in Dart.
      await tester.pumpWidget(host(
        Icon(SolarIconsBoldDuotone.home.primary, size: 20),
      ));
      expect(tester.widget<Icon>(find.byType(Icon)).icon,
          SolarIconsBoldDuotone.home.primary);
    });
  });
}
