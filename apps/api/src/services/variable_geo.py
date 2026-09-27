"""Workshop's geospatial operations on variables (§568; `workshop` p.142).

    "Geospatial: Geohash from geopoint: Converts a given geopoint into a
     geohash value as a string. Latitude from geopoint: Returns the numeric
     latitude value from a given geopoint. Longitude from geopoint: Returns
     the numeric longitude value from a given geopoint. MGRS from geopoint:
     Converts a given geopoint into an MGRS value as a string." (p.142)

A geopoint is what a geopoint property holds, `{"lat", "lon"}` - read off an
object by `object_property` - or the "lat,lon" text p.139's String → GeoPoint
describes; both are read by the ontology's own `_coerce_geopoint`, so a
geopoint means the same here as on an object.

**The geohash** is the standard base-32 interleaving, to a precision of 1 to
12 characters (12 by default, about 4 cm).

**MGRS** is WGS84 UTM with its 100 km square letters, written without spaces
to 1 m (`31UDQ4825111943`), each figure truncated rather than rounded, as the
standard's own implementation does: a grid reference names the square a point
is in. It covers 80°S to 84°N with Norway's and Svalbard's zone exceptions.
The poles are UPS, a different projection, and are refused rather than
answered wrong.
"""
from __future__ import annotations

import math
from typing import Any

from .property_values import PropertyValueError, _coerce_geopoint

ARITY = {"geohash": 1, "latitude": 1, "longitude": 1, "mgrs": 1}
TRANSFORMS = tuple(ARITY)
MAX_GEOHASH = 12
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

# WGS84, and UTM's scale on its central meridian.
_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 0.9996
_BANDS = "CDEFGHJKLMNPQRSTUVWX"
_COLUMNS = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")
_ROWS = "ABCDEFGHJKLMNPQRSTUV"


class GeoError(ValueError):
    """An input that is not a geopoint, or one MGRS here cannot name."""


def check(transform: str, inputs: int, config: dict[str, Any]) -> str | None:
    if inputs != 1:
        return f"{transform} takes 1 input"
    if transform == "geohash":
        precision = config.get("precision", MAX_GEOHASH)
        if isinstance(precision, bool) or not isinstance(precision, int) \
                or not 1 <= precision <= MAX_GEOHASH:
            return f"geohash's precision must be a whole number of characters from 1 to {MAX_GEOHASH}"
    return None


def geohash(lat: float, lon: float, precision: int) -> str:
    """The standard geohash: longitude and latitude halved in turn, five bits
    a character."""
    lats, lons = [-90.0, 90.0], [-180.0, 180.0]
    out, bits, bit, even = [], 0, 0, True
    while len(out) < precision:
        span, value = (lons, lon) if even else (lats, lat)
        middle = (span[0] + span[1]) / 2
        if value >= middle:
            bits = bits * 2 + 1
            span[0] = middle
        else:
            bits = bits * 2
            span[1] = middle
        even = not even
        bit += 1
        if bit == 5:
            out.append(_BASE32[bits])
            bits = bit = 0
    return "".join(out)


def _zone(lat: float, lon: float) -> int:
    if 56 <= lat < 64 and 3 <= lon < 12:
        return 32  # Norway's west coast.
    if 72 <= lat < 84 and 0 <= lon < 42:
        return 31 if lon < 9 else 33 if lon < 21 else 35 if lon < 33 else 37  # Svalbard.
    return int((lon + 180) // 6) + 1


def mgrs(lat: float, lon: float) -> str:
    """A geopoint's MGRS reference, to 1 m."""
    if not -80 <= lat <= 84:
        raise GeoError("MGRS here covers 80°S to 84°N; the poles are UPS, which is not supported")
    # 180°E is 180°W, zone 1, as GeoTrans has it.
    if lon >= 180:
        lon -= 360
    zone = _zone(lat, lon)
    phi = math.radians(lat)
    lam = math.radians(lon) - math.radians((zone - 1) * 6 - 180 + 3)
    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = _EP2 * math.cos(phi) ** 2
    a = math.cos(phi) * lam
    e4, e6 = _E2 ** 2, _E2 ** 3
    m = _A * ((1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
              - (3 * _E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
              + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
              - (35 * e6 / 3072) * math.sin(6 * phi))
    easting = _K0 * n * (a + (1 - t + c) * a ** 3 / 6
                         + (5 - 18 * t + t ** 2 + 72 * c - 58 * _EP2) * a ** 5 / 120) + 500000
    northing = _K0 * (m + n * math.tan(phi) * (
        a ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * a ** 4 / 24
        + (61 - 58 * t + t ** 2 + 600 * c - 330 * _EP2) * a ** 6 / 720))
    # No false northing south of the Equator: its 10,000 km is five whole
    # cycles of the 2,000 km row letters, so the letters and figures are the
    # same without it (adding it survived the sweep as equivalent).
    band = _BANDS[min(int((lat + 80) // 8), len(_BANDS) - 1)]
    column = _COLUMNS[(zone - 1) % 3][int(easting // 100_000) - 1]
    row = _ROWS[(int(northing // 100_000) + (5 if zone % 2 == 0 else 0)) % 20]
    return (f"{zone:02d}{band}{column}{row}"
            f"{int(easting % 100_000):05d}{int(northing % 100_000):05d}")


def apply(transform: str, inputs: list[Any], config: dict[str, Any], label: str) -> Any:
    if inputs[0] is None:
        return None
    try:
        point = _coerce_geopoint(inputs[0])
    except PropertyValueError as exc:
        raise GeoError(f"{label!r} takes a geopoint: {exc}") from None
    lat, lon = point["lat"], point["lon"]
    if transform == "latitude":
        return lat
    if transform == "longitude":
        return lon
    if transform == "geohash":
        return geohash(lat, lon, int(config.get("precision", MAX_GEOHASH)))
    return mgrs(lat, lon)
