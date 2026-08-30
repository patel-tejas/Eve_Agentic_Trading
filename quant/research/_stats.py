"""Distribution and moment primitives shared by the phase-08b validation tools.

The project deliberately carries no SciPy dependency (see ``pyproject.toml``),
so the two normal-distribution functions every test here needs are implemented
directly:

``norm_cdf``
    Exact to double precision via :func:`math.erf`.
``norm_ppf``
    Acklam's rational approximation refined by one Halley step against
    ``norm_cdf``, giving full double precision across the open interval.

Everything is a pure function of a returns sequence. No I/O, no polars, so the
same code serves the research runner, the MCP tools and the tests.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

TRADING_DAYS_PER_YEAR = 252.0

# Acklam's coefficients for the inverse normal CDF.
_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)
_P_LOW = 0.02425


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (quantile function) for ``0 < p < 1``."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"norm_ppf requires 0 < p < 1, got {p}")

    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )
    elif p <= 1.0 - _P_LOW:
        q = p - 0.5
        r = q * q
        x = (
            (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5])
            * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )

    # One Halley refinement: the approximation above is good to ~1.15e-9,
    # this takes it to machine precision.
    err = norm_cdf(x) - p
    density = norm_pdf(x)
    if density > 0.0:
        u = err / density
        x -= u / (1.0 + x * u / 2.0)
    return x


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean; ``0.0`` for an empty sequence."""
    return sum(values) / len(values) if values else 0.0


def stdev(values: Sequence[float], *, ddof: int = 1) -> float:
    """Sample standard deviation; ``0.0`` when there are too few points."""
    n = len(values)
    if n - ddof <= 0:
        return 0.0
    mu = mean(values)
    return math.sqrt(sum((x - mu) ** 2 for x in values) / (n - ddof))


def skewness(values: Sequence[float]) -> float:
    """Population (biased) skewness — the third standardised moment.

    Population rather than sample-corrected because the probabilistic Sharpe
    ratio's derivation is stated in terms of the distribution's own moments.
    """
    n = len(values)
    if n < 3:
        return 0.0
    mu = mean(values)
    m2 = sum((x - mu) ** 2 for x in values) / n
    if m2 <= 0.0:
        return 0.0
    m3 = sum((x - mu) ** 3 for x in values) / n
    return m3 / m2**1.5


def kurtosis(values: Sequence[float]) -> float:
    """Population NON-excess kurtosis — normal distribution gives 3.0.

    Non-excess on purpose: :func:`quant.research.multiple_testing.
    probabilistic_sharpe_ratio` uses the raw fourth moment, and passing an
    excess kurtosis there silently shifts the variance term by 3.
    """
    n = len(values)
    if n < 4:
        return 3.0
    mu = mean(values)
    m2 = sum((x - mu) ** 2 for x in values) / n
    if m2 <= 0.0:
        return 3.0
    m4 = sum((x - mu) ** 4 for x in values) / n
    return m4 / m2**2


def sharpe_ratio(
    returns: Sequence[float],
    *,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
    annualised: bool = True,
) -> float:
    """Sharpe ratio of a per-period returns series (zero risk-free rate).

    ``annualised=False`` returns the per-period ratio, which is the form the
    probabilistic and deflated Sharpe ratios are defined against — mixing the
    two is the easiest way to get a nonsense confidence number.
    """
    sd = stdev(returns)
    if sd <= 0.0:
        return 0.0
    ratio = mean(returns) / sd
    return ratio * math.sqrt(periods_per_year) if annualised else ratio
