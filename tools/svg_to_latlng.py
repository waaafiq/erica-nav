#!/usr/bin/env python3
"""
Convert building footprints traced in Illustrator (exported as SVG) into
real-world lat/lng polygons, so buildings missing from OpenStreetMap can
still get an accurate outline on the map.

Workflow
--------
1. Screenshot the app's own real map (or any north-up satellite view) at a
   fixed pan/zoom. Note the lat/lng of two spots you can identify precisely
   in that screenshot (e.g. two building corners already in buildings.csv,
   or the map's visible corners).
2. Import the screenshot into Illustrator as a locked template layer.
3. Trace each new building as a closed path with the pen tool (straight
   corners — don't drag control handles). Rename each path (double-click it
   in the Layers panel) to the building's number from buildings.csv, e.g. "105".
4. File > Export > Export As > SVG. In the SVG options make sure object
   names are kept (Styling: Presentation Attributes; Object IDs: Layer Names
   or Object Names) so the names survive as element ids in the file.
5. Run this script against the exported SVG with 2-3 reference points.

Usage
-----
  python3 svg_to_latlng.py traced.svg \\
      --ref "120,340=37.29701,126.83235" \\
      --ref "980,610=37.29655,126.83410" \\
      --out custom_buildings.json

Give 2 --ref points for a simple north-up scale/offset (use this when the
base image is a straight screenshot of the app's own map — already
north-up, no rotation). Give 3+ --ref points for a full affine fit that
also corrects rotation/skew — use this for an angled satellite grab.

Each --ref is "px,py=lat,lng": px,py is the pixel position of a known point
in the SVG's own coordinate space (open the SVG in a text editor or
Illustrator's X/Y readout to find it), and lat,lng is that point's real
coordinate.

Output is a JSON file: { "<building number>": [[lat,lng], [lat,lng], ...] }
ready to merge into the app's building data.
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET


def parse_ref(s):
    px_part, real_part = s.split('=')
    px, py = (float(v) for v in px_part.split(','))
    lat, lng = (float(v) for v in real_part.split(','))
    return (px, py, lat, lng)


def solve3(rows):
    """Gaussian elimination for a 3x3 linear system. rows: [[a,b,c,y], ...] (3 rows)."""
    m = [row[:] for row in rows]
    n = 3
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(m[r][i]))
        if abs(m[piv][i]) < 1e-9:
            raise ValueError('reference points are degenerate (collinear?) — pick 3 non-collinear points')
        m[i], m[piv] = m[piv], m[i]
        pivot = m[i][i]
        m[i] = [v / pivot for v in m[i]]
        for r in range(n):
            if r != i:
                factor = m[r][i]
                m[r] = [mv - factor * iv for mv, iv in zip(m[r], m[i])]
    return [m[i][3] for i in range(n)]


def fit_affine(refs):
    """refs: list of (px, py, lat, lng), len >= 3.
    Fits lat = a*px + b*py + c ; lng = d*px + e*py + f via least squares
    (normal equations solved directly, no numpy needed since it's always 3x3)."""
    n = len(refs)
    sx = sum(r[0] for r in refs)
    sy = sum(r[1] for r in refs)
    sxx = sum(r[0] * r[0] for r in refs)
    syy = sum(r[1] * r[1] for r in refs)
    sxy = sum(r[0] * r[1] for r in refs)
    slat = sum(r[2] for r in refs)
    slng = sum(r[3] for r in refs)
    sxlat = sum(r[0] * r[2] for r in refs)
    sylat = sum(r[1] * r[2] for r in refs)
    sxlng = sum(r[0] * r[3] for r in refs)
    sylng = sum(r[1] * r[3] for r in refs)
    row0 = [sxx, sxy, sx]
    row1 = [sxy, syy, sy]
    row2 = [sx, sy, float(n)]
    a, b, c = solve3([row0 + [sxlat], row1 + [sylat], row2 + [slat]])
    d, e, f = solve3([row0 + [sxlng], row1 + [sylng], row2 + [slng]])

    def transform(px, py):
        return (a * px + b * py + c, d * px + e * py + f)

    return transform


def fit_simple(refs):
    """Exactly 2 points: independent axis-aligned scale + offset (no rotation)."""
    (px1, py1, lat1, lng1), (px2, py2, lat2, lng2) = refs
    if px2 == px1 or py2 == py1:
        raise ValueError('the two reference points must differ in both x and y')
    mlng = (lng2 - lng1) / (px2 - px1)
    mlat = (lat2 - lat1) / (py2 - py1)

    def transform(px, py):
        lat = lat1 + mlat * (py - py1)
        lng = lng1 + mlng * (px - px1)
        return (lat, lng)

    return transform


def parse_path_d(d):
    """Minimal SVG path-data parser -> list of (x,y) anchor points.
    Handles M/L/H/V/C/S/Q/T (absolute + relative) and Z. Curves are
    flattened to their endpoint only, which is fine for building corners
    traced with straight pen-tool clicks."""
    tokens = re.findall(r'[MmLlHhVvCcSsQqTtZz]|-?\d*\.?\d+(?:e-?\d+)?', d)
    points = []
    i = 0
    cx = cy = 0.0
    start_x = start_y = 0.0
    cmd = None

    def nums(k):
        nonlocal i
        vals = [float(tokens[i + j]) for j in range(k)]
        i += k
        return vals

    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
        if cmd in ('M', 'm'):
            x, y = nums(2)
            if cmd == 'm' and points:
                x += cx
                y += cy
            cx, cy = x, y
            start_x, start_y = cx, cy
            points.append((cx, cy))
            cmd = 'L' if cmd == 'M' else 'l'
        elif cmd in ('L', 'l'):
            x, y = nums(2)
            if cmd == 'l':
                x += cx
                y += cy
            cx, cy = x, y
            points.append((cx, cy))
        elif cmd in ('H', 'h'):
            x, = nums(1)
            if cmd == 'h':
                x += cx
            cx = x
            points.append((cx, cy))
        elif cmd in ('V', 'v'):
            y, = nums(1)
            if cmd == 'v':
                y += cy
            cy = y
            points.append((cx, cy))
        elif cmd in ('C', 'c'):
            x1, y1, x2, y2, x, y = nums(6)
            if cmd == 'c':
                x += cx
                y += cy
            cx, cy = x, y
            points.append((cx, cy))
        elif cmd in ('S', 's', 'Q', 'q'):
            vals = nums(4)
            x, y = vals[2], vals[3]
            if cmd in ('s', 'q'):
                x += cx
                y += cy
            cx, cy = x, y
            points.append((cx, cy))
        elif cmd in ('T', 't'):
            x, y = nums(2)
            if cmd == 't':
                x += cx
                y += cy
            cx, cy = x, y
            points.append((cx, cy))
        elif cmd in ('Z', 'z'):
            cx, cy = start_x, start_y
            i += 1
        else:
            i += 1
    return points


def extract_shapes(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()
    shapes = {}
    for el in root.iter():
        tag = el.tag.split('}')[-1]
        eid = el.get('id') or ''
        if tag == 'polygon' and el.get('points'):
            pts = []
            for pair in el.get('points').strip().split():
                x, y = pair.split(',')
                pts.append((float(x), float(y)))
            if pts:
                shapes[eid] = pts
        elif tag == 'path' and el.get('d'):
            pts = parse_path_d(el.get('d'))
            if len(pts) >= 3:
                shapes[eid] = pts
    return shapes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('svg', help='SVG file exported from Illustrator')
    ap.add_argument('--ref', action='append', required=True,
                     help='reference point "px,py=lat,lng" (2 for simple scale, 3+ for full affine fit)')
    ap.add_argument('--out', default='custom_buildings.json', help='output JSON path')
    ap.add_argument('--decimals', type=int, default=6, help='lat/lng rounding')
    args = ap.parse_args()

    refs = [parse_ref(r) for r in args.ref]
    if len(refs) < 2:
        sys.exit('need at least 2 --ref points')
    transform = fit_simple(refs) if len(refs) == 2 else fit_affine(refs)

    print('Reference point check (transformed value should closely match what you typed in):')
    for px, py, lat, lng in refs:
        tlat, tlng = transform(px, py)
        print(f'  ({px:.1f},{py:.1f}) -> {tlat:.6f},{tlng:.6f}   (you gave {lat:.6f},{lng:.6f})')

    shapes = extract_shapes(args.svg)
    if not shapes:
        sys.exit('no <path> or <polygon> elements with usable geometry found in the SVG')

    out = {}
    skipped = []
    for eid, pts in shapes.items():
        num = re.sub(r'\D', '', eid)  # "path105" -> "105"; plain "105" -> "105"
        if not num:
            skipped.append(eid or '(no id)')
            continue
        poly = [[round(lat, args.decimals), round(lng, args.decimals)]
                for lat, lng in (transform(x, y) for x, y in pts)]
        out[num] = poly

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f'\nWrote {len(out)} building polygon(s) to {args.out}')
    if skipped:
        print(f'Skipped {len(skipped)} shape(s) with no digits in their id — '
              f'rename them in Illustrator to the building number and re-export: {skipped}')


if __name__ == '__main__':
    main()
