"""What a file-based sync takes, and what its dataset becomes (decision 0021;
`data-connection` p.160-164; §749, §750).

The pure half of a file sync: p.164's filters, p.160-162's contradictions,
which of a folder's files a run takes, and the dataset's files after it. No
database and no socket, which is what lets the worker run the **same file**:
`apps/worker/src/anchor_worker/file_sync_rules.py` is a byte-for-byte copy, held
so by a test, for `exports.py`'s reason - a scheduled run that chose different
files from a manual one would be a difference nothing else would notice.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

#: p.160's "Transaction type" (decision 0020).
TRANSACTIONS = ("SNAPSHOT", "APPEND", "UPDATE")

#: A regex a person typed, run against every path in a folder. Bounded so a
#: filter cannot be an essay.
MAX_PATTERN = 200


class FileSyncError(ValueError):
    """A file sync that cannot be saved or cannot run, in a sentence."""


def _when(value: str) -> datetime:
    """A date or date-time, in UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _stamp(value: datetime) -> str:
    """The connector's own format for LastModified (`_s3_timestamp`), so the
    two compare as strings."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z")


def parse_filters(raw: Any) -> dict[str, Any]:
    """p.164's filters, checked and normalised. Absent keys are filters not
    set; unknown keys are refused rather than kept, since a stored setting
    nothing reads is a control that cannot work."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise FileSyncError("filters are an object of p.164's filters")
    known = {"exclude_synced", "path_matches", "path_not_matches", "any_path_matches",
             "modified_after", "size_min", "size_max", "at_least", "limit"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise FileSyncError(f"unknown filter {', '.join(unknown)}")
    out: dict[str, Any] = {}
    excluded = raw.get("exclude_synced")
    if excluded not in (None, False):
        if excluded is True:
            excluded = {}
        if not isinstance(excluded, dict) or set(excluded) - {"by_modified", "by_size"}:
            raise FileSyncError(
                "exclude_synced is true, or {by_modified, by_size} for p.164's options")
        out["exclude_synced"] = {"by_modified": bool(excluded.get("by_modified")),
                                 "by_size": bool(excluded.get("by_size"))}
    for key in ("path_matches", "path_not_matches", "any_path_matches"):
        pattern = raw.get(key)
        if pattern in (None, ""):
            continue
        if not isinstance(pattern, str) or len(pattern) > MAX_PATTERN:
            raise FileSyncError(f"{key} is a regular expression of up to {MAX_PATTERN} characters")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise FileSyncError(f"{key} is not a regular expression: {exc}") from exc
        out[key] = pattern
    if raw.get("modified_after") not in (None, ""):
        try:
            out["modified_after"] = _stamp(_when(str(raw["modified_after"])))
        except ValueError as exc:
            raise FileSyncError("modified_after is a date, like 2026-01-31") from exc
    for key, least in (("size_min", 0), ("size_max", 0), ("at_least", 1), ("limit", 1)):
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < least:
            raise FileSyncError(f"{key} is a whole number of at least {least}")
        out[key] = value
    if "size_min" in out and "size_max" in out and out["size_min"] > out["size_max"]:
        raise FileSyncError("size_min is larger than size_max, so no file could pass")
    return out


def check(transaction: str, filters: dict[str, Any]) -> None:
    """Refuse the settings p.160-162 call contradictory where they would make
    a run do something other than its type says (decision 0021 §2)."""
    if transaction not in TRANSACTIONS:
        raise FileSyncError(f"a file sync's transaction type is one of {', '.join(TRANSACTIONS)}")
    excluded = filters.get("exclude_synced")
    if transaction == "APPEND":
        if excluded is None:
            raise FileSyncError(
                "an APPEND file sync needs Exclude files already synced: without it every "
                "run adds every file again, and the dataset holds each row once per run"
            )
        if excluded["by_modified"] or excluded["by_size"]:
            raise FileSyncError(
                "p.161: Exclude files already synced with the modified date or size option "
                "would re-ingest a changed file in an APPEND, duplicating its rows. A file "
                "that changes needs an UPDATE file sync"
            )
    if transaction == "UPDATE" and not (excluded and (excluded["by_modified"]
                                                      or excluded["by_size"])):
        raise FileSyncError(
            "an UPDATE file sync needs Exclude files already synced with the modified date "
            "or size option, or it can never see a file change - and then it is an APPEND"
        )


def select(
    listing: list[dict[str, Any]], filters: dict[str, Any],
    seen: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """The files a run takes: `listing` (as `list_folder` returns it) through
    p.164's filters, oldest first so a limited run drains a backlog in order.
    `seen` is `sync_files`: every file this sync has taken, by path."""
    files = sorted(listing, key=lambda f: (f.get("modified") or "", f["path"]))
    if "path_matches" in filters:
        files = [f for f in files if re.search(filters["path_matches"], f["path"])]
    if "path_not_matches" in filters:
        files = [f for f in files if not re.search(filters["path_not_matches"], f["path"])]
    if "modified_after" in filters:
        files = [f for f in files if (f.get("modified") or "") > filters["modified_after"]]
    if "size_min" in filters:
        files = [f for f in files if f["size"] >= filters["size_min"]]
    if "size_max" in filters:
        files = [f for f in files if f["size"] <= filters["size_max"]]
    if "any_path_matches" in filters and not any(
            re.search(filters["any_path_matches"], f["path"]) for f in files):
        # p.164: "If any file has a relative path matching the regular
        # expression, sync all files in the subfolder that are not otherwise
        # filtered" - and none does.
        return []
    excluded = filters.get("exclude_synced")
    if excluded is not None:
        def changed(f: dict[str, Any]) -> bool:
            before = seen.get(f["path"])
            if before is None:
                return True
            return ((excluded["by_modified"] and before.get("modified") != f.get("modified"))
                    or (excluded["by_size"] and int(before["size"]) != int(f["size"])))
        files = [f for f in files if changed(f)]
    if len(files) < filters.get("at_least", 0):
        return []
    if "limit" in filters:
        files = files[:filters["limit"]]
    return files


def view_after(transaction: str, held: list[str], taken: list[str]) -> list[str]:
    """The dataset's files after a run, in the order they are read: a
    SNAPSHOT is exactly what it took (p.160, p.162), an APPEND or UPDATE is
    what was held with what it took added, a path it took again replacing
    the old (p.161-162)."""
    if transaction == "SNAPSHOT":
        return list(taken)
    return [path for path in held if path not in taken] + list(taken)


def file_key(dataset_prefix: str, path: str, size: int, modified: str | None) -> str:
    """Where one synced file's rows are kept. Named by the file *as it was
    taken*, so a run that fails after writing it leaves the key the dataset's
    files still name untouched."""
    name = hashlib.sha256(f"{path}\n{size}\n{modified or ''}".encode()).hexdigest()[:32]
    return f"{dataset_prefix}files/{name}.parquet"
