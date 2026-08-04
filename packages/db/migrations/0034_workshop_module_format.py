"""Convert every Canvas app to the Workshop module format (decision 0002).

The one-shot conversion decision 0002 designed, and the first `.py` migration
in this directory. It is Python because the thing being rewritten is a jsonb
document whose *meaning* the application defines: which props name a parameter,
which widget declares one. Re-expressing that in PL/pgSQL would be a second
implementation of the format, in the language with no tests, diverging from the
one `apps/api/tests/test_workshop_format.py` exercises. So this imports the
converter rather than restating it.

**What changes.** `canvas_apps.definition` - the live document - becomes a
`format: 2` document. Nothing else is rewritten; see the next paragraph, which
this sentence used to contradict.

**The original is kept, and precisely this way.** Historical `canvas_app_versions`
rows are left untouched - they are the record of what the app was, and a
migration that rewrote them would make the history lie about the format it was
written in. Only `canvas_apps.definition`, the live document, is rewritten, and
the conversion appends a *new* version row carrying the converted document, so
the change appears in the history rather than being an edit nobody can see.
Same rule as everywhere else here: a record of what happened must not change
when live state does.

**Idempotent.** `convert()` returns an already-v2 document unchanged, and this
skips any app whose definition is already v2, so a re-run writes nothing.

**Empty apps are skipped**, not converted to an empty module: an app nobody has
ever saved has no layout to preserve, and giving it one would put a version row
in the history of an app that has never had a version.
"""
from __future__ import annotations

import json
import os
import sys

# The converter lives with the API because that is what owns the format. This
# migration ships in the same image (packages/db and apps/api are both in the
# migration container - see docs/deploying.md), so the import is a path away.
_REPO_ROOT = os.path.dirname(  # /repo
    os.path.dirname(  # /repo/packages
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /repo/packages/db
    )
)
_API_SRC = os.path.join(_REPO_ROOT, "apps", "api")
if _API_SRC not in sys.path:
    sys.path.insert(0, _API_SRC)

from src.services import workshop_format  # noqa: E402


def apply(cur) -> None:
    cur.execute(
        """
        SELECT id, definition, current_version
          FROM canvas_apps
         ORDER BY created_at
        """
    )
    rows = cur.fetchall()

    converted = 0
    for app_id, definition, current_version in rows:
        document = json.loads(definition) if isinstance(definition, str) else definition
        if not document:
            continue  # never saved; nothing to preserve
        if not workshop_format.is_v1(document):
            continue  # already converted

        module = workshop_format.convert(document)
        payload = json.dumps(module)
        next_version = (current_version or 0) + 1

        # The new document, and a version row recording that the conversion is
        # what produced it. created_by is null: no person did this.
        cur.execute(
            """
            INSERT INTO canvas_app_versions (canvas_app_id, version_number, definition)
            VALUES (%s, %s, %s::jsonb)
            """,
            (app_id, next_version, payload),
        )
        cur.execute(
            """
            UPDATE canvas_apps
               SET definition = %s::jsonb, current_version = %s, updated_at = now()
             WHERE id = %s
            """,
            (payload, next_version, app_id),
        )
        converted += 1

    print(f"  converted {converted} of {len(rows)} canvas app(s) to format 2")
