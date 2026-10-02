"""p.393's DSP filter (§685; `workshop` p.393).

> "DSP filter: Apply a digital signal processing filter (Butterworth,
> Chebyshev, or inverse Chebyshev) to reduce noise in a time series." (p.393)

The design is held two ways: to SciPy's published coefficients where they are
well known, and to what each family *is* - Butterworth's half-power point at
the cut-off, Chebyshev's ripple in the passband, the inverse Chebyshev's
attenuation from the cut-off on - so a filter that happened to match a table
but not its definition would still fail.
"""
from __future__ import annotations

import cmath
import math
import os
import sys

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import dsp  # noqa: E402
from src.services import time_series as ts  # noqa: E402


def gain(b: list[float], a: list[float], fraction: float) -> float:
    """|H| at `fraction` of the Nyquist frequency."""
    z = cmath.exp(-1j * math.pi * fraction)
    top = sum(c * z ** k for k, c in enumerate(b))
    bottom = sum(c * z ** k for k, c in enumerate(a))
    return abs(top / bottom)


def close(got: list[float], want: list[float], tol: float = 1e-7) -> bool:
    return len(got) == len(want) and all(abs(g - w) < tol for g, w in zip(got, want))


# ---- the design ---------------------------------------------------------------------
def test_butterworth_matches_scipy() -> None:
    b, a = dsp.design("butterworth", 2, 0.2)
    assert close(b, [0.06745527, 0.13491055, 0.06745527])
    assert close(a, [1.0, -1.1429805, 0.4128016])
    b, a = dsp.design("butterworth", 4, 0.1)
    assert close(b, [0.0004166, 0.0016664, 0.0024996, 0.0016664, 0.0004166])
    assert close(a, [1.0, -3.18063855, 3.86119435, -2.11215536, 0.43826514])


def test_chebyshev_matches_scipy() -> None:
    b, a = dsp.design("chebyshev", 3, 0.3, ripple=1)
    assert close(b, [0.03438497, 0.1031549, 0.1031549, 0.03438497])
    assert close(a, [1.0, -1.58040494, 1.25384498, -0.39836031])


@pytest.mark.parametrize("order", [1, 2, 3, 5, 8])
def test_butterworth_is_at_half_power_at_the_cut_off(order: int) -> None:
    b, a = dsp.design("butterworth", order, 0.3)
    assert gain(b, a, 0) == pytest.approx(1)
    assert gain(b, a, 0.3) == pytest.approx(1 / math.sqrt(2), rel=1e-6)
    # Maximally flat: never above one.
    assert all(gain(b, a, f / 100) <= 1 + 1e-9 for f in range(100))


@pytest.mark.parametrize("order", [2, 3, 4, 7])
def test_chebyshev_ripples_within_the_passband_and_ends_there(order: int) -> None:
    ripple = 2.0
    b, a = dsp.design("chebyshev", order, 0.25, ripple=ripple)
    floor = 10 ** (-ripple / 20)
    assert all(floor - 1e-9 <= gain(b, a, 0.25 * f / 50) <= 1 + 1e-9 for f in range(51))
    assert gain(b, a, 0.25) == pytest.approx(floor, rel=1e-6)
    # An even order starts at the bottom of the ripple, an odd one at the top.
    assert gain(b, a, 0) == pytest.approx(floor if order % 2 == 0 else 1, rel=1e-6)


@pytest.mark.parametrize("order", [2, 3, 4, 6])
def test_inverse_chebyshev_attenuates_from_the_cut_off_on(order: int) -> None:
    attenuation = 50.0
    b, a = dsp.design("inverse_chebyshev", order, 0.2, attenuation=attenuation)
    ceiling = 10 ** (-attenuation / 20)
    assert gain(b, a, 0) == pytest.approx(1)
    assert gain(b, a, 0.2) == pytest.approx(ceiling, rel=1e-5)
    assert all(gain(b, a, 0.2 + 0.8 * f / 60) <= ceiling * (1 + 1e-6) for f in range(1, 60))


def test_a_higher_order_cuts_harder() -> None:
    gentle = dsp.design("butterworth", 2, 0.2)
    steep = dsp.design("butterworth", 6, 0.2)
    assert gain(*steep, 0.5) < gain(*gentle, 0.5) / 20


def test_the_impulse_response_is_the_recursion() -> None:
    b, a = [1.0, 0.5], [1.0, -0.5]
    assert dsp.impulse_response(b, a, 4) == [1.0, 1.0, 0.5, 0.25]


def test_zero_phase_weights_are_symmetric_trimmed_and_keep_the_level() -> None:
    weights = dsp.zero_phase_weights(*dsp.design("butterworth", 2, 0.2))
    reach = (len(weights) - 1) // 2
    assert len(weights) == 2 * reach + 1 and 3 < reach < dsp.MAX_REACH
    assert weights == list(reversed(weights))
    assert weights[reach] == max(weights)
    # Trimmed weights fall a hair short of one; the query rescales by their sum.
    assert sum(weights) == pytest.approx(1, abs=1e-4)
    # Trimmed where they no longer matter, and not before.
    assert abs(weights[0]) > dsp.TOLERANCE * weights[reach] / 10
    # A gentle filter reaches further than a sharp one.
    wide = dsp.zero_phase_weights(*dsp.design("butterworth", 2, 0.05))
    assert len(wide) > len(weights)
    # One that rings past the bound is refused rather than cut short.
    with pytest.raises(dsp.TooLong, match="raise the cut-off or lower the order"):
        dsp.zero_phase_weights(*dsp.design("butterworth", 8, 0.001))


# ---- as a transform -----------------------------------------------------------------
def rows(values: list[float | None], sensor: str = "S1") -> list[tuple]:
    return [(sensor, f"2026-01-01 {i // 60:02d}:{i % 60:02d}:00", v) for i, v in enumerate(values)]


def run(transform: dict, data: list[tuple]) -> list[float]:
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE dataset (sensor VARCHAR, taken TIMESTAMP, reading DOUBLE)")
        con.executemany("INSERT INTO dataset VALUES (?, ?, ?)", data)
        sql = ts.points_sql(key_column="sensor", timestamp_column="taken", value_column="reading",
                            series_id="S1", interval="none", aggregate="avg",
                            transforms=ts.parse_transforms([transform]))
        return [float(r[1]) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


BUTTER = {"kind": "dsp", "family": "butterworth", "order": 2, "cutoff": 0.1}


def test_a_level_series_stays_level_to_its_ends() -> None:
    """Renormalised at the ends, so the first reading is not averaged with
    readings that do not exist."""
    assert run(BUTTER, rows([5.0] * 40)) == pytest.approx([5.0] * 40)


def test_noise_is_reduced_and_the_trend_kept() -> None:
    noisy = [i / 10 + (1 if i % 2 else -1) for i in range(1000)]
    smoothed = run(BUTTER, rows(noisy))
    assert len(smoothed) == 1000
    # Clear of both ends by more than the longest of the three filters reaches.
    middle = range(420, 580)
    # The alternation is gone and the ramp remains, without lag.
    assert max(abs(smoothed[i] - i / 10) for i in middle) < 0.02
    for family, extra in (("chebyshev", {"ripple": 1}), ("inverse_chebyshev", {"attenuation": 40})):
        other = run({**BUTTER, "family": family, **extra}, rows(noisy))
        assert max(abs(other[i] - i / 10) for i in middle) < 0.05, family


def test_gaps_are_skipped_and_series_kept_apart() -> None:
    data = rows([1.0, None, 1.0, 1.0]) + rows([100.0] * 4, "S2")
    assert run(BUTTER, data) == pytest.approx([1.0, 1.0, 1.0])
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE dataset (sensor VARCHAR, taken TIMESTAMP, reading DOUBLE)")
        con.executemany("INSERT INTO dataset VALUES (?, ?, ?)", data)
        sql = ts.points_for_many_sql(
            key_column="sensor", timestamp_column="taken", value_column="reading",
            series_ids=["S1", "S2"], interval="none", aggregate="avg",
            transforms=ts.parse_transforms([BUTTER]))
        got: dict[str, list[float]] = {}
        for series, _, value in con.execute(sql).fetchall():
            got.setdefault(series, []).append(value)
        assert got == {"S1": pytest.approx([1.0] * 3), "S2": pytest.approx([100.0] * 4)}
    finally:
        con.close()


def test_each_family_takes_its_own_setting() -> None:
    assert ts.parse_transforms([BUTTER]) == [BUTTER | {"cutoff": 0.1}]
    cheb = ts.parse_transforms([{**BUTTER, "family": "chebyshev"}])[0]
    assert cheb["ripple"] == 1.0 and "attenuation" not in cheb
    inverse = ts.parse_transforms([{**BUTTER, "family": "inverse_chebyshev", "ripple": 3}])[0]
    assert inverse["attenuation"] == 40.0 and "ripple" not in inverse


@pytest.mark.parametrize("raw, said", [
    ({**BUTTER, "family": "bessel"}, "the filter must be one of"),
    ({**BUTTER, "order": 0}, "the order must be a whole number from 1 to 8"),
    ({**BUTTER, "order": 9}, "from 1 to 8"),
    ({**BUTTER, "order": 2.0}, "whole number"),
    ({**BUTTER, "order": True}, "whole number"),
    ({**BUTTER, "cutoff": 0}, "between 0 and 1"),
    ({**BUTTER, "cutoff": 1}, "between 0 and 1"),
    ({**BUTTER, "cutoff": "0.1"}, "the cut-off must be a number"),
    ({**BUTTER, "cutoff": float("nan")}, "must be a number"),
    ({**BUTTER, "family": "chebyshev", "ripple": 0}, "the ripple must be above 0"),
    ({**BUTTER, "family": "chebyshev", "ripple": 21}, "at most 20 dB"),
    ({**BUTTER, "family": "inverse_chebyshev", "attenuation": 0}, "the attenuation must be above 0"),
    ({**BUTTER, "family": "inverse_chebyshev", "attenuation": 121}, "at most 120 dB"),
    ({**BUTTER, "order": 8, "cutoff": 0.001}, "raise the cut-off or lower the order"),
])
def test_a_filter_that_cannot_be_designed_is_refused(raw: dict, said: str) -> None:
    with pytest.raises(ValueError) as caught:
        ts.parse_transforms([raw])
    assert said in str(caught.value)
