#!/usr/bin/env python3
"""
Estimate real-world lat/lng polygons for buildings that already have a
hand-traced shape in the app's schematic map (BUILDING_SHAPES) but no
real coordinates yet in BUILDING_DIRECTORY (buildings.csv) — typically
newer buildings that OpenStreetMap hasn't surveyed.

How it works
------------
Every building that has BOTH a schematic shape AND a real lat/lng acts as
a calibration point: its shape's pixel centroid is paired with its known
real coordinate. Buildings are grouped by zone (1, 2, 3, ...) since the
schematic drawing isn't drawn to a single consistent scale/rotation across
the whole campus — fitting one affine transform per zone (using that
zone's calibration points) is far more accurate than one transform for
the whole map. That transform is then applied to the full pixel polygon
of each shape-only, no-coordinates building in the same zone.

This needs no new tracing or Illustrator work — it reads data that's
already in index.html.

Usage
-----
  python3 tools/geolocate_schematic_shapes.py ../index.html --out estimated_buildings.json

Output JSON: { "<building num>": { "lat": .., "lng": .., "poly": [[lat,lng],...],
               "zone": "..", "fit_residual_m": .. } }

`fit_residual_m` is not this building's own error — it's the zone's
average calibration residual (how well the fitted transform reproduces
the zone's *known* buildings), included so you can see how much to trust
the estimate. A few meters is normal; tens of meters means that zone's
schematic drawing is too distorted for a linear fit and needs manual
correction (or real tracing via svg_to_latlng.py) instead.
"""
import argparse
import json
import re
import sys
from collections import defaultdict


def solve3(rows):
    m = [row[:] for row in rows]
    n = 3
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(m[r][i]))
        if abs(m[piv][i]) < 1e-9:
            raise ValueError('degenerate calibration points (collinear?)')
        m[i], m[piv] = m[piv], m[i]
        pivot = m[i][i]
        m[i] = [v / pivot for v in m[i]]
        for r in range(n):
            if r != i:
                factor = m[r][i]
                m[r] = [mv - factor * iv for mv, iv in zip(m[r], m[i])]
    return [m[i][3] for i in range(n)]


def fit_affine(refs):
    """refs: list of (px, py, lat, lng). Needs >= 3 non-collinear points."""
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


def haversine_m(lat1, lng1, lat2, lng2):
    import math
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(min(1, a ** 0.5))


def extract_directory(src):
    i = src.find('const BUILDING_DIRECTORY')
    j = src.find('];', i)
    block = src[i:j + 1].replace('\\"', '"')
    rows = re.findall(
        r'num:\s*"([A-Za-z0-9]+)".*?zone:\s*"([A-Za-z0-9]+)".*?lat:\s*(null|[\d.\-]+),\s*lng:\s*(null|[\d.\-]+)',
        block)
    out = {}
    for num, zone, lat, lng in rows:
        out[num] = {
            'zone': zone,
            'lat': None if lat == 'null' else float(lat),
            'lng': None if lng == 'null' else float(lng),
        }
    return out


def extract_shapes(src):
    i = src.find('const BUILDING_SHAPES')
    j = src.find('};', i)
    block = src[i:j + 1]
    pairs = re.findall(r"'([A-Za-z0-9]+)':\s*'([^']+)'", block)
    out = {}
    for num, pts_str in pairs:
        pts = []
        for tok in pts_str.strip().split():
            x, y = tok.split(',')
            pts.append((float(x), float(y)))
        out[num] = pts


    return out


def centroid(pts):
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('index_html', help='path to the app\'s index.html')
    ap.add_argument('--out', default='estimated_buildings.json')
    ap.add_argument('--decimals', type=int, default=6)
    args = ap.parse_args()

    src = open(args.index_html, encoding='utf-8').read()
    directory = extract_directory(src)
    shapes = extract_shapes(src)

    by_zone_calib = defaultdict(list)  # zone -> [(px,py,lat,lng,num), ...]
    missing = []  # (num, zone)
    for num, pts in shapes.items():
        d = directory.get(num)
        zone = d['zone'] if d else None
        if d and d['lat'] is not None and d['lng'] is not None:
            cx, cy = centroid(pts)
            by_zone_calib[zone].append((cx, cy, d['lat'], d['lng'], num))
        else:
            missing.append((num, zone))

    if not missing:
        sys.exit('no shape-only buildings found (everything with a BUILDING_SHAPES entry already has lat/lng)')

    results = {}
    zone_fits = {}
    for zone, calib in by_zone_calib.items():
        if len(calib) < 4:
            # 3 points gives an exact interpolating fit with zero redundancy —
            # it looks "perfect" on the calibration points themselves but can
            # extrapolate wildly for a building outside their triangle. Require
            # a 4th point so the fit is a real (checkable) least-squares fit.
            continue
        refs = [(c[0], c[1], c[2], c[3]) for c in calib]
        transform = fit_affine(refs)
        residuals = []
        for px, py, lat, lng, num in calib:
            tlat, tlng = transform(px, py)
            residuals.append(haversine_m(lat, lng, tlat, tlng))
        avg_res = sum(residuals) / len(residuals)
        zone_fits[zone] = (transform, avg_res, len(calib))

    print('Per-zone calibration fit quality (lower is better; this is how well the fit')
    print('reproduces buildings whose real coordinates we already know):')
    for zone, (transform, avg_res, n) in sorted(zone_fits.items()):
        print(f'  zone {zone}: {n} calibration buildings, avg residual {avg_res:.1f} m')

    MAX_DIAGONAL_M = 120  # no real building on this campus should span more than this

    skipped = []
    for num, zone in missing:
        if zone not in zone_fits:
            skipped.append((num, 'zone has fewer than 4 calibrated buildings'))
            continue
        transform, avg_res, n = zone_fits[zone]
        pts = shapes[num]
        poly = [[round(lat, args.decimals), round(lng, args.decimals)]
                for lat, lng in (transform(x, y) for x, y in pts)]
        lats = [p[0] for p in poly]
        lngs = [p[1] for p in poly]
        diagonal = haversine_m(min(lats), min(lngs), max(lats), max(lngs))
        if diagonal > MAX_DIAGONAL_M:
            skipped.append((num, f'estimated shape spans {diagonal:.0f}m — the fit is '
                                  f'extrapolating too far from its calibration points to trust'))
            continue
        clat, clng = centroid([(p[0], p[1]) for p in poly])
        results[num] = {
            'zone': zone,
            'lat': round(clat, args.decimals),
            'lng': round(clng, args.decimals),
            'poly': poly,
            'fit_residual_m': round(avg_res, 1),
        }

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f'\nEstimated real coordinates for {len(results)} building(s) -> {args.out}')
    for num, r in results.items():
        print(f'  {num}: {r["lat"]}, {r["lng"]}  (zone {r["zone"]}, ~{r["fit_residual_m"]}m expected accuracy)')
    if skipped:
        print(f'\nCould not estimate {len(skipped)} building(s) — these need manual placement')
        print('(the app\'s existing "place on map" admin tool) or real tracing via svg_to_latlng.py:')
        for num, reason in skipped:
            print(f'  {num}: {reason}')


if __name__ == '__main__':
    main()
