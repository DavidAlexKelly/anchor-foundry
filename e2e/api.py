"""The API, as a browser test needs it: enough to build a Workshop module to
point a browser at.

**Why these tests seed through the API rather than through SQL.** A module
whose objects were inserted straight into `object_instances` would be testing a
table. The point of a browser check is that the whole path holds - upload,
object type, source mapping, sync, module definition, resolve, render - so the
seeding uses the same endpoints a person would.

The one exception is `spread_updated_at`, and it is marked as one: `updated_at`
is set *by* the platform, so a test about bucketing it cannot ask the platform
to set it to anything interesting.
"""
from __future__ import annotations

import csv as csv_module
import io
import json
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from typing import Any


class ApiError(RuntimeError):
    pass


class Api:
    """A caller bound to one dev user's token."""

    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token
        # **Every object type this run creates, so the run can take them away
        # again.** The suite had no cleanup at all, and a shared dev workspace
        # accumulated about 1,400 of them across one session - enough that the
        # Ontology Manager's listing, which fetches and renders every type in
        # the workspace, took seven seconds to open a dialog and a test leaning
        # on Playwright's five-second default went red. The suite had aged into
        # failing on its own leftovers.
        #
        # Recorded here rather than in each test because `call` is the one
        # funnel every test's writes go through: a per-test list would be
        # correct for the tests that remembered and silently wrong for the rest.
        self.created_object_types: list[str] = []  # delete paths, not bare ids

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            # The API refuses cookie auth without it; sent here so these calls
            # go through the same middleware a browser's do.
            "X-Anchor-Session": "1",
        }

    def call(self, method: str, path: str, body: Any = None) -> Any:
        request = urllib.request.Request(
            f"{self.base}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={**self._headers(), "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read()
                parsed = json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise ApiError(f"{method} {path} -> {exc.code} {exc.read().decode()[:500]}") from exc
        self._remember(method, path, parsed)
        return parsed

    def _remember(self, method: str, path: str, parsed: Any) -> None:
        """Note an object type that was just created, for `cleanup` to remove.

        Matched on the *path* rather than on the shape of the response, because
        several endpoints return something with an `id` and only this one
        creates a row that outlives the run.
        """
        if method != "POST" or not path.endswith("/object-types"):
            return
        if isinstance(parsed, dict) and isinstance(parsed.get("id"), str):
            # The *delete path*, built from the create path, so this needs no
            # workspace id of its own - the one that created the type is right
            # there and cannot disagree with it.
            self.created_object_types.append(f"{path}/{parsed['id']}")

    def cleanup(self) -> tuple[int, int]:
        """Delete what this run created. Returns (removed, left behind).

        **Best effort, and that is a decision rather than laziness.** The API
        refuses to delete an `active` or `promoted` object type (p.256) and
        refuses one whose cascade would take an active action type with it -
        both are rules the suite itself exercises, so a cleanup that insisted
        would fail on precisely the tests that prove those rules work. What it
        cannot remove it leaves, and says how many.

        It also must never fail a run: this happens after the last assertion,
        so an exception here would turn a green suite red for tidying up.
        """
        removed = 0
        for delete_path in reversed(self.created_object_types):
            try:
                self.call("DELETE", delete_path)
                removed += 1
            except Exception:
                pass
        left = len(self.created_object_types) - removed
        self.created_object_types.clear()
        return removed, left

    def upload_file(
        self, path: str, data: bytes, *, filename: str, content_type: str
    ) -> dict[str, Any]:
        """A single-file multipart POST, for the endpoints that take one.

        Separate from `upload_csv` because that one also sends a `name` field
        and hard-codes `text/csv`: the attachment endpoint takes neither, and
        the content type is the *point* of the call rather than a constant -
        decision 0009 renders by it.
        """
        boundary = "----anchor" + uuid.uuid4().hex
        parts = [
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
            ).encode(),
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(
            f"{self.base}{path}",
            method="POST",
            data=b"".join(parts),
            headers={
                **self._headers(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise ApiError(f"upload {path} -> {exc.code} {exc.read().decode()[:500]}") from exc

    def upload_csv(self, path: str, name: str, csv: bytes) -> dict[str, Any]:
        boundary = "----anchor" + uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'.encode(),
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                'filename="seed.csv"\r\nContent-Type: text/csv\r\n\r\n'
            ).encode(),
            csv,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(
            f"{self.base}{path}",
            method="POST",
            data=b"".join(parts),
            headers={
                **self._headers(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise ApiError(f"upload {path} -> {exc.code} {exc.read().decode()[:500]}") from exc


class Module:
    """A Workshop module built from a CSV, and the URL that opens it.

    Everything is tagged with a random suffix so two tests - or two runs
    against the same dev database - cannot collide. Nothing is cleaned up
    afterwards on purpose: a failed run leaves its module in place, which is
    the difference between debugging a browser test and re-running it blind.
    """

    def __init__(self, api: Api, name: str, *, beside: "Module | None" = None) -> None:
        """`beside` puts this module in another module's project.

        Needed by anything about *two* modules — an embed, most obviously,
        which the server refuses across projects. Without it the default of
        one-project-per-module is right: tests that share a project share its
        object types and each other's leftovers.
        """
        self.api = api
        self.tag = uuid.uuid4().hex[:6]
        workspace = api.call("GET", "/workspaces")[0]
        self.workspace_id = workspace["id"]
        self.workspace_slug = workspace["slug"]
        if beside is not None:
            self.project_id, self.project_slug = beside.project_id, beside.project_slug
        else:
            project = api.call(
                "POST", f"/workspaces/{self.workspace_id}/projects",
                {"name": f"{name} {self.tag}"},
            )
            self.project_id = project["id"]
            self.project_slug = project["slug"]
        self.base = f"/workspaces/{self.workspace_id}/projects/{self.project_id}"
        self.object_type_id: str | None = None
        self.app_id: str | None = None

    def object_type(
        self,
        *,
        columns: list[str],
        rows: list[dict[str, Any]],
        key: str,
        title: str | None = None,
        visibility: dict[str, str] | None = None,
        types: dict[str, str] | None = None,
        formats: dict[str, dict | None] | None = None,
        rules: dict[str, list[dict]] | None = None,
    ) -> str:
        """Upload, declare, map and sync - the whole way an object type gets
        instances."""
        # **Written with the csv module, not by joining on commas.** A
        # geopoint's value *is* "lat,lon", so the naive join produced a row with
        # more fields than the header and the upload came back "primary key
        # column 'id' is not in the dataset" - a message about the key, from a
        # fault in a different column entirely.
        buffer = io.StringIO()
        writer = csv_module.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([str(row[c]) for c in columns])
        csv = buffer.getvalue().encode()
        dataset = self.api.upload_csv(
            f"{self.base}/datasets/upload", f"seed_{self.tag}", csv
        )
        declared = self.api.call(
            "POST",
            f"/workspaces/{self.workspace_id}/object-types",
            {
                "api_name": f"seed_{self.tag}",
                "display_name": f"Seed {self.tag}",
                "properties": [
                    {
                        "api_name": c,
                        "display_name": c.title(),
                        # String unless told otherwise. `types` exists for the
                        # one case that needs a real base type - a geopoint
                        # renders as a Map in a standard Object View, and a
                        # string of the same characters does not.
                        "data_type": (types or {}).get(c, "string"),
                        **({"required": True} if c == key else {}),
                        **({"visibility": (visibility or {})[c]} if c in (visibility or {}) else {}),
                        # How a reader should see the value (`object-link-types`
                        # p.94-101). Absent means unformatted, which is what
                        # every property of every other fixture is.
                        **({"value_format": (formats or {})[c]} if c in (formats or {}) else {}),
                        # Ordered conditional formatting rules, first match
                        # wins (`object-link-types` p.102-109).
                        **({"conditional_format": (rules or {})[c]}
                           if c in (rules or {}) else {}),
                    }
                    for c in columns
                ],
                **({"title_property": title} if title else {}),
            },
        )
        self.object_type_id = declared["id"]
        source = self.api.call(
            "POST",
            f"{self.base}/object-type-sources",
            {
                "object_type_id": self.object_type_id,
                "dataset_id": dataset["id"],
                "primary_key_column": key,
                "column_mappings": {c: c for c in columns},
            },
        )
        synced = self.api.call(
            "POST", f"{self.base}/object-type-sources/{source['id']}/sync", {}
        )
        assert synced["upserted"] == len(rows), synced
        return self.object_type_id

    def spread_updated_at(self, admin_dsn: str, stamps: dict[str, datetime]) -> None:
        """Give each instance its own `updated_at`, keyed by primary key.

        **Reaches past the API deliberately, and only here.** A sync stamps
        every row with one instant, so a time-series test seeded normally would
        be a test of a single spike. The trigger on the table is `BEFORE
        UPDATE`, so it is switched off around the rewrite - without that every
        row lands on `now()` and every bucket size agrees for the wrong reason.
        """
        import psycopg

        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute("ALTER TABLE object_instances DISABLE TRIGGER USER")
            try:
                for key, when in stamps.items():
                    conn.execute(
                        "UPDATE object_instances SET updated_at = %s "
                        " WHERE object_type_id = %s AND primary_key = %s",
                        (when, self.object_type_id, key),
                    )
            finally:
                conn.execute("ALTER TABLE object_instances ENABLE TRIGGER USER")

    def define(self, document: dict[str, Any], *, description: str = "") -> str:
        """Set this module's document, creating the app on the first call.

        **Creates once, saves thereafter**, which is what the name says and did
        not used to do: every call used to POST a new app, so a fixture wanting
        a version *history* got a 409 on its second save rather than a second
        version. Found writing `test_versions_dialog.py`, which is the first
        test that ever needed to save the same module twice.
        """
        if self.app_id is None:
            app = self.api.call("POST", f"{self.base}/canvas-apps", {"name": f"App {self.tag}"})
            self.app_id = app["id"]
            # The id the *application* is addressed by. Distinct from `app_id`,
            # which is the row's id in `canvas_apps` and is still what every
            # canvas-apps endpoint below is keyed on.
            self.resource_id = app["resource_id"]
        self.api.call(
            "PUT", f"{self.base}/canvas-apps/{self.app_id}/definition",
            {"definition": document, "version_description": description},
        )
        return self.app_id

    def definition(self) -> dict[str, Any]:
        """This module's document as the **server** currently holds it.

        For the assertions that are about what a save produced rather than what
        the panel drew. A builder can be made to show anything; the question
        that matters for a document is whether the server took it and what it
        took, and reading the panel back only ever confirms the panel.
        """
        return self.api.call("GET", f"{self.base}/canvas-apps/{self.app_id}")["definition"]

    @property
    def url(self) -> str:
        """Where a module opens, which is the resource id and nothing else.

        The old slug path still resolves and forwards here, so this could have
        stayed as it was - but then every browser test would exercise the
        redirect rather than the application, and the one thing none of them
        would cover is the URL people actually get.
        """
        return f"/r/{self.resource_id}"


def layout(nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A module layout from `{id: {resolvedName, props}}`, in the order given.

    Format 2 (decision 0002) wants every node to name its parent and the root
    to list its children; spelling that out in every test would bury what each
    test is actually about.

    **Nesting**: a spec may name its own `parent` and list its own `nodes`, for
    the layouts that contain other widgets (a Flow or Toolbar section, a Tabs
    widget). Anything without a `parent` is a child of ROOT, and ROOT lists only
    those - the first version of this put *every* node in ROOT's list, so a
    section's children were also drawn as its siblings.
    """
    out: dict[str, Any] = {
        "ROOT": {
            "type": {"resolvedName": "CanvasContainer"},
            "isCanvas": True,
            "props": {},
            "nodes": [nid for nid, spec in nodes.items() if not spec.get("parent")],
            "linkedNodes": {},
        }
    }
    for node_id, spec in nodes.items():
        node: dict[str, Any] = {
            "type": {"resolvedName": spec["resolvedName"]},
            "props": spec.get("props", {}),
            "parent": spec.get("parent", "ROOT"),
            "nodes": list(spec.get("nodes", [])),
        }
        if spec.get("isCanvas"):
            node["isCanvas"] = True
            node["linkedNodes"] = {}
        out[node_id] = node
    return out


def object_set(object_type_id: str, filters: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"object_type_id": object_type_id, "filters": filters or []}
