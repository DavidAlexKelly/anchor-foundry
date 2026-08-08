"""A small real OpenSearch-shaped HTTP API for the instance store tests.

Runs as its own process (`python opensearch_fixture_server.py <port>`) so
`OpenSearchInstanceStore` drives a genuine socket through the genuine
`opensearchpy.AsyncOpenSearch` client - the same standard the REST connector
is held to (rest_fixture_server.py), and for the same reason: a mocked
client tests the mock's shape, not the gateway's.

What this *is*: enough of the REST surface, with real semantics, for every
call the gateway makes - index exists/create, bulk upsert, delete_by_query
on a term + range filter, search with a term filter, sort, from/size and a
total, get by id, and partial update.

Mapping enforcement, as of decision 0006 §7: `indices.create` bodies are
remembered, values are coerced and compared by their declared type, and a
document or query that contradicts the mapping is refused the way a cluster
refuses it. Until that existed every field was text here, so a store that
mapped `capacity` as an integer and one that left it alone gave identical
answers - which is exactly the disagreement typed properties exist to remove,
invisible to the only test that could have seen it.

What this is **still not**: OpenSearch. There are no analyzers, no scoring, no
refresh semantics, no sharding, and the mapping rules implemented are the ones
this platform writes rather than the whole language. It proves the gateway
forms correct requests, reads responses correctly, and does not contradict the
mapping it declared; it cannot prove a real cluster agrees. That remaining gap
is stated in STATUS rather than papered over, and decision 0006 lists checking
it as a deployment step.

Endpoints:
  GET    /                        version banner (client handshake)
  HEAD   /{index}                 indices.exists
  PUT    /{index}                 indices.create
  POST   /_bulk                   update + doc_as_upsert only
  POST   /{index}/_delete_by_query
  POST   /{index}/_search       term/terms/range/multi_match in filter/must/
                                should (+minimum_should_match)/must_not, sorted+paged
  GET    /{index}/_doc/{id}
  POST   /{index}/_update/{id}
  POST   /__reset                 test helper: forget every index
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# index name -> {doc_id: source}
INDICES: dict[str, dict[str, dict]] = {}

# index name -> the mapping body `indices.create` was given. Kept so the
# fixture can *contradict* a wrong one (decision 0006 §7): until it did, every
# field was text as far as this process was concerned, so a store that mapped
# `capacity` as an integer and one that left it as text produced identical
# answers here - which is precisely the disagreement typed properties exist to
# remove, invisible to the only test that could have seen it.
MAPPINGS: dict[str, dict] = {}


MISSING = object()


class MappingError(ValueError):
    """A document or query that contradicts the index's declared mapping.

    Its own type, because a real cluster answers these with 400 and a
    `mapper_parsing_exception` rather than by quietly coercing - and decision
    0006 §5 turns on that failure being reachable in a test.
    """


def _declared_type(index: str, field: str) -> str | None:
    """The mapping's type for a field path, or None where nothing declares one.

    Honours explicit `properties` first and `dynamic_templates` second, which is
    the order a real cluster resolves them in: a named field beats a pattern.
    A trailing `.keyword` names a subfield of the same value and is reported as
    `keyword`, since that is what it is.
    """
    mapping = (MAPPINGS.get(index) or {}).get("mappings") or {}
    keyword_subfield = field.endswith(".keyword")
    path = field[: -len(".keyword")] if keyword_subfield else field

    node = mapping.get("properties") or {}
    declared: dict | None = None
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            declared = None
            break
        declared = node[part]
        node = declared.get("properties") or {}
    if declared is not None and "type" in declared:
        if keyword_subfield:
            return "keyword" if "keyword" in (declared.get("fields") or {}) else None
        return str(declared["type"])

    for template in mapping.get("dynamic_templates") or []:
        for spec in template.values():
            match = spec.get("path_match")
            if match and _path_matches(match, path):
                mapped = (spec.get("mapping") or {})
                if keyword_subfield:
                    return "keyword" if "keyword" in (mapped.get("fields") or {}) else None
                return str(mapped.get("type")) if mapped.get("type") else None
    return None


def _path_matches(pattern: str, path: str) -> bool:
    """`properties.*` against `properties.capacity`. One level, which is all
    the templates this platform writes use - a fixture that implemented more
    would be imitating a rule nothing here relies on."""
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return path.startswith(prefix + ".") and "." not in path[len(prefix) + 1:]
    return pattern == path


def _coerce(value, declared: str | None, where: str):
    """A value as the mapping says it is, or a refusal.

    **Refusing is the point.** A real cluster rejects "n/a" for an integer
    field with a `mapper_parsing_exception`; a fixture that stored it as a
    string would let a typed reindex look like it had worked and leave the
    disagreement to be found on a real deployment.
    """
    if value is None or declared is None:
        return value
    try:
        if declared in ("integer", "long"):
            if isinstance(value, bool) or float(value) != int(float(value)):
                raise ValueError
            return int(value)
        if declared in ("float", "double"):
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if declared == "boolean":
            if isinstance(value, bool):
                return value
            if str(value).lower() in ("true", "false"):
                return str(value).lower() == "true"
            raise ValueError
        if declared == "date":
            _parse_date(value)
            return value
        if declared == "geo_point":
            _parse_geo(value)
            return value
    except (TypeError, ValueError) as exc:
        raise MappingError(
            f"failed to parse field [{where}] of type [{declared}]: {value!r}"
        ) from exc
    return value


def _parse_date(value) -> datetime:
    when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _parse_geo(value) -> tuple[float, float]:
    """`{"lat": .., "lon": ..}` or `"lat,lon"`, the two forms the platform
    writes. Anything else is a parse failure rather than a guess."""
    if isinstance(value, dict):
        return float(value["lat"]), float(value["lon"])
    lat, _, lon = str(value).partition(",")
    if not lon:
        raise ValueError(f"not a geo_point: {value!r}")
    return float(lat), float(lon)


def _validate(index: str, doc: dict, prefix: str = "") -> dict:
    """Every field of a document, coerced by the mapping. Raises on the first
    contradiction, the way a cluster refuses the whole document rather than
    storing the parts that happened to parse."""
    out: dict = {}
    for key, value in doc.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and _declared_type(index, path) != "geo_point":
            out[key] = _validate(index, value, prefix=f"{path}.")
        else:
            out[key] = _coerce(value, _declared_type(index, path), path)
    return out


def _comparable(value, declared: str | None):
    """A value in the form its mapping compares in.

    This is the whole reason the mapping is remembered. `keyword` compares as
    bytes and `integer` numerically, so `"250" < "40"` on one and `250 > 40` on
    the other - which is the disagreement `object_sets.ORDERED_OPERATORS`
    refuses to choose between, and which a fixture with no mappings could not
    reproduce in either direction.
    """
    if value is None:
        return None
    if declared in ("integer", "long", "float", "double"):
        return float(value)
    if declared == "boolean":
        return bool(value)
    if declared == "date":
        return _parse_date(value)
    return str(value)


def _resolve(source: dict, field: str):
    """Field paths as OpenSearch writes them: dotted into the document, with a
    trailing ``.keyword`` naming a subfield of the same value.

    The fixture treats ``properties.dept.keyword`` and ``properties.dept`` as
    the same thing, because it has no analyzers and so no way to tell text
    from keyword semantics apart. That means it cannot prove the ``.keyword``
    subfield exists in a real mapping - only that the gateway asks about the
    right field. The mapping itself is asserted by the index template in
    instance_store._ensure_index, not here.
    """
    if field.endswith(".keyword"):
        field = field[: -len(".keyword")]
    current: object = source
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def _match(source: dict, clause: dict, index: str = "") -> bool:
    if "term" in clause:
        field, value = next(iter(clause["term"].items()))
        found = _resolve(source, field)
        if found is MISSING:
            return False
        declared = _declared_type(index, field)
        try:
            return _comparable(found, declared) == _comparable(value, declared)
        except (TypeError, ValueError) as exc:
            # A query value the field's type cannot hold. A real cluster
            # answers 400 rather than "no matches", and the difference matters:
            # silently empty is how a wrong query looks like a true answer.
            raise MappingError(
                f"failed to parse query value for [{field}] of type [{declared}]: {value!r}"
            ) from exc
    if "terms" in clause:
        field, values = next(iter(clause["terms"].items()))
        found = _resolve(source, field)
        if found is MISSING:
            return False
        declared = _declared_type(index, field)
        return _comparable(found, declared) in {_comparable(v, declared) for v in values}
    if "geo_bounding_box" in clause:
        # Decision 0006 §3: the map's area selection is a bounding box, not
        # four ordered comparisons - four get the antimeridian wrong, silently,
        # for exactly the customers whose data crosses it. The fixture answers
        # it properly so that a store which reached for comparisons instead
        # would not merely be slower, it would be visibly wrong here.
        field, box = next(iter(clause["geo_bounding_box"].items()))
        found = _resolve(source, field)
        if found is MISSING:
            return False
        if _declared_type(index, field) != "geo_point":
            raise MappingError(f"[geo_bounding_box] query on non-geo_point field [{field}]")
        lat, lon = _parse_geo(found)
        top_left, bottom_right = _parse_geo(box["top_left"]), _parse_geo(box["bottom_right"])
        if not (bottom_right[0] <= lat <= top_left[0]):
            return False
        west, east = top_left[1], bottom_right[1]
        # A box whose west edge is east of its east edge crosses the
        # antimeridian, and then "between" is the union of two ranges rather
        # than one interval.
        return west <= lon <= east if west <= east else (lon >= west or lon <= east)
    if "multi_match" in clause:
        # Substring over every property value plus the primary key. Real
        # OpenSearch tokenises and ranks; the fixture only has to decide
        # whether the gateway asked the right question of the right fields.
        spec = clause["multi_match"]
        needle = str(spec["query"]).lower()
        haystack = []
        for field in spec["fields"]:
            if field.endswith(".*"):
                nested = source.get(field[:-2]) or {}
                haystack.extend(str(v) for v in nested.values())
            elif "." in field:
                # A concrete nested field ("properties.status"), which the
                # object-set gateway sends. Real OpenSearch resolves the path;
                # this used to read it as a top-level key and match nothing.
                current: object = source
                for part in field.split("."):
                    current = (current or {}).get(part) if isinstance(current, dict) else None
                haystack.append("" if current is None else str(current))
            else:
                haystack.append(str(source.get(field, "")))
        if spec.get("type") == "phrase_prefix":
            # Narrowed on purpose: real OpenSearch prefixes the *last term*
            # after tokenising, so "clos" matches "closed" and also matches
            # "site closed". Whole-value prefix is the part both stores can
            # agree on, and the part object_sets.matches defines.
            return any(value.lower().startswith(needle) for value in haystack)
        return any(needle in value.lower() for value in haystack)
    if "match_all" in clause:
        return True
    if "range" in clause:
        field, bounds = next(iter(clause["range"].items()))
        found = _resolve(source, field)
        if found is MISSING:
            return False
        # **Compared by the mapping, not as text.** This is the line the whole
        # exercise is about: `capacity >= 40` is true of 250 on an integer
        # field and false on a keyword one, and until the mapping was
        # remembered this fixture could only ever give the second answer -
        # so a typed range that worked on Postgres and not on OpenSearch
        # would have passed here.
        declared = _declared_type(index, field)
        try:
            current = _comparable(found, declared)
            edges = {op: _comparable(bounds[op], declared) for op in bounds if op in
                     ("lt", "lte", "gt", "gte")}
        except (TypeError, ValueError) as exc:
            raise MappingError(
                f"failed to parse range bound for [{field}] of type [{declared}]"
            ) from exc
        if "lt" in edges and not current < edges["lt"]:
            return False
        if "lte" in edges and not current <= edges["lte"]:
            return False
        if "gt" in edges and not current > edges["gt"]:
            return False
        if "gte" in edges and not current >= edges["gte"]:
            return False
        return True
    raise ValueError(f"fixture does not implement clause {clause!r}")


def _filtered(index: str, query: dict) -> list[tuple[str, dict]]:
    docs = list(INDICES.get(index, {}).items())
    if not query or "match_all" in query:
        return docs
    if "bool" in query:
        bool_query = query["bool"]
        clauses = list(bool_query.get("filter", [])) + list(bool_query.get("must", []))
        should = list(bool_query.get("should", []))
        # must_not is honoured for the same reason minimum_should_match is: the
        # object-set gateway sends it for `neq`, and a fixture that ignored it
        # would report every document as matching and call that a pass.
        must_not = list(bool_query.get("must_not", []))
        # minimum_should_match is honoured rather than assumed: the gateway's
        # link traversal sends two should-clauses expecting *either* to
        # qualify, and a fixture that quietly required both would pass the
        # wrong query.
        minimum = int(bool_query.get("minimum_should_match", 0))
        if should and minimum:
            def enough(source: dict) -> bool:
                return sum(1 for c in should if _match(source, c, index)) >= minimum
        elif should:
            def enough(source: dict) -> bool:
                return True
        else:
            def enough(source: dict) -> bool:
                return True
    else:
        clauses = [query]
        must_not = []

        def enough(source: dict) -> bool:
            return True
    def allowed(source: dict) -> bool:
        return not any(_match(source, c, index) for c in must_not)

    if not clauses:
        return [(i, s) for i, s in docs if enough(s) and allowed(s)]
    return [
        (i, s)
        for i, s in docs
        if all(_match(s, c, index) for c in clauses) and enough(s) and allowed(s)
    ]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _send(self, code: int, payload: dict | None = None) -> None:
        body = json.dumps(payload if payload is not None else {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Elastic-Product", "Elasticsearch")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> str:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length).decode() if length else ""

    # ---- routing ------------------------------------------------------------
    def do_HEAD(self) -> None:  # noqa: N802
        index = urlparse(self.path).path.strip("/")
        self.send_response(200 if index in INDICES else 404)
        self.send_header("Content-Length", "0")
        self.send_header("X-Elastic-Product", "Elasticsearch")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, {
                "name": "fixture", "cluster_name": "fixture",
                "version": {"number": "2.11.0", "distribution": "opensearch"},
                "tagline": "The OpenSearch Project",
            })
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[1] == "_doc":
            index, doc_id = parts[0], parts[2]
            source = INDICES.get(index, {}).get(doc_id)
            if source is None:
                return self._send(404, {"_index": index, "_id": doc_id, "found": False})
            return self._send(200, {"_index": index, "_id": doc_id, "found": True,
                                    "_source": source})
        self._send(404, {"error": f"fixture has no GET {path}"})

    def do_PUT(self) -> None:  # noqa: N802
        index = urlparse(self.path).path.strip("/")
        raw = self._body()
        INDICES.setdefault(index, {})
        # Remembered rather than discarded: everything below compares by it.
        MAPPINGS[index] = json.loads(raw or "{}")
        self._send(200, {"acknowledged": True, "index": index})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        raw = self._body()
        if path == "/__reset":
            INDICES.clear()
            MAPPINGS.clear()
            return self._send(200, {"reset": True})
        if path == "/_bulk":
            return self._bulk(raw)
        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[1] == "_search":
            return self._search(parts[0], json.loads(raw or "{}"))
        if len(parts) == 2 and parts[1] == "_delete_by_query":
            return self._delete_by_query(parts[0], json.loads(raw or "{}"))
        if len(parts) == 3 and parts[1] == "_update":
            return self._update(parts[0], parts[2], json.loads(raw or "{}"))
        self._send(404, {"error": f"fixture has no POST {path}"})

    # ---- operations ---------------------------------------------------------
    def _bulk(self, raw: str) -> None:
        lines = [json.loads(line) for line in raw.splitlines() if line.strip()]
        items = []
        for i in range(0, len(lines), 2):
            action, payload = lines[i], lines[i + 1]
            if "update" not in action:
                return self._send(400, {"error": "fixture implements bulk update only"})
            index = action["update"]["_index"]
            doc_id = action["update"]["_id"]
            bucket = INDICES.setdefault(index, {})
            existing = bucket.get(doc_id)
            if existing is None and not payload.get("doc_as_upsert"):
                items.append({"update": {"_id": doc_id, "status": 404,
                                         "error": {"type": "document_missing_exception"}}})
                continue
            try:
                doc = _validate(index, payload["doc"])
            except MappingError as exc:
                # Per-item, not per-request: a real bulk reports each document
                # separately and the gateway reads `errors` plus the items, so a
                # fixture that failed the whole call would exercise a path the
                # gateway does not have.
                items.append({"update": {"_id": doc_id, "status": 400,
                                         "error": {"type": "mapper_parsing_exception",
                                                   "reason": str(exc)}}})
                continue
            bucket[doc_id] = {**(existing or {}), **doc}
            items.append({"update": {"_id": doc_id, "status": 200,
                                     "result": "updated" if existing else "created"}})
        self._send(200, {"errors": any("error" in i["update"] for i in items), "items": items})

    def _search(self, index: str, body: dict) -> None:
        try:
            matched = _filtered(index, body.get("query", {}))
        except MappingError as exc:
            # What a real cluster answers a query its mapping cannot honour.
            # Returning no matches instead would be the worst option available:
            # a wrong query that looks like a true answer.
            return self._send(400, {"error": {"type": "search_phase_execution_exception",
                                              "reason": str(exc)}})
        for sort in reversed(body.get("sort", [])):
            field, direction = next(iter(sort.items()))
            matched.sort(key=lambda pair: str(pair[1].get(field, "")),
                         reverse=direction == "desc")
        start = int(body.get("from", 0))
        size = int(body.get("size", 10))
        window = matched[start:start + size]
        response: dict = {
            "hits": {
                "total": {"value": len(matched), "relation": "eq"},
                "hits": [{"_index": index, "_id": i, "_source": s} for i, s in window],
            }
        }
        # Cardinality and terms - the aggregations this platform issues
        # (object_sets.AGGREGATIONS, and the terms behind a grouped count and a
        # cross-tab). Cardinality is implemented exactly, not approximately:
        # OpenSearch's is approximate above ~40k distinct values, and a fixture
        # that copied that would be imitating an error budget it has no way to
        # reproduce. Small sets agree either way, which is what a test asserts
        # against.
        aggs = body.get("aggs") or {}
        if aggs:
            try:
                response["aggregations"] = self._aggregate(aggs, matched)
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
        self._send(200, response)

    def _aggregate(self, aggs: dict, matched: list[tuple[str, dict]]) -> dict:
        """One level of aggregations over the matched documents.

        Recursive, because a cross-tab is a terms aggregation *inside* a terms
        aggregation: each outer bucket re-aggregates its own documents, which
        is what makes the inner counts cells rather than column totals.
        """
        computed = {}
        for name, spec in aggs.items():
            if "date_histogram" in spec:
                computed[name] = self._date_histogram(spec["date_histogram"], matched)
                continue
            kind = "cardinality" if "cardinality" in spec else (
                "terms" if "terms" in spec else None
            )
            if kind is None:
                raise ValueError(f"fixture has no {list(spec)[0]} aggregation")
            field = spec[kind]["field"]
            # `properties.x.keyword` addresses the same stored value as
            # `properties.x`; this fixture has no analysers, so the subfield is
            # the field. Its own docstring already records that this is the
            # thing a fixture cannot check.
            path = field[: -len(".keyword")] if field.endswith(".keyword") else field
            parts = path.split(".")
            grouped: dict[str, list[tuple[str, dict]]] = {}
            for pair in matched:
                cursor = pair[1]
                for part in parts:
                    cursor = cursor.get(part) if isinstance(cursor, dict) else None
                if cursor is not None:
                    grouped.setdefault(str(cursor), []).append(pair)
            if kind == "cardinality":
                computed[name] = {"value": len(grouped)}
                continue
            # `include` narrows to named terms before ordering and sizing, the
            # way the real one does - a cross-tab pins both axes with it so the
            # columns are the same on every row.
            include = spec["terms"].get("include")
            if include is not None:
                allowed = set(include)
                grouped = {k: v for k, v in grouped.items() if k in allowed}
            # count desc, then key asc - the order the real terms aggregation
            # is asked for explicitly, so the fixture is not the reason a test
            # passes.
            ordered = sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            size = int(spec["terms"].get("size", 10))
            # Real OpenSearch rejects this rather than returning nothing, and
            # the difference matters: a caller that reaches a terms aggregation
            # with an empty axis has a bug, and a fixture that shrugged would
            # let the guard against it be deleted without a test noticing. That
            # is not hypothetical - it survived a mutation until this existed.
            if size < 1:
                raise ValueError("[size] must be greater than 0")
            computed[name] = {
                "buckets": [
                    {"key": key, "doc_count": len(docs),
                     **(self._aggregate(spec["aggs"], docs) if spec.get("aggs") else {})}
                    for key, docs in ordered[:size]
                ]
            }
        return computed

    def _date_histogram(self, spec: dict, matched: list[tuple[str, dict]]) -> dict:
        """Calendar buckets over a date field, keyed in epoch milliseconds.

        **Only `calendar_interval`, and only UTC** - which is not laziness, it
        is the fixture refusing to answer a question the caller should not be
        asking. `fixed_interval` months drift past every 31-day month and
        Postgres's `date_trunc` does not, so a caller that reached for one has
        a cross-store bug this fixture would otherwise hide behind plausible
        numbers. Same for a time zone: the caller pins UTC deliberately.

        `min_doc_count` defaults to 1 here rather than to the real default of
        0, because the platform always asks for 1 and gap-filling lives in
        `object_sets.fill_time_buckets` - a fixture that filled would be doing
        the thing under test.
        """
        if "calendar_interval" not in spec:
            raise ValueError("fixture supports calendar_interval only, not fixed_interval")
        interval = spec["calendar_interval"]
        if spec.get("time_zone", "UTC") != "UTC":
            raise ValueError("fixture buckets in UTC only")
        if int(spec.get("min_doc_count", 1)) != 1:
            raise ValueError("fixture returns populated buckets only (min_doc_count 1)")

        counts: dict[datetime, int] = {}
        for _, source in matched:
            raw = source.get(spec["field"])
            if raw is None:
                continue
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            when = when.astimezone(timezone.utc)
            if interval == "day":
                start = when.replace(hour=0, minute=0, second=0, microsecond=0)
            elif interval == "week":
                start = (when - timedelta(days=when.weekday())).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            elif interval == "month":
                start = when.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                raise ValueError(f"fixture has no {interval!r} calendar interval")
            counts[start] = counts.get(start, 0) + 1
        return {
            "buckets": [
                {"key": int(start.timestamp() * 1000),
                 "key_as_string": start.isoformat(),
                 "doc_count": n}
                for start, n in sorted(counts.items())
            ]
        }

    def _delete_by_query(self, index: str, body: dict) -> None:
        try:
            matched = _filtered(index, body.get("query", {}))
        except MappingError as exc:
            return self._send(400, {"error": {"type": "mapper_parsing_exception",
                                              "reason": str(exc)}})
        for doc_id, _ in matched:
            INDICES[index].pop(doc_id, None)
        self._send(200, {"deleted": len(matched)})

    def _update(self, index: str, doc_id: str, body: dict) -> None:
        bucket = INDICES.get(index, {})
        if doc_id not in bucket:
            return self._send(404, {"_index": index, "_id": doc_id, "found": False})
        try:
            doc = _validate(index, body["doc"])
        except MappingError as exc:
            return self._send(400, {"error": {"type": "mapper_parsing_exception",
                                              "reason": str(exc)}})
        bucket[doc_id] = {**bucket[doc_id], **doc}
        self._send(200, {"_index": index, "_id": doc_id, "result": "updated"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9209
    # Threading, not the plain HTTPServer: the opensearchpy client pools
    # keep-alive connections, and a single-threaded server serialises behind
    # whichever one it is currently holding open.
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
