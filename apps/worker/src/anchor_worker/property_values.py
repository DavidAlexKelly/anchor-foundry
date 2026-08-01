"""Property value semantics: what a declared property type actually means
(ROADMAP Objects item 4, db migration 0029).

**This file is duplicated verbatim in `apps/worker/src/anchor_worker/` and a
test asserts the two are byte-identical.** It is the fifth such mirror in this
build (dataset_engine, storage, connectors, the expectations evaluator, now
this), and STATUS's rough edges say the fifth should have been a shared
package instead. The judgement made here, recorded rather than hidden: this
module is ~150 lines of pure standard-library Python with no imports from
either app, so byte-parity is mechanically checkable in a way the connector
registries are not - and the shared package needs both service images moved
to a repo-root Docker build context, which is a change with its own risk that
should not ride along inside a property-types feature. The parity test is the
mitigation, not the fix. Whoever needs a sixth mirror should stop and build
the package.

Why it exists at all: `geopoint` and `timestamp` have been in the
property_data_type enum since migration 0003 as labels nothing enforced. The
sync path wrote whatever a column held and the action path checked only
integer/float/boolean/string, so a `geopoint` property accepted the string
"banana". Both write paths now run every value through
`coerce_property_value`, which is why this has to be shared: a type enforced
on one path and not the other is not a type.
"""
from __future__ import annotations

from typing import Any


class PropertyValueError(ValueError):
    """A value that does not fit its property's declared type."""


def _coerce_geopoint(value: Any) -> dict[str, float]:
    """Accepts the two shapes a geopoint actually arrives in and normalises
    both to {"lat", "lon"}.

    A mapping (Parquet STRUCT, JSON object) under any of the usual key
    spellings, or the "lat,lon" text a CSV column holds. Both are real: the
    dataset layer reads Parquet and CSV with equal standing, and a coordinate
    column in a CSV export is a string every time.

    Order is lat,lon rather than lon,lat. That is a choice with no right
    answer - GeoJSON says lon,lat, nearly every consumer UI says lat,lon -
    so it is stated here, enforced by the range checks below (a latitude
    outside ±90 is refused, which catches the transposed case for most of the
    world), and written into the type's own documentation.
    """
    if isinstance(value, dict):
        keys = {k.lower(): v for k, v in value.items()}
        lat = keys.get("lat", keys.get("latitude"))
        lon = keys.get("lon", keys.get("lng", keys.get("longitude")))
        if lat is None or lon is None:
            raise PropertyValueError(
                f"a geopoint needs lat and lon, got keys {sorted(value)}"
            )
    elif isinstance(value, str):
        parts = value.split(",")
        if len(parts) != 2:
            raise PropertyValueError(
                f"expected a geopoint as 'lat,lon', got {value!r}"
            )
        lat, lon = parts
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        lat, lon = value
    else:
        raise PropertyValueError(f"cannot read {value!r} as a geopoint")

    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError) as exc:
        raise PropertyValueError(f"geopoint coordinates are not numbers: {value!r}") from exc
    if not -90 <= lat_f <= 90:
        raise PropertyValueError(
            f"latitude {lat_f} is out of range (values are lat,lon - did you "
            "send lon,lat?)"
        )
    if not -180 <= lon_f <= 180:
        raise PropertyValueError(f"longitude {lon_f} is out of range")
    return {"lat": lat_f, "lon": lon_f}


ATTACHMENT_FIELDS = ("key", "filename", "content_type", "size")


def _coerce_attachment(value: Any) -> dict[str, Any]:
    """An attachment value is a reference the platform wrote, not something a
    user types, so this validates shape rather than trying to be generous:
    anything that is not the object `POST .../attachments` returned is a
    caller mistake.

    A **JSON string** is also accepted, and that is not laxity - it is the
    round trip. Write-back stores the whole reference as JSON text in the
    dataset column (`column_value` below), and the next sync reads that column
    and comes back through here. Accepting only a dict would mean an
    attachment survived exactly until the source was re-synced, which is the
    same as not working.

    Fabricating a key buys nothing: the download route checks every key
    against the workspace's own storage prefix, which is where that boundary
    actually lives.
    """
    if isinstance(value, str):
        import json as _json

        try:
            value = _json.loads(value)
        except ValueError as exc:
            raise PropertyValueError(
                f"expected an attachment reference, got {value[:40]!r}"
            ) from exc
    if not isinstance(value, dict):
        raise PropertyValueError(
            "an attachment value must be the object returned by the upload "
            f"endpoint, got {type(value).__name__}"
        )
    missing = [f for f in ATTACHMENT_FIELDS if f not in value]
    if missing:
        raise PropertyValueError(f"attachment is missing {', '.join(missing)}")
    return {f: value[f] for f in ATTACHMENT_FIELDS}


def _coerce_temporal(value: Any, *, data_type: str) -> str:
    """ISO-8601 in, ISO-8601 out. An offset is preserved when the value has
    one and simply absent when it does not - see migration 0029 for why there
    is no separate timestamptz type."""
    import datetime as _dt

    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    text_value = str(value).strip()
    candidate = text_value.replace("Z", "+00:00")  # fromisoformat rejects Z < 3.11
    try:
        parsed: _dt.date = (
            _dt.date.fromisoformat(candidate) if data_type == "date"
            else _dt.datetime.fromisoformat(candidate)
        )
    except ValueError as exc:
        raise PropertyValueError(
            f"expected an ISO-8601 {data_type}, got {text_value!r}"
        ) from exc
    return parsed.isoformat()


def _coerce_integer(value: Any) -> int:
    """Coerce, do not merely check. A CSV column arrives as text and a Parquet
    column as a number; both are the same integer, and a type that accepted
    one but not the other would be describing the file format rather than the
    data. A float is accepted only when it is exactly integral - 3.0 is the
    integer 3, 3.5 is a different number and silently truncating it is the
    kind of quiet data loss this codebase refuses elsewhere."""
    if isinstance(value, bool):
        raise PropertyValueError(f"expected an integer, got the boolean {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise PropertyValueError(f"{value!r} is not a whole number")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise PropertyValueError(f"expected an integer, got {value!r}") from exc
    raise PropertyValueError(f"expected an integer, got {type(value).__name__}")


def _coerce_float(value: Any) -> float:
    if isinstance(value, bool):
        raise PropertyValueError(f"expected a number, got the boolean {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise PropertyValueError(f"expected a number, got {value!r}") from exc
    raise PropertyValueError(f"expected a number, got {type(value).__name__}")


_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0"}


def _coerce_boolean(value: Any) -> bool:
    """The spellings a CSV actually contains. Deliberately *not* Python's
    truthiness: "0" and "no" are true strings and would both become True, and
    a boolean column that reads every non-empty cell as true is worse than no
    boolean column at all."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
    raise PropertyValueError(f"expected a boolean, got {value!r}")


def coerce_property_value(data_type: str, value: Any) -> Any:
    """The single definition of what a property value may be (db 0029).

    Used by both write paths - dataset sync (`instances.extract_rows`) and
    action write-back (`actions.validate_submitted_values`) - because a type
    enforced on one path and not the other is not a type. Before this, every
    non-scalar label was decorative: a `geopoint` property accepted the string
    "banana" from an action and stored whatever a CSV column happened to hold
    from a sync.

    Returns the *normalised* value, so a geopoint read from "51.5,-0.12" and
    one written as {"lat": .., "lon": ..} land in storage identically - a
    property whose stored shape depended on which path wrote it would push
    that problem onto every reader, including the Canvas map widget this item
    exists to unblock.

    None passes through: absent is not a type error, and `required` is a
    separate concern the ontology already models.
    """
    if value is None:
        return None
    if data_type == "geopoint":
        return _coerce_geopoint(value)
    if data_type == "attachment":
        return _coerce_attachment(value)
    if data_type in ("date", "timestamp"):
        return _coerce_temporal(value, data_type=data_type)
    if data_type == "integer":
        return _coerce_integer(value)
    if data_type == "float":
        return _coerce_float(value)
    if data_type == "boolean":
        return _coerce_boolean(value)
    if data_type == "string":
        # Any scalar renders as a string losslessly, and this is the commonest
        # mapping there is: an id column DuckDB reads as BIGINT, mapped to a
        # property whose declared type is string. Refusing that would make the
        # type system hostile for no gain - it is the *ambiguous* conversions
        # that are worth refusing, not the total ones.
        if isinstance(value, (dict, list)):
            raise PropertyValueError(f"expected a string, got {type(value).__name__}")
        # A bool is refused rather than rendered. A number in a string column
        # is a *format* difference (the same id, read from CSV or Parquet); a
        # JSON `true` submitted for a name field is a caller mistake, and
        # turning it into "true" would store the mistake instead of reporting
        # it.
        if isinstance(value, bool):
            raise PropertyValueError(f"expected a string, got the boolean {value!r}")
        return str(value)
    # json is deliberately unconstrained - it is the escape hatch, and
    # constraining it would leave nowhere to put a value that has no type yet.
    return value


def column_value(data_type: str, value: Any) -> Any:
    """The flat form of a property value, for writing back into a dataset
    column (roadmap Objects item 4).

    A dataset column holds a scalar; a geopoint and an attachment do not.
    Rather than refuse write-back for the two structured types - which would
    make them second-class the moment anyone built a form - the value is
    flattened on the way into the Parquet copy while the ontology keeps the
    structured version. A geopoint becomes the "lat,lon" text it is most
    often read from, which round-trips exactly through
    `coerce_property_value` on the next sync. An attachment becomes its
    storage key, which is the only part of it that is not derivable.
    """
    if value is None:
        return None
    if data_type == "geopoint" and isinstance(value, dict):
        return f"{value['lat']},{value['lon']}"
    if data_type == "attachment" and isinstance(value, dict):
        # The whole reference, as JSON text, not just the key: filename,
        # content type and size are not derivable from a storage key, and a
        # round trip that lost them would degrade the attachment a little on
        # every sync.
        import json as _json

        return _json.dumps(value, sort_keys=True)
    return value




def coerce_rows(
    rows: list[tuple[str, dict[str, Any]]], property_types: dict[str, str]
) -> list[tuple[str, dict[str, Any]]]:
    """Apply the declared types to a whole sync's worth of extracted rows.

    Kept out of `extract_rows` on purpose: that function's job is "read these
    columns out of this Parquet file", it is mirrored in the worker too, and
    giving it a second responsibility would mean two mirrors to keep in step
    instead of one.

    **A bad value fails the whole sync**, loudly, naming the property, the
    primary key and the value. The alternative - null out what will not
    coerce and carry on - is the failure this codebase keeps refusing: the
    row would arrive looking complete with a field silently missing, and
    nothing downstream would ever report it. A sync that stops with "row 4181:
    location 'banana' is not a geopoint" is a mapping the user can fix; a sync
    that quietly drops it is a bug they find months later.

    A property with no declared type is passed through untouched rather than
    guessed at - the mapping names properties that exist, and one that does
    not is a §38 edit racing a sync, not a value to reinterpret.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for primary_key, properties in rows:
        coerced: dict[str, Any] = {}
        for name, value in properties.items():
            data_type = property_types.get(name)
            if data_type is None:
                coerced[name] = value
                continue
            try:
                coerced[name] = coerce_property_value(data_type, value)
            except PropertyValueError as exc:
                raise PropertyValueError(
                    f"row {primary_key!r}: {name} ({data_type}) - {exc}"
                ) from exc
        out.append((primary_key, coerced))
    return out
