"""p.393's *DSP filter* (§685; `workshop` p.393).

> "DSP filter: Apply a digital signal processing filter (Butterworth,
> Chebyshev, or inverse Chebyshev) to reduce noise in a time series." (p.393)

**Designed here, run as SQL.** A filter is designed the classical way: an
analog low-pass prototype (Butterworth; Chebyshev type I with a passband
ripple; inverse Chebyshev - type II - with a stopband attenuation), moved to
the cut-off, and mapped to a digital filter by the bilinear transform with
pre-warping. That is how the textbooks and SciPy's `iirfilter` do it, and the
tests hold these coefficients to SciPy's published values.

The recursion itself is not something a window function can express, but its
**zero-phase** form is: running a filter forwards and then backwards (what
`filtfilt` does, so a smoothed series does not lag its readings) is the same as
one symmetric weighting of the neighbouring readings - the impulse response
convolved with itself reversed. `zero_phase_weights` returns those weights,
trimmed where they no longer matter, and `time_series` applies them as a
weighted sum over neighbouring readings, renormalised at the ends so the first
and last readings are not dragged towards zero.

**By reading, not by clock.** The cut-off is a fraction of the Nyquist
frequency of the readings as they come, one after another. p.393's *Sample*
makes an unevenly spaced series even first, and the editor says so.

Standard library only: an eighth-order filter is sixteen complex numbers, and
nothing here needs an array library.
"""
from __future__ import annotations

import cmath
import math

FAMILIES = ("butterworth", "chebyshev", "inverse_chebyshev")
MAX_ORDER = 8
#: Weights smaller than this, relative to the largest, are dropped: a
#: hundred-thousandth of the centre reading's say is below anything a chart
#: can draw.
TOLERANCE = 1e-5
#: The most readings either side one smoothed reading may draw on. Enough for
#: an eighth-order inverse Chebyshev at a twentieth of Nyquist; a slower
#: filter than that is refused (`TooLong`).
MAX_REACH = 1000


def _prototype(family: str, order: int, ripple: float, attenuation: float):
    """The analog low-pass prototype's zeros, poles and gain, at 1 rad/s."""
    n = order
    steps = range(-n + 1, n, 2)
    if family == "butterworth":
        poles = [-cmath.exp(1j * math.pi * m / (2 * n)) for m in steps]
        return [], poles, 1.0
    if family == "chebyshev":
        eps = math.sqrt(10 ** (0.1 * ripple) - 1)
        mu = math.asinh(1 / eps) / n
        poles = [-cmath.sinh(mu + 1j * math.pi * m / (2 * n)) for m in steps]
        gain = _product(-p for p in poles).real
        if n % 2 == 0:
            gain /= math.sqrt(1 + eps * eps)
        return [], poles, gain
    # inverse Chebyshev (type II)
    de = 1 / math.sqrt(10 ** (0.1 * attenuation) - 1)
    mu = math.asinh(1 / de) / n
    ms = [m for m in steps if m != 0]
    zeros = [-(1j / math.sin(m * math.pi / (2 * n))).conjugate() for m in ms]
    raw = [-cmath.exp(1j * math.pi * m / (2 * n)) for m in steps]
    poles = [1 / complex(math.sinh(mu) * p.real, math.cosh(mu) * p.imag) for p in raw]
    gain = (_product(-p for p in poles) / _product(-z for z in zeros)).real
    return zeros, poles, gain


def _product(values) -> complex:
    out = complex(1, 0)
    for v in values:
        out *= v
    return out


def _poly(roots: list[complex]) -> list[complex]:
    """The monic polynomial with these roots, highest power first."""
    coefficients = [complex(1, 0)]
    for r in roots:
        coefficients = [a - r * b for a, b in zip(coefficients + [0], [0] + coefficients)]
    return coefficients


def design(family: str, order: int, cutoff: float, *,
           ripple: float = 1.0, attenuation: float = 40.0) -> tuple[list[float], list[float]]:
    """A digital low-pass filter's coefficients `(b, a)`, highest power
    first, with `a[0] == 1`. `cutoff` is a fraction of the Nyquist frequency,
    strictly between 0 and 1."""
    zeros, poles, gain = _prototype(family, order, ripple, attenuation)
    # Pre-warped, so the digital filter's edge is where it was asked for.
    warped = 4 * math.tan(math.pi * cutoff / 2)
    zeros = [z * warped for z in zeros]
    poles = [p * warped for p in poles]
    gain *= warped ** (len(poles) - len(zeros))
    # The bilinear transform, at fs = 2.
    digital_zeros = [(4 + z) / (4 - z) for z in zeros] + [-1] * (len(poles) - len(zeros))
    digital_poles = [(4 + p) / (4 - p) for p in poles]
    gain *= (_product(4 - z for z in zeros) / _product(4 - p for p in poles)).real
    b = [(gain * c).real for c in _poly(digital_zeros)]
    a = [c.real for c in _poly(digital_poles)]
    return b, a


def impulse_response(b: list[float], a: list[float], length: int) -> list[float]:
    """The filter's response to one reading of 1, `length` readings long."""
    out: list[float] = []
    for n in range(length):
        acc = b[n] if n < len(b) else 0.0
        for k in range(1, min(n, len(a) - 1) + 1):
            acc -= a[k] * out[n - k]
        out.append(acc)
    return out


class TooLong(ValueError):
    """A filter whose response outlasts `MAX_REACH` readings."""


def zero_phase_weights(b: list[float], a: list[float]) -> list[float]:
    """The weights of the forwards-and-backwards filter, centred: entry `i`
    weighs the reading `i - reach` places away, where `reach` is
    `(len(weights) - 1) // 2`.

    **Refused rather than cut short** when the response lasts longer than
    `MAX_REACH` readings: a very low cut-off with a steep order rings for
    thousands of readings, and the first few hundred of that are not a gentler
    version of the filter but a different, wrong one."""
    h = impulse_response(b, a, 4 * MAX_REACH)
    peak = max(abs(v) for v in h) or 1.0
    last = max((n for n, v in enumerate(h) if abs(v) > TOLERANCE * peak), default=0)
    if last > MAX_REACH:
        raise TooLong(
            f"that filter would weigh readings more than {MAX_REACH} places away; "
            "raise the cut-off or lower the order")
    h = h[: last + 1]
    full = [sum(h[k] * h[k + j] for k in range(len(h) - j)) for j in range(len(h))]
    largest = max(abs(w) for w in full) or 1.0
    reach = max((j for j, w in enumerate(full) if abs(w) > TOLERANCE * largest), default=0)
    one_side = full[: reach + 1]
    return list(reversed(one_side[1:])) + one_side
