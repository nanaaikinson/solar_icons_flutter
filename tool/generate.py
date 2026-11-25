#!/usr/bin/env python3
"""Generate solar_icons_flutter fonts + Dart bindings from the Iconify Solar icon set.

Pipeline
--------
1. Read `@iconify-json/solar` icons.json (24x24 viewBox, `currentColor`).
2. Flatten each icon with picosvg: resolve groups/transforms, convert primitive
   shapes to paths, and outline strokes into fills (4 of the 6 Solar styles are
   stroke-based, and fonts can only carry filled contours).
3. Group the resulting shapes by opacity. Duotone styles collapse to two layers:
   everything below full opacity becomes the "secondary" layer, the rest the
   "primary" layer. Both layers use the same colour, so `src-over` compositing of
   a colour onto itself is an identity -- the original paint order does not need
   to be preserved.
4. Normalise each shape's winding and concatenate the contours into one glyph.
   Deliberately NOT a boolean union: Skia drops contours where stroke outlines
   meet at a single point. See the comment in `flatten` before changing this.
5. Build one TrueType font per style and one Dart class per style.

A handful of icons need help before step 2: `unmask` resolves the luminance-mask
idiom that picosvg cannot, and `normalize_markup` pushes group opacity down onto
shapes and splits multi-subpath stroked paths.

Usage: python3 tool/generate.py [--icons-json PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "fonts"
SRC_DIR = ROOT / "lib" / "src"

ICONIFY_PKG = "@iconify-json/solar@1.2.15"

# Longest suffixes first so `-bold-duotone` is not shortened to `-bold`.
STYLES = [
    # (iconify suffix, dart class suffix, font family, duotone?)
    ("bold-duotone", "BoldDuotone", "SolarIconsBoldDuotone", True),
    ("line-duotone", "LineDuotone", "SolarIconsLineDuotone", True),
    ("linear", "Linear", "SolarIconsLinear", False),
    ("outline", "Outline", "SolarIconsOutline", False),
    ("broken", "Broken", "SolarIconsBroken", False),
    ("bold", "Bold", "SolarIconsBold", False),
]

UPEM = 1200
SVG_SIZE = 24
SCALE = UPEM / SVG_SIZE  # 50 font units per SVG unit
# The baseline sits at the bottom of the em, a whole pixel at any whole-number
# icon size. With it at 1000/1200 of the size, Flutter rounds it to the nearest
# pixel and glyphs land up to half a pixel off, differently at every size.
ASCENDER = 1200
DESCENDER = 0  # ASCENDER - DESCENDER == UPEM, so Icon() centres exactly.
FIRST_CODEPOINT = 0xE000

# Every code point ever assigned, per style. Icons keep theirs across source
# bumps, and new icons are appended after the highest one, so a font from one
# release never draws the wrong glyph for a constant compiled against another.
CODEPOINTS = ROOT / "tool" / "codepoints.json"

# The fonts are checked in, so their bytes must be reproducible. fontTools stamps
# head.created/modified with the wall clock, which would turn every regeneration
# into a 2.9 MB binary diff with no glyph changes. Seconds since fontTools' epoch
# of 1904-01-01; override with SOURCE_DATE_EPOCH (Unix epoch) if you need to.
FONT_TIMESTAMP = 3871000000

# `pallete-2-linear` draws two dots as a self-masked 3-unit stroke on a r=1.5
# circle, which clips to a solid disc. picosvg cannot resolve masks, so the
# equivalent maskless artwork is substituted.
BODY_OVERRIDES = {
    "pallete-2-linear": (
        '<g fill="none" stroke="currentColor">'
        '<path stroke-width="1.5" d="M2 12.026c0 5.146 3.867 9.387 8.847 9.96c.735.085 1.447-.228 1.97-.753'
        "a1.68 1.68 0 0 0 0-2.372c-.523-.525-.95-1.307-.555-1.934c1.576-2.508 9.738 3.251 9.738-4.9"
        'C22 6.488 17.523 2 12 2S2 6.489 2 12.026Z"/>'
        '<circle cx="17.5" cy="11.5" r=".75" stroke-width="1.5"/>'
        '<circle cx="6.5" cy="11.5" r=".75" stroke-width="1.5"/>'
        "</g>"
        '<path fill="currentColor" d="M11.085 7a1.5 1.5 0 1 1-3 0a1.5 1.5 0 0 1 3 0Z"/>'
        '<path fill="currentColor" d="M16 7a1.5 1.5 0 1 1-3 0a1.5 1.5 0 0 1 3 0Z"/>'
    ),
}

# `case` is a Dart reserved word. `4k` starts with a digit, and Solar also ships
# a separate `four-k` icon, so it cannot simply be spelled out.
NAME_OVERRIDES = {"case": "caseIcon", "4k": "icon4k"}


def split_key(key: str):
    for suffix, *_ in STYLES:
        if key.endswith("-" + suffix):
            return key[: -(len(suffix) + 1)], suffix
    return None, None


def dart_name(base: str) -> str:
    if base in NAME_OVERRIDES:
        return NAME_OVERRIDES[base]
    parts = [p for p in re.split(r"[^a-zA-Z0-9]+", base) if p]
    return parts[0].lower() + "".join(p[:1].upper() + p[1:] for p in parts[1:])


# --------------------------------------------------------------------------- 1/2


def fetch_icons_json(dest: Path) -> Path:
    """Download the pinned Iconify package and return the path to icons.json.

    `dest` carries the pinned version in its name, so bumping ICONIFY_PKG misses
    the cache and re-downloads instead of silently rebuilding from the old set.
    """
    if dest.exists():
        return dest
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["npm", "pack", ICONIFY_PKG], cwd=tmp, check=True, capture_output=True)
        tgz = next(Path(tmp).glob("*.tgz"))
        with tarfile.open(tgz) as tar:
            member = tar.extractfile("package/icons.json")
            if member is None:
                raise SystemExit(f"{ICONIFY_PKG} has no package/icons.json")
            with member:
                dest.write_bytes(member.read())
    return dest


_SVG_NS = "http://www.w3.org/2000/svg"
_OPACITY_OPAQUE = {"defs", "mask", "clipPath", "style", "title", "desc"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _is_stroke_only(fill, stroke) -> bool:
    return fill == "none" and stroke not in (None, "none")


def _split_subpaths(element):
    """One `<path>` per subpath, for stroke-only paths.

    Skia's stroker mangles some multi-subpath Solar paths into a filled
    silhouette. Each subpath of a stroked path is stroked independently anyway,
    so splitting is semantically free -- but only for stroke-only paths: a
    filled path's subpaths are its holes and must stay together.
    """
    import copy
    import re

    from picosvg.svg_types import SVGPath

    d = element.get("d")
    if not d:
        return [element]
    absolute = SVGPath(d=d).absolute().d
    # Splitting on "M" is only sound while every moveto is absolute: a relative
    # "m" would be folded into the previous subpath and then resolved against
    # the wrong origin, silently misplacing the geometry.
    if "m" in absolute:
        raise ValueError(f"absolute() left a relative moveto: {absolute[:60]}")
    subpaths = re.findall(r"M[^M]*", absolute)
    if len(subpaths) < 2:
        return [element]
    out = []
    for subpath in subpaths:
        clone = copy.deepcopy(element)
        clone.set("d", subpath.strip())
        out.append(clone)
    return out


def normalize_markup(body: str) -> str:
    """Push group opacity onto shapes and split multi-subpath stroked paths.

    picosvg keeps per-shape `opacity` but silently drops group opacity, which
    would flatten a duotone icon's shaded layer to full strength. Group opacity
    composites the group as a unit whereas per-shape opacity does not, but every
    Solar shape is `currentColor` and the layers are re-unioned per opacity
    afterwards, so the two are equivalent here.
    """
    import xml.etree.ElementTree as ET

    ET.register_namespace("", _SVG_NS)
    root = ET.fromstring(f'<svg xmlns="{_SVG_NS}">{body}</svg>')

    def walk(element, opacity: float, fill, stroke):
        """Normalise `element` in place; return what replaces it in its parent."""
        tag = _local(element.tag)
        if tag in _OPACITY_OPAQUE:
            return [element]
        own = element.get("opacity")
        factor = opacity * (float(own) if own is not None else 1.0)
        fill = element.get("fill", fill)
        stroke = element.get("stroke", stroke)
        if tag in ("g", "svg"):
            element.attrib.pop("opacity", None)
        elif factor != 1.0:
            element.set("opacity", f"{factor:g}")

        children = list(element)
        replacement = []
        for child in children:
            replacement.extend(walk(child, factor, fill, stroke))
        if replacement != children:
            for child in children:
                element.remove(child)
            element.extend(replacement)

        if tag == "path" and _is_stroke_only(fill, stroke):
            return _split_subpaths(element)
        return [element]

    walk(root, 1.0, None, None)
    return "".join(
        ET.tostring(child, encoding="unicode").replace(f' xmlns="{_SVG_NS}"', "")
        for child in root
    )


# Seventeen Solar icons encode their layers as a luminance mask over a
# full-canvas `currentColor` rect: white paints at full strength, `gray` at half
# (the duotone shading), and black cuts a hole. picosvg cannot resolve masks, so
# the mask is translated back into ordinary paint plus a set of cut-out shapes.
_MASK_SHELL_PATH = "M0 0h24v24H0z"
_MASK_ALPHA = {
    "#fff": 1.0, "#ffffff": 1.0, "white": 1.0,
    "gray": 0.5, "grey": 0.5, "#808080": 0.5,
    "#000": 0.0, "#000000": 0.0, "black": 0.0,
}
_SHAPE_TAGS = {"path", "circle", "rect", "ellipse", "line", "polygon", "polyline"}


def _paint_alpha(element):
    """The mask alpha this shape paints with, or None if it paints nothing."""
    alphas = [
        _MASK_ALPHA[v]
        for v in (element.get("fill"), element.get("stroke"))
        if v is not None and v in _MASK_ALPHA
    ]
    return max(alphas) if alphas else None


def _prune(element, keep, inherited):
    """Copy `element`, keeping only shapes `keep` accepts. None if nothing is left."""
    import copy
    import xml.etree.ElementTree as ET

    tag = _local(element.tag)
    alpha = _paint_alpha(element)
    effective = alpha if alpha is not None else inherited

    if tag in _SHAPE_TAGS:
        if not keep(effective):
            return None
        shape = copy.deepcopy(element)
        for attribute in ("fill", "stroke"):
            if shape.get(attribute) in _MASK_ALPHA:
                shape.set(attribute, "currentColor")
        if effective is not None and 0.0 < effective < 1.0:
            shape.set("opacity", f"{effective:g}")
        return shape

    kept = [_prune(child, keep, effective) for child in element]
    kept = [k for k in kept if k is not None]
    if not kept:
        return None
    group = ET.Element(element.tag, dict(element.attrib))
    for attribute in ("fill", "stroke"):
        if group.get(attribute) in _MASK_ALPHA:
            group.set(attribute, "currentColor")
    group.extend(kept)
    return group


def unmask(body: str):
    """Split `body` into (paint, cut) markup, resolving Solar's luminance masks.

    Returns the body unchanged with an empty cut for the icons -- almost all of
    them -- that use no mask.
    """
    if "<mask" not in body:
        return body, ""

    import xml.etree.ElementTree as ET

    ET.register_namespace("", _SVG_NS)
    root = ET.fromstring(f'<svg xmlns="{_SVG_NS}">{body}</svg>')
    masks = {
        element.get("id"): element
        for element in root.iter()
        if _local(element.tag) == "mask" and element.get("id")
    }
    shells = [
        element
        for element in root.iter()
        if element.get("mask", "").startswith("url(#")
        and element.get("d") == _MASK_SHELL_PATH
    ]
    if len(shells) != 1 or len(masks) != 1:
        return body, ""  # not the known idiom; let picosvg report it

    content = masks.get(shells[0].get("mask")[5:-1])
    if content is None:
        return body, ""  # dangling mask reference; let picosvg report it

    def serialise(element):
        if element is None:
            return ""
        return "".join(
            ET.tostring(child, encoding="unicode").replace(f' xmlns="{_SVG_NS}"', "")
            for child in element
        )

    paint = _prune(content, lambda a: a is not None and a > 0.0, None)
    cut = _prune(content, lambda a: a == 0.0, None)
    return serialise(paint), serialise(cut)


_HREFS = ("href", "{http://www.w3.org/1999/xlink}href")
_INHERITED = (
    "fill", "fill-rule", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset",
)


def _parse(body: str):
    import xml.etree.ElementTree as ET

    ET.register_namespace("", _SVG_NS)
    return ET.fromstring(f'<svg xmlns="{_SVG_NS}">{body}</svg>')


def _serialise(root) -> str:
    import xml.etree.ElementTree as ET

    return "".join(
        ET.tostring(child, encoding="unicode").replace(f' xmlns="{_SVG_NS}"', "")
        for child in root
    )


def inline_uses(body: str) -> str:
    """Replace each `<use href="#id">` with a copy of the element it names.

    picosvg resolves only `xlink:href`, and Solar has started emitting `href`.
    """
    if "<use" not in body:
        return body
    import copy

    root = _parse(body)
    targets = {e.get("id"): e for e in root.iter() if e.get("id")}
    for parent in list(root.iter()):
        for index, child in enumerate(list(parent)):
            if _local(child.tag) != "use":
                continue
            href = next((child.get(h) for h in _HREFS if child.get(h)), "")
            target = targets.get(href[1:]) if href.startswith("#") else None
            if target is None or child.get("x", "0") != "0" or child.get("y", "0") != "0":
                return body  # not the known idiom; let picosvg report it
            clone = copy.deepcopy(target)
            clone.attrib.pop("id")
            for name, value in child.attrib.items():
                if name not in _HREFS:
                    clone.set(name, value)
            parent[index] = clone
    return _serialise(root)


def split_masked(body: str):
    """Pull out shapes clipped by an all-white mask: (rest, [(shape, mask)]).

    A mask that paints only full-strength white is a plain clip, so the shape
    renders as its own geometry intersected with the mask's. picosvg cannot
    resolve masks, so `flatten` does that intersection itself. Each pulled-out
    shape takes the presentation attributes it inherited from its groups.
    """
    if "mask=" not in body:
        return body, []
    root = _parse(body)
    masks = {e.get("id"): e for e in root.iter() if _local(e.tag) == "mask"}
    clipped = []

    def walk(element, inherited):
        inherited = {**inherited, **{a: element.get(a) for a in _INHERITED if element.get(a)}}
        for child in list(element):
            ref = child.get("mask", "")
            mask = masks.get(ref[5:-1]) if ref.startswith("url(#") else None
            if mask is None:
                walk(child, inherited)
                continue
            shapes = [e for e in mask.iter() if _local(e.tag) in _SHAPE_TAGS]
            fills = {e.get("fill", mask.get("fill")) for e in shapes}
            if not shapes or not fills <= {"#fff", "#ffffff", "white"} or any(
                e.get("stroke") for e in shapes
            ):
                raise ValueError(f"unsupported mask {ref}")
            child.attrib.pop("mask")
            for name, value in inherited.items():
                if child.get(name) is None:
                    child.set(name, value)
            for shape in shapes:
                shape.set("fill", "currentColor")
            clipped.append((_serialise([child]), _serialise(mask)))
            element.remove(child)

    walk(root, {})
    for mask in masks.values():
        for parent in root.iter():
            if mask in list(parent):
                parent.remove(mask)
    return _serialise(root), clipped


def translucent_units(body: str) -> list[tuple[str, int]]:
    """The translucent units of `body`: (standalone markup, layer count).

    A unit is the outermost element that carries an opacity. SVG composites a
    unit as a whole, so its own pieces never stack, but two units that overlap
    composite darker: 50% over 50% is 75%. Duotone layers are all drawn at 50%,
    so a unit counts as the number of stacked layers nearest its opacity: 0.3
    is one layer (50%), 0.7 two (75%). Each unit takes the presentation
    attributes it inherited. Returns [] if a transform sits above a unit.
    """
    root = _parse(body)
    units = []

    def walk(element, inherited) -> bool:
        for child in element:
            if _local(child.tag) in _OPACITY_OPAQUE:
                continue
            opacity = float(child.get("opacity", 1))
            if opacity < 1:
                for name, value in inherited.items():
                    if child.get(name) is None:
                        child.set(name, value)
                child.attrib.pop("opacity")
                count = min(range(1, 5), key=lambda n: abs(opacity - (1 - 0.5**n)))
                units.append((_serialise([child]), count))
                continue
            if child.get("transform") is not None and len(child):
                return False
            if not walk(child, {**inherited, **{a: child.get(a) for a in _INHERITED if child.get(a)}}):
                return False
        return True

    return units if walk(root, {}) else []


def overlap_layers(units, pico, opaque: str) -> list[str]:
    """Regions covered by at least 2, 3 and 4 of `units`, as path data.

    Parts hidden under `opaque` (the primary layer's path data) are left out:
    they never show, and their antialiased edges would darken the primary's.
    """
    from picosvg import svg_pathops as sp
    from picosvg.svg_types import SVGPath

    levels: list[list] = []  # levels[j]: the region covered by more than j layers
    for unit in (markup for markup, count in units for _ in range(count)):
        shapes = list(pico(unit).shapes())
        if not shapes:
            continue
        path = list(sp.union([s.as_cmd_seq() for s in shapes], [s.fill_rule or "nonzero" for s in shapes]))
        for j in range(min(len(levels), 3), 0, -1):
            deeper = list(sp.intersection([levels[j - 1], path], ["nonzero", "nonzero"]))
            if j == len(levels):
                levels.append(deeper)
            else:
                levels[j] = list(sp.union([levels[j], deeper], ["nonzero", "nonzero"]))
        levels[0:1] = [list(sp.union(levels[:1] + [path], ["nonzero"] * (len(levels[:1]) + 1)))]
    if opaque:
        hidden = SVGPath(d=opaque).as_cmd_seq()
        levels[1:] = [list(sp.difference([level, hidden], ["nonzero", "nonzero"])) for level in levels[1:]]
    out = []
    for level in levels[1:]:
        if level and sp.path_area(level, "nonzero") >= 0.02:
            out.append(SVGPath.from_commands(level).round_floats(3).d.strip())
    return out


def flatten(item):
    """Worker: one icon -> {opacity: path_d, "overlaps": [path_d]} or an error string."""
    key, body = item
    from picosvg import svg_pathops as sp
    from picosvg.svg import SVG
    from picosvg.svg_types import SVGPath

    import dataclasses

    try:
        paint_body, cut_body = unmask(inline_uses(body))
        paint_body, clipped = split_masked(paint_body)
    except ValueError as e:
        return key, None, f"markup: {e}"

    def pico(markup):
        wrapped = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            f"{normalize_markup(markup)}</svg>"
        )
        return SVG.fromstring(wrapped).topicosvg()

    try:
        painted = pico(paint_body)
        cut_shapes = pico(cut_body).shapes() if cut_body else []
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        return key, None, f"picosvg: {type(e).__name__}: {e}"

    shapes = list(painted.shapes())
    try:
        for shape_markup, mask_markup in clipped:
            mask_shapes = list(pico(mask_markup).shapes())
            mask = sp.union(
                [m.as_cmd_seq() for m in mask_shapes],
                [m.fill_rule or "nonzero" for m in mask_shapes],
            )
            for shape in pico(shape_markup).shapes():
                kept = SVGPath.from_commands(
                    sp.intersection(
                        [shape.as_cmd_seq(), mask], [shape.fill_rule or "nonzero", "nonzero"]
                    )
                )
                shapes.append(dataclasses.replace(kept, opacity=shape.opacity))
    except Exception as e:  # noqa: BLE001
        return key, None, f"mask: {type(e).__name__}: {e}"

    layers: dict[float, list] = {}
    for shape in shapes:
        opacity = float(getattr(shape, "opacity", 1.0)) * float(getattr(shape, "fill_opacity", 1.0))
        opacity = round(opacity, 3)
        if opacity <= 0.0:
            continue
        layers.setdefault(opacity, []).append(shape)

    out = {}
    for opacity, shapes in layers.items():
        # Every shape in a layer is the same colour, so concatenating their
        # contours renders exactly as painting them in order -- both SVG and
        # TrueType fill non-zero. A boolean union would be equivalent in
        # principle, but Skia's union drops contours where stroke outlines meet
        # at a single point, which mangles several Solar icons.
        #
        # Concatenation is only safe once each shape's contours wind the same
        # way, otherwise an overlap between two oppositely wound shapes cancels
        # to zero and punches a hole. remove_overlaps normalises each shape.
        try:
            normalised = [
                SVGPath.from_commands(
                    sp.remove_overlaps(shape.as_cmd_seq(), shape.fill_rule or "nonzero")
                )
                for shape in shapes
            ]
        except Exception as e:  # noqa: BLE001
            return key, None, f"normalise: {type(e).__name__}: {e}"
        merged = SVGPath(d=" ".join(path.d for path in normalised))
        if cut_shapes:
            try:
                merged = SVGPath.from_commands(
                    sp.difference(
                        [merged.as_cmd_seq()] + [c.as_cmd_seq() for c in cut_shapes],
                        ["nonzero"] * (1 + len(cut_shapes)),
                    )
                )
            except Exception as e:  # noqa: BLE001
                return key, None, f"cut: {type(e).__name__}: {e}"
        d = merged.round_floats(3).d.strip()
        if d:
            out[opacity] = d
    if not out:
        return key, None, "no visible geometry"
    if key.endswith("-duotone") and "<mask" not in body:
        try:
            opaque = " ".join(d for op, d in out.items() if op >= 1.0)
            overlaps = overlap_layers(translucent_units(paint_body), pico, opaque)
        except Exception as e:  # noqa: BLE001
            return key, None, f"overlap: {type(e).__name__}: {e}"
        if overlaps:
            out["overlaps"] = overlaps
    return key, out, None


def flatten_all(icons: dict) -> dict:
    items = [(k, BODY_OVERRIDES.get(k, v["body"])) for k, v in icons.items()]
    t0 = time.time()
    flat, errors = {}, {}
    with Pool() as pool:
        for done, (key, out, err) in enumerate(pool.imap_unordered(flatten, items, chunksize=25), 1):
            (errors if err else flat)[key] = err or out
            if done % 1000 == 0:
                print(f"  flattened {done}/{len(items)}  ({time.time() - t0:.0f}s)", flush=True)
    print(f"  flattened {len(flat)} icons in {time.time() - t0:.0f}s")
    if errors:
        print(f"  !! {len(errors)} failed:", file=sys.stderr)
        for k, e in errors.items():
            print(f"     {k}: {e}", file=sys.stderr)
        raise SystemExit("aborting: every icon must convert")
    return flat


def to_layers(style_is_duotone: bool, layers: dict) -> tuple[str, str | None]:
    """Collapse an icon's opacity layers into (primary, secondary_or_None)."""
    full = [d for op, d in layers.items() if op >= 1.0]
    partial = [d for op, d in layers.items() if op < 1.0]
    if not style_is_duotone:
        # Monochrome styles: a handful of icons carry a stray translucent shape.
        # Merge everything into one opaque glyph.
        return " ".join(full + partial), None
    return " ".join(full), (" ".join(partial) or None)


# --------------------------------------------------------------------------- 3


def assign_codepoints(locked: dict, bases: list[str], step: int) -> dict:
    """Keep the code points in `locked` and append new `bases` after the highest.

    `locked` maps Solar base names to hex code points. Names that left the
    source stay in it, so their code points are never handed to another icon.
    """
    assigned = {base: int(cp, 16) for base, cp in locked.items()}
    next_cp = max(assigned.values(), default=FIRST_CODEPOINT - step) + step
    for base in bases:
        if base not in assigned:
            assigned[base] = next_cp
            next_cp += step
    return assigned


def build_font(family: str, contours: list[str], out_path: Path, version: str):
    """contours: SVG path data in codepoint order starting at FIRST_CODEPOINT."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.misc.timeTools import timestampSinceEpoch
    from fontTools.misc.transform import Transform
    from fontTools.svgLib.path import parse_path

    # SVG is y-down with origin top-left; fonts are y-up from the baseline.
    to_font = Transform(SCALE, 0, 0, -SCALE, 0, ASCENDER)

    # Glyphs are named after their codepoint: icon names are not guaranteed to be
    # unique once the primary/secondary duotone suffix is appended.
    order = [".notdef"]
    glyf, cmap = {".notdef": TTGlyphPen(None).glyph()}, {}

    for index, d in enumerate(contours):
        codepoint = FIRST_CODEPOINT + index
        name = f"u{codepoint:04X}"
        tt_pen = TTGlyphPen(None)
        if d:
            parse_path(d, TransformPen(Cu2QuPen(tt_pen, max_err=1.0), to_font))
        order.append(name)
        glyf[name] = tt_pen.glyph()
        cmap[codepoint] = name

    fb = FontBuilder(UPEM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyf)

    # A glyph's left side bearing must equal its xMin. Renderers that trust hmtx
    # shift outlines by (lsb - xMin), which slides each glyph by its own offset
    # -- enough to visibly pull a duotone icon's two layers apart.
    glyf_table = fb.font["glyf"]
    metrics = {}
    for name in order:
        glyph = glyf_table[name]
        glyph.recalcBounds(glyf_table)
        metrics[name] = (UPEM, glyph.xMin if glyph.numberOfContours else 0)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENDER, descent=DESCENDER, lineGap=0)
    fb.setupNameTable(
        {
            "familyName": family,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{family}:solar_icons_flutter",
            "fullName": family,
            "psName": family,
            "version": version,
            "copyright": "Solar Icon Set (c) 480 Design, CC BY 4.0",
            "licenseDescription": "Creative Commons Attribution 4.0 International",
            "licenseInfoURL": "https://creativecommons.org/licenses/by/4.0/",
        }
    )
    fb.setupOS2(
        sTypoAscender=ASCENDER,
        sTypoDescender=DESCENDER,
        sTypoLineGap=0,
        usWinAscent=ASCENDER,
        usWinDescent=-DESCENDER,
        sxHeight=ASCENDER,
        sCapHeight=ASCENDER,
        achVendID="SOLR",
        fsType=0,
    )
    fb.setupPost(isFixedPitch=1)

    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    head = fb.font["head"]
    head.created = head.modified = (
        timestampSinceEpoch(int(source_date_epoch))
        if source_date_epoch
        else FONT_TIMESTAMP
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(out_path)


# --------------------------------------------------------------------------- 4

DART_HEADER = """// GENERATED FILE - DO NOT EDIT.
//
// Regenerate with: python3 tool/generate.py
// Source: Solar Icon Set by 480 Design, via {pkg} (CC BY 4.0).

import 'package:flutter/widgets.dart';
{extra_imports}
"""


def emit_dart(class_suffix, family, duotone, entries, version, overlaps):
    """entries: [(dart_name, base_name, codepoint)] -- codepoint is the primary.

    overlaps: {base_name: [codepoint]} for duotone icons with stacked layers.
    """
    extra = "\nimport 'solar_duotone_icon_data.dart';\n" if duotone else ""
    lines = [DART_HEADER.format(pkg=ICONIFY_PKG, extra_imports=extra)]
    kind = "duotone " if duotone else ""
    lines.append(
        f"/// The {len(entries)} {kind}icons of the Solar `{class_suffix}` style.\n"
        f"///\n"
        f"/// ```dart\n"
        f"/// {'SolarDuotoneIcon' if duotone else 'Icon'}(SolarIcons{class_suffix}.{entries[0][0]})\n"
        f"/// ```\n"
        f"abstract final class SolarIcons{class_suffix} {{\n"
        f"  /// The font family that backs this style.\n"
        f"  static const String fontFamily = '{family}';\n"
        f"\n"
        f"  /// The package the font is shipped in.\n"
        f"  static const String fontPackage = 'solar_icons_flutter';\n"
    )
    for name, base, cp in entries:
        lines.append(f"\n  /// Solar `{base}` in the {class_suffix} style.")
        if duotone:
            lines.append(
                f"  static const SolarDuotoneIconData {name} = SolarDuotoneIconData(\n"
                f"    primary: IconData(0x{cp:x}, "
                f"fontFamily: fontFamily, fontPackage: fontPackage),\n"
                f"    secondary: IconData(0x{cp + 1:x}, "
                f"fontFamily: fontFamily, fontPackage: fontPackage),\n"
                + (
                    "    overlaps: <IconData>[\n"
                    + "".join(
                        f"      IconData(0x{o:x}, fontFamily: fontFamily, fontPackage: fontPackage),\n"
                        for o in overlaps[base]
                    )
                    + "    ],\n"
                    if base in overlaps
                    else ""
                )
                + "  );"
            )
        else:
            lines.append(
                f"  static const IconData {name} = "
                f"IconData(0x{cp:x}, fontFamily: fontFamily, fontPackage: fontPackage);"
            )
    lines.append("\n}\n")
    return "\n".join(lines)


def emit_index(class_suffix, module, duotone, entries):
    """A const name -> icon map for the opt-in dynamic-lookup library."""
    kind = "SolarDuotoneIconData" if duotone else "IconData"
    imports = (
        "import '../solar_duotone_icon_data.dart';"
        if duotone
        else "import 'package:flutter/widgets.dart';"
    )
    lines = [
        "// GENERATED FILE - DO NOT EDIT.",
        "//",
        "// Regenerate with: python3 tool/generate.py",
        f"// Source: Solar Icon Set by 480 Design, via {ICONIFY_PKG} (CC BY 4.0).",
        "",
        imports,
        f"import '../{module}.dart';",
        "",
        f"/// Every {class_suffix} icon, keyed by its Solar name (e.g. `'home-smile'`).",
        "///",
        "/// Referencing this map keeps every glyph of this style in the build.",
        f"const Map<String, {kind}> solar{class_suffix}Icons = <String, {kind}>{{",
    ]
    for name, base, _ in entries:
        lines.append(f"  '{base}': SolarIcons{class_suffix}.{name},")
    lines.append("};")
    return "\n".join(lines) + "\n"


INDEX_LIBRARY = """// GENERATED FILE - DO NOT EDIT.
//
// Regenerate with: python3 tool/generate.py

/// Name-keyed maps of every Solar icon, for looking icons up dynamically —
/// from a CMS field, a config file, or a searchable icon picker.
///
/// This library is deliberately **not** exported by `solar_icons_flutter.dart`.
/// A map that mentions every icon defeats icon tree shaking, so importing it
/// pins the full font for each style whose map you touch (roughly 400-600 KB
/// per style). Import it only if you genuinely need lookup by name.
///
/// ```dart
/// import 'package:solar_icons_flutter/solar_icons_index.dart';
///
/// Icon(solarBoldIcons['home-smile']!);
/// Icon(solarIconByName('home-smile', SolarIconStyle.linear)!);
/// ```
library;

import 'package:flutter/widgets.dart';

import 'solar_icons_flutter.dart';
{imports}
export 'solar_icons_flutter.dart';
{exports}
/// Looks up [name] in [style] and returns its full-opacity [IconData].
///
/// For duotone styles this is the primary layer only; use
/// [solarDuotoneIconByName] to get both layers. Returns null if [style] has no
/// icon called [name] — Solar does not draw every icon in every style.
IconData? solarIconByName(String name, SolarIconStyle style) => switch (style) {{
{mono_cases}{duo_cases}    }};

/// Looks up [name] in a duotone [style].
///
/// Returns null if [style] is not a duotone style, or has no icon called [name].
SolarDuotoneIconData? solarDuotoneIconByName(String name, SolarIconStyle style) =>
    switch (style) {{
{duo_only_cases}      _ => null,
    }};
"""


# --------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    version_tag = ICONIFY_PKG.rsplit("@", 1)[-1]
    ap.add_argument(
        "--icons-json",
        type=Path,
        default=ROOT / "tool" / ".cache" / f"icons-{version_tag}.json",
    )
    ap.add_argument("--version", default="1.0")
    args = ap.parse_args()

    args.icons_json.parent.mkdir(parents=True, exist_ok=True)
    print(f"1. source: {ICONIFY_PKG}")
    icon_set = json.loads(fetch_icons_json(args.icons_json).read_text())
    icons = icon_set["icons"]
    locks = json.loads(CODEPOINTS.read_text()) if CODEPOINTS.exists() else {}
    # Solar renames icons by turning the old name into an alias. Names that
    # already shipped stay, drawn from their new artwork.
    class_suffixes = {suffix: class_suffix for suffix, class_suffix, *_ in STYLES}
    for alias, spec in icon_set.get("aliases", {}).items():
        base, suffix = split_key(alias)
        if alias in icons or base not in locks.get(class_suffixes.get(suffix), {}):
            continue
        if set(spec) != {"parent"} or spec["parent"] not in icons:
            raise SystemExit(f"shipped icon {alias} became an unsupported alias: {spec}")
        icons[alias] = icons[spec["parent"]]
    print(f"   {len(icons)} icons")

    print("2. flattening (picosvg: stroke -> fill, groups/transforms resolved)")
    flat = flatten_all(icons)

    print("3. building fonts + Dart")
    summary, indexes = [], []
    for suffix, class_suffix, family, duotone in STYLES:
        keys = sorted(k for k in flat if split_key(k)[1] == suffix)
        step = 2 if duotone else 1
        stacked = {
            split_key(k)[0]: flat[k].pop("overlaps") for k in keys if "overlaps" in flat[k]
        }
        assigned = assign_codepoints(
            locks.get(class_suffix, {}),
            [split_key(k)[0] for k in keys]
            + [f"{base}/overlap{n}" for base in sorted(stacked) for n in range(1, len(stacked[base]) + 1)],
            step,
        )
        locks[class_suffix] = {base: f"0x{cp:x}" for base, cp in assigned.items()}
        contours = [""] * (max(assigned.values()) + step - FIRST_CODEPOINT)
        entries = []
        n_secondary = 0
        for key in keys:
            base = split_key(key)[0]
            cp = assigned[base]
            primary, secondary = to_layers(duotone, flat[key])
            contours[cp - FIRST_CODEPOINT] = primary
            if duotone:
                contours[cp + 1 - FIRST_CODEPOINT] = secondary or ""
                n_secondary += 1 if secondary else 0
            entries.append((dart_name(base), base, cp))
        overlaps = {}
        for base, layers in stacked.items():
            overlaps[base] = [assigned[f"{base}/overlap{n}"] for n in range(1, len(layers) + 1)]
            for cp, d in zip(overlaps[base], layers):
                contours[cp - FIRST_CODEPOINT] = d

        names = Counter(name for name, _, _ in entries)
        clashes = {n: c for n, c in names.items() if c > 1}
        if clashes:
            raise SystemExit(f"duplicate Dart identifiers in {class_suffix}: {clashes}")

        font_path = FONT_DIR / f"{family}.ttf"
        build_font(family, contours, font_path, args.version)
        dart_path = SRC_DIR / f"solar_icons_{suffix.replace('-', '_')}.dart"
        dart_path.write_text(emit_dart(class_suffix, family, duotone, entries, args.version, overlaps))
        module = f"src/solar_icons_{suffix.replace('-', '_')}"
        index_path = SRC_DIR / "index" / f"solar_icons_{suffix.replace('-', '_')}_index.dart"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(emit_index(class_suffix, module.replace("src/", ""), duotone, entries))
        indexes.append((class_suffix, suffix.replace("-", "_"), duotone))

        kb = font_path.stat().st_size / 1024
        summary.append((class_suffix, len(entries), n_secondary, kb, font_path.name))
        print(f"   {class_suffix:<12} {len(entries):>5} icons  {kb:>7.0f} KB  {font_path.name}")

    total_kb = sum(s[3] for s in summary)
    print(f"   {'TOTAL':<12} {sum(s[1] for s in summary):>5} icons  {total_kb:>7.0f} KB")

    # SolarIconStyle members are the class suffix in lowerCamelCase.
    def enum_member(class_suffix: str) -> str:
        return class_suffix[0].lower() + class_suffix[1:]

    (ROOT / "lib" / "solar_icons_index.dart").write_text(
        INDEX_LIBRARY.format(
            imports="".join(f"import 'src/index/solar_icons_{m}_index.dart';\n" for _, m, _ in indexes),
            exports="".join(f"export 'src/index/solar_icons_{m}_index.dart';\n" for _, m, _ in indexes),
            mono_cases="".join(
                f"      SolarIconStyle.{enum_member(c)} => solar{c}Icons[name],\n"
                for c, _, d in indexes
                if not d
            ),
            duo_cases="".join(
                f"      SolarIconStyle.{enum_member(c)} => solar{c}Icons[name]?.primary,\n"
                for c, _, d in indexes
                if d
            ),
            duo_only_cases="".join(
                f"      SolarIconStyle.{enum_member(c)} => solar{c}Icons[name],\n"
                for c, _, d in indexes
                if d
            ),
        )
    )

    # pana scores formatting, and hand-rolled emission will not match the
    # formatter exactly. Let `dart format` be the authority on layout.
    print("4. dart format")
    subprocess.run(
        ["dart", "format", str(ROOT / "lib"), str(ROOT / "test")],
        check=True,
        capture_output=True,
    )

    CODEPOINTS.write_text(json.dumps(locks, indent=2, sort_keys=True) + "\n")

    (ROOT / "tool" / "manifest.json").write_text(
        json.dumps(
            {
                "source": ICONIFY_PKG,
                "unitsPerEm": UPEM,
                "firstCodePoint": f"0x{FIRST_CODEPOINT:x}",
                "styles": [
                    {"class": f"SolarIcons{c}", "icons": n, "duotoneLayers": d, "font": f}
                    for c, n, d, _, f in summary
                ],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
