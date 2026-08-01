"""Regenerate the world outline in `src/components/canvas/basemap.ts`
(ROADMAP Canvas item 4).

The map widget ships its basemap *in the bundle* rather than fetching tiles —
see the module docstring in `basemap.ts` for why. This script is what makes
that data reproducible rather than a blob somebody pasted in once.

Source: Natural Earth 1:110m Admin 0 Countries, public domain (CC0).
    curl -o /tmp/ne110.json \\
      https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson

Usage:
    python3 scripts/make-basemap.py 0.3 /tmp/ne110.json > /tmp/world.path

Output is one SVG path in x=lon, y=-lat coordinates, so the component applies
a plain affine transform rather than carrying a projection. The tolerance
argument is degrees of Douglas-Peucker error: 0.3 gives a world recognisable
at widget size in ~60 KB; 0.6 halves that and starts losing small islands.
"""
import json
import sys

EPS = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
MIN_POINTS = 5


def perp(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return ((x - (x1 + t * dx)) ** 2 + (y - (y1 + t * dy)) ** 2) ** 0.5


def simplify(points, eps):
    """Douglas-Peucker, iteratively - a world coastline is deep enough that a
    recursive implementation is a stack overflow waiting to happen."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        worst, wi = 0.0, -1
        for i in range(lo + 1, hi):
            d = perp(points[i], points[lo], points[hi])
            if d > worst:
                worst, wi = d, i
        if worst > eps:
            keep[wi] = True
            stack.append((lo, wi))
            stack.append((wi, hi))
    return [p for p, k in zip(points, keep) if k]


def rings(geom):
    """Outer rings only. Holes (a lake inside a country) are not worth the
    bytes at this scale, and dropping them cannot mislead: the basemap is
    context behind the pins, never a source of anybody's data."""
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


data = json.load(open(sys.argv[2] if len(sys.argv) > 2 else "/tmp/ne110.json"))
parts = []
for feature in data["features"]:
    for ring in rings(feature["geometry"]):
        pts = simplify([(round(x, 2), round(-y, 2)) for x, y in ring], EPS)
        # What a simplified ring degenerates into: a sliver of three or four
        # points is noise on a world map, not an island anyone recognises.
        if len(pts) < MIN_POINTS:
            continue
        d = f"M{pts[0][0]} {pts[0][1]}" + "".join(f"L{x} {y}" for x, y in pts[1:]) + "Z"
        parts.append(d)

path = "".join(parts)
print(f"rings={len(parts)} chars={len(path)}", file=sys.stderr)
sys.stdout.write(path)
