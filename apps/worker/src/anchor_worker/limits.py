"""What a transform may produce, said once (§298).

**Found by a differential test on its first run.** `python_sandbox.py` and
`transform_runner.py` both capped a transform's output at five million rows and
both had their own constant and their own sentence:

    the transform produced 3 rows - above this build's 2 row limit
    the transform produced 3 rows, over the 2 limit

One rule, two wordings, and which one a person saw depended on whether the
platform was running with ECS configured — which is not something the author of
a transform knows or should have to. §292 found the same shape one floor down
and fixed it by moving the rules into `user_api.py`; this is the rest of it.

**Its own module rather than `user_api.py`**, because that file is copied into
the directory customer code runs in and is imported *by* their transform. A cap
the platform enforces is not part of the API a transform is written against, and
putting it there would offer it to be read, compared against, and eventually
worked around. This is part of the image both runners ship in.

Stdlib only, deliberately: `transform_runner.py` runs in a container with an
empty task role and no egress, and a test asserts it imports neither boto3 nor
psycopg. A sibling constant is safe; anything that reaches for a client is not.
"""
from __future__ import annotations

#: Matches the SQL transform's day-one cap. A transform that produces more than
#: this has almost always lost a join condition, and finding out at write time
#: is kinder than finding out when the dataset is queried.
MAX_OUTPUT_ROWS = 5_000_000


def too_many_rows(count: int, limit: int | None = None) -> str:
    """The refusal, with both numbers in it.

    **Both**, because "too many rows" without the size leaves the author
    guessing at which join lost its condition, and without the limit leaves them
    guessing at how much they have to lose.

    `limit` is a parameter so a caller that has lowered the cap - a test, or a
    future per-workspace tier - says which number it is refusing against rather
    than printing one it is not using.
    """
    return (
        f"the transform produced {count:,} rows, over this build's "
        f"{MAX_OUTPUT_ROWS if limit is None else limit:,} row limit"
    )
