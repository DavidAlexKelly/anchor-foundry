"""Remove the versions a dataset's retention policy lets go (§965;
docs/decisions/0005-dataset-retention.md; db 0170, 0171).

Every version of every dataset was kept whole, for ever. A dataset with a
policy - `retention_versions`, the newest N kept - now loses the bytes of the
older ones each night, and keeps their rows, which stay true about what the
data was. Which versions may go is the database's to say
(`expirable_dataset_versions`), the same answer the dataset's Retention
report shows before anything is removed: never the current version, the
newest N, a version a transactional export will still read, or one whose
file another version or dataset still reads.

Each version is marked expired first, under a lock and asked again, then its
bytes are removed, and the mark undone if that fails. So a reader never
finds a version said to be kept whose file is gone; a sweep that stops
partway leaves bytes behind, which the next sweep does not see again (the
row says expired) - a cost, never a hole.
"""

import re

from dagster import OpExecutionContext, job, op

from ..resources import PlatformDatabase
from ..storage import gateway_from_env

#: The only shape of file this deletes: one version's own directory, under its
#: own dataset. A key that looks like anything else is left where it is, and
#: the version kept, rather than guessed at.
_VERSION_FILE = re.compile(r"^(workspaces/[^/]+/datasets/(?P<dataset>[0-9a-f-]{36})/v[0-9]+/)data\.parquet$")


def version_directory(dataset_id: str, key: str) -> str | None:
    """The directory to remove for a version stored at `key`, or None when
    the key is not one of this dataset's own version files."""
    match = _VERSION_FILE.match(key)
    if match is None or match.group("dataset") != str(dataset_id):
        return None
    return match.group(1)


def expire_one(context: OpExecutionContext, platform_db: PlatformDatabase, storage,
               dataset_id, version_number: int) -> bool:
    """Mark, remove, and undo the mark if the removal failed. True when the
    version's bytes are gone."""
    with platform_db.connect() as conn:
        key = conn.execute("SELECT expire_dataset_version(%s, %s)",
                           (str(dataset_id), version_number)).fetchone()[0]
        conn.commit()
    if key is None:
        return False  # no longer expirable, or went with a version sharing its file
    if key == "":
        return True  # never had a file
    directory = version_directory(str(dataset_id), key)
    try:
        if directory is None:
            raise ValueError(f"not a version file of this dataset: {key}")
        storage.delete_prefix(directory)
    except Exception as exc:  # noqa: BLE001 - one version must not stop the rest
        with platform_db.connect() as conn:
            conn.execute("SELECT unexpire_dataset_version(%s, %s)", (str(dataset_id), key))
            conn.commit()
        context.log.error(f"dataset {dataset_id} v{version_number}: kept, not removed: {exc}")
        return False
    return True


@op
def expire_dataset_versions(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    storage = gateway_from_env()
    with platform_db.connect() as conn:
        datasets = [row[0] for row in conn.execute(
            "SELECT dataset_id FROM datasets_with_retention()").fetchall()]
    expired = 0
    for dataset_id in datasets:
        with platform_db.connect() as conn:
            versions = [row[0] for row in conn.execute(
                "SELECT version_number FROM expirable_dataset_versions(%s)",
                (str(dataset_id),)).fetchall()]
        for number in versions:
            if expire_one(context, platform_db, storage, dataset_id, number):
                expired += 1
    if expired:
        context.log.info(f"expired {expired} dataset version(s)")
    return expired


@job
def dataset_retention():
    expire_dataset_versions()
