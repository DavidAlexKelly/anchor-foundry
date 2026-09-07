"""Pointing a connection string at a different database on the same server.

**One function, because there were ten copies of it and they were all the same
bug** (§263). Every suite that needs a *second* database — one standing in for
a customer's source system, or a scratch database to migrate from empty — built
its DSN with

    ADMIN_DSN.replace("/platform?", f"/{OTHER}?")

which is a string match on two things that are not part of the syntax: that the
platform database is called `platform`, and that the DSN has a query string.
When either is false the replace **silently does nothing** and every statement
meant for the throwaway database runs against the real one.

That is not hypothetical twice over. `STATUS.md` records a session where a DSN
with no `?` sent a scratch fixture's `CREATE TABLE`, `CREATE VIEW` and blanket
`GRANT` into the shared dev database and broke every other suite's fixtures
with an unrelated `DROP ROLE` failure. And §263 hit the other half while giving
the worker suite a database of its own: `platform_worker_test` does not contain
`/platform?`, so four fixtures created their tables in the wrong database and
three tests failed with "table public.items does not exist" — a message that
points at the source system rather than at the DSN that never changed.

**Parsed rather than pattern-matched.** `urlsplit` knows which part is the
path; a string does not.
"""
from __future__ import annotations

import urllib.parse


def for_database(dsn: str, database: str) -> str:
    """`dsn` with its database replaced by `database`, everything else kept.

    Keeps the scheme, credentials, host, port and query — the query especially,
    because `sslmode=disable` is what makes a local DSN work at all and a
    rebuilt string that dropped it would fail at connect time with a TLS error
    nobody would trace back to here.

    Raises rather than returning something plausible when `dsn` has no database
    in it: **the whole reason this function exists is that the old form failed
    by quietly doing nothing**, and a version that returned the input unchanged
    would have reproduced that exactly.
    """
    parts = urllib.parse.urlsplit(dsn)
    if not parts.path.strip("/"):
        raise ValueError(f"{dsn!r} names no database, so there is nothing to replace")
    return urllib.parse.urlunsplit(parts._replace(path=f"/{database}"))
