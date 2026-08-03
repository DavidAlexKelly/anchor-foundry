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

What this is **not**: OpenSearch. There are no analyzers, no mapping
enforcement, no refresh semantics, no sharding. It proves the gateway forms
correct requests and reads responses correctly; it cannot prove the cluster
agrees. That gap is stated in STATUS rather than papered over.

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# index name -> {doc_id: source}
INDICES: dict[str, dict[str, dict]] = {}


MISSING = object()


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


def _match(source: dict, clause: dict) -> bool:
    if "term" in clause:
        field, value = next(iter(clause["term"].items()))
        found = _resolve(source, field)
        return found is not MISSING and str(found) == str(value)
    if "terms" in clause:
        field, values = next(iter(clause["terms"].items()))
        found = _resolve(source, field)
        return found is not MISSING and str(found) in {str(v) for v in values}
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
        current = str(source.get(field, ""))
        if "lt" in bounds and not current < str(bounds["lt"]):
            return False
        if "gte" in bounds and not current >= str(bounds["gte"]):
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
                return sum(1 for c in should if _match(source, c)) >= minimum
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
        return not any(_match(source, c) for c in must_not)

    if not clauses:
        return [(i, s) for i, s in docs if enough(s) and allowed(s)]
    return [
        (i, s)
        for i, s in docs
        if all(_match(s, c) for c in clauses) and enough(s) and allowed(s)
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
        self._body()
        INDICES.setdefault(index, {})
        self._send(200, {"acknowledged": True, "index": index})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        raw = self._body()
        if path == "/__reset":
            INDICES.clear()
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
            bucket[doc_id] = {**(existing or {}), **payload["doc"]}
            items.append({"update": {"_id": doc_id, "status": 200,
                                     "result": "updated" if existing else "created"}})
        self._send(200, {"errors": any("error" in i["update"] for i in items), "items": items})

    def _search(self, index: str, body: dict) -> None:
        matched = _filtered(index, body.get("query", {}))
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
        # Cardinality only - the one aggregation this platform issues
        # (object_sets.AGGREGATIONS). Implemented exactly, not approximately:
        # OpenSearch's cardinality is approximate above ~40k distinct values,
        # and a fixture that copied that would be imitating an error budget it
        # has no way to reproduce. Small sets agree either way, which is what
        # a test asserts against.
        aggs = body.get("aggs") or {}
        if aggs:
            computed = {}
            for name, spec in aggs.items():
                if "cardinality" not in spec:
                    return self._send(400, {"error": f"fixture has no {list(spec)[0]} aggregation"})
                field = spec["cardinality"]["field"]
                # `properties.x.keyword` addresses the same stored value as
                # `properties.x`; this fixture has no analysers, so the
                # subfield is the field. Its own docstring already records that
                # this is the thing a fixture cannot check.
                path = field[: -len(".keyword")] if field.endswith(".keyword") else field
                parts = path.split(".")
                values = set()
                for _, source in matched:
                    cursor = source
                    for part in parts:
                        cursor = cursor.get(part) if isinstance(cursor, dict) else None
                    if cursor is not None:
                        values.add(str(cursor))
                computed[name] = {"value": len(values)}
            response["aggregations"] = computed
        self._send(200, response)

    def _delete_by_query(self, index: str, body: dict) -> None:
        matched = _filtered(index, body.get("query", {}))
        for doc_id, _ in matched:
            INDICES[index].pop(doc_id, None)
        self._send(200, {"deleted": len(matched)})

    def _update(self, index: str, doc_id: str, body: dict) -> None:
        bucket = INDICES.get(index, {})
        if doc_id not in bucket:
            return self._send(404, {"_index": index, "_id": doc_id, "found": False})
        bucket[doc_id] = {**bucket[doc_id], **body["doc"]}
        self._send(200, {"_index": index, "_id": doc_id, "result": "updated"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9209
    # Threading, not the plain HTTPServer: the opensearchpy client pools
    # keep-alive connections, and a single-threaded server serialises behind
    # whichever one it is currently holding open.
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
