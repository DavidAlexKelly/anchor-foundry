"""What a transform printed, kept (§358; `dataset-preview` p.3).

The rules only, which is all this module has — the capture belongs to the two
runners and differs between them on purpose.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.run_logs import LIMIT, STDERR_HEADING, capped, combine  # noqa: E402


class TestCombine:
    def test_stdout_alone_is_the_log(self) -> None:
        assert combine("hello\nworld", "") == "hello\nworld\n"

    def test_stderr_alone_is_labelled(self) -> None:
        # Unlabelled, a traceback reads as something the transform printed on
        # purpose — and the difference is the whole question when a run failed.
        assert combine("", "Traceback") == f"{STDERR_HEADING}\nTraceback\n"

    def test_both_are_kept_and_kept_apart(self) -> None:
        out = combine("printed", "raised")
        assert out.index("printed") < out.index(STDERR_HEADING) < out.index("raised")

    def test_a_quiet_run_has_no_log_at_all(self) -> None:
        # **Not an empty string dressed as a log.** A run with nothing to say
        # should store nothing, so that the control offering it can be absent
        # rather than opening on blankness (§214).
        assert combine("", "") == ""
        assert combine("\n\n", "") == ""

    def test_it_does_not_invent_an_interleaving(self) -> None:
        # The streams are captured separately, so the order they were really
        # written in is not recoverable. This asserts the shape that admits
        # that: all of one, then all of the other.
        assert combine("a\nb", "c\nd") == f"a\nb\n\n{STDERR_HEADING}\nc\nd\n"


class TestCapped:
    def test_a_short_log_is_untouched(self) -> None:
        assert capped("small", limit=100) == "small"

    def test_exactly_the_limit_is_untouched(self) -> None:
        # The boundary, because "over" and "at" are one character apart and a
        # note on a log that fits is a lie about what was kept.
        assert capped("x" * 100, limit=100) == "x" * 100

    def test_a_long_log_keeps_its_end(self) -> None:
        # **The end, not the beginning.** A transform that printed for a while
        # and then raised has its answer in the last lines.
        out = capped("a" * 200 + "THE INTERESTING PART", limit=40)
        assert out.endswith("THE INTERESTING PART")
        assert "a" * 200 not in out

    def test_it_says_how_much_went(self) -> None:
        out = capped("x" * 500, limit=100)
        assert "400" in out, out
        assert "100" in out, out

    def test_the_kept_part_is_the_limit(self) -> None:
        # The negative control for the note: a build that prepended the note
        # without trimming would satisfy every assertion above.
        body = capped("x" * 500, limit=100).split("\n", 1)[1]
        assert len(body.encode("utf-8")) == 100

    def test_a_multibyte_character_cut_in_half_does_not_fail_the_run(self) -> None:
        # Slicing bytes can land inside a character. Losing one is fine;
        # raising `UnicodeDecodeError` while writing a log would fail a
        # transform that had already succeeded.
        out = capped("é" * 200, limit=51)
        assert out.count("é") >= 24
