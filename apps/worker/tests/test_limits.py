"""What a transform may produce, and the sentence that refuses it (§298).

**A tiny module gets its own file because a differential test cannot see it.**
`test_execution_parity.py` compares the two runners, which is what caught the
cap being declared twice with two different wordings - but a change to the
*shared* rule moves both answers together, so the comparison agrees and sees
nothing. A mutant proved that: rewording `too_many_rows` survived the parity
suite entirely.

That is the known limit of differential testing, and the answer is not to make
the comparison cleverer. It is to test the rule where the rule lives, which is
here. The two files together say: the runners agree with each other, and they
agree with this.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import limits  # noqa: E402


def test_the_refusal_names_the_size_and_the_limit() -> None:
    """**Both numbers, and this is the whole reason the sentence exists.**

    "Too many rows" without the size leaves the author guessing at which join
    lost its condition; without the limit it leaves them guessing at how much
    they have to lose. A message with neither is a message that sends somebody
    to read the source of the platform.
    """
    said = limits.too_many_rows(7_500_000)
    assert "7,500,000" in said, said
    assert "5,000,000" in said, said
    # Thousands separators, because eight undivided digits is a number nobody
    # reads correctly at a glance and this one is being compared against another.
    assert "7500000" not in said


def test_a_lowered_limit_is_the_one_reported() -> None:
    """`limit` is a parameter so a caller refusing against a different number -
    a test, or a future per-workspace tier - says which number it is refusing
    against rather than printing the default it is not using."""
    said = limits.too_many_rows(3, 2)
    assert "3 rows" in said and "2 row limit" in said, said
    assert "5,000,000" not in said


def test_the_sentence_is_about_the_transform_rather_than_the_platform() -> None:
    """The author can act on "your transform produced too many rows" and cannot
    act on "limit exceeded". Pinned because it is the kind of wording that gets
    shortened by somebody tidying up, and the shortening is the loss."""
    said = limits.too_many_rows(9)
    assert said.startswith("the transform produced "), said
    assert "row limit" in said, said


def test_the_cap_is_the_one_the_sql_transform_uses() -> None:
    """Five million, matching the SQL path's day-one cap. Stated as a number
    here rather than derived, because the two are the same by decision and not
    by construction - the SQL cap lives in the API, which this cannot import."""
    assert limits.MAX_OUTPUT_ROWS == 5_000_000
