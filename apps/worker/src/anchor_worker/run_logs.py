"""What a transform printed, kept (§358; `dataset-preview` p.3).

> "On the left panel, a list of jobs appears with their statuses and durations.
>  Upon selection, a detailed Job view appears on the right showing detailed job
>  information, including progress, specification, **build logs**, files and the
>  resulting schema." (p.3)

**What was there before this.** Both runners already captured stdout and stderr
— the local sandbox through `capture_output=True`, the container by running the
transform in its own process — and both threw nearly all of it away: on failure
one line was kept, truncated to 500 characters, as `model_runs.error_message`;
on success the output was parsed for a payload and discarded. So a `print()` in
a transform, which is the first thing anybody reaches for when one misbehaves,
went into the void.

`model_runs.log_s3_key` has existed since migration 0003 and **nothing has ever
written it**; `services/models.py` said it was "written by the worker runtime
for long runs", which was not true of any runtime. So this needs no migration —
only the column's first writer, and its docstring corrected.

**The rules live here and the capture does not**, because the two runners
capture differently and must not: the subprocess runner redirects inside its
template, the container redirects around its `exec`. What they have to agree on
is what the result *looks like*, which is this module — §292's rule ("one
implementation, imported by both") applied to the half that can be shared.
"""
from __future__ import annotations

# 64 KiB. A transform printing inside a loop can produce megabytes, and a log
# nobody can open is not a log — but the interesting output is rarely more than
# a few lines and the limit should not be so tight that a normal run is
# truncated. This is bytes rather than lines because what it protects is the
# object store and the browser, and both count bytes.
LIMIT = 64 * 1024

TRUNCATION_NOTE = "… {dropped} earlier bytes not kept (the log was over {limit} bytes)\n"

STDERR_HEADING = "--- stderr ---"


def combine(stdout: str, stderr: str) -> str:
    """The two streams as one log.

    **Labelled rather than interleaved.** They are captured separately, so the
    order they were actually written in is not recoverable — presenting them as
    one stream would invent an interleaving that never happened. A heading
    costs one line and does not lie.

    Either stream being empty is the common case: a transform that worked
    quietly has neither, and one that failed has a traceback and no stdout.
    """
    out = stdout.strip("\n")
    err = stderr.strip("\n")
    if not err:
        return f"{out}\n" if out else ""
    if not out:
        return f"{STDERR_HEADING}\n{err}\n"
    return f"{out}\n\n{STDERR_HEADING}\n{err}\n"


def capped(text: str, limit: int = LIMIT) -> str:
    """At most `limit` bytes, keeping the **end**.

    The end, because that is where a failure is: a transform that printed a
    hundred thousand lines and then raised has its answer in the last ten, and
    keeping the head would throw away exactly the part somebody opened the log
    for.

    The note says how much went, so a reader who needs the rest knows there is
    a rest rather than wondering why the log starts mid-sentence.
    """
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    note = TRUNCATION_NOTE.format(dropped=len(raw) - limit, limit=limit)
    # Decoded with `ignore`: slicing bytes can land inside a multi-byte
    # character, and half a character is not worth failing a run over.
    return note + raw[-limit:].decode("utf-8", "ignore")
