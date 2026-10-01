"""Minimal psychrometrics (SI) from the standard ASHRAE Fundamentals formulations."""

from __future__ import annotations

import math


def pressure_at(elevation_m: float) -> float:
    """Standard atmospheric pressure (Pa) at elevation."""
    return 101325.0 * (1 - 2.25577e-5 * elevation_m) ** 5.2559


def p_ws(t_c: float) -> float:
    """Saturation vapour pressure (Pa), Hyland-Wexler."""
    T = t_c + 273.15
    if t_c < 0:
        c = (-5.6745359e3, 6.3925247, -9.677843e-3, 6.2215701e-7, 2.0747825e-9, -9.484024e-13, 4.1635019)
        ln = c[0] / T + c[1] + c[2] * T + c[3] * T ** 2 + c[4] * T ** 3 + c[5] * T ** 4 + c[6] * math.log(T)
    else:
        c = (-5.8002206e3, 1.3914993, -4.8640239e-2, 4.1764768e-5, -1.4452093e-8, 6.5459673)
        ln = c[0] / T + c[1] + c[2] * T + c[3] * T ** 2 + c[4] * T ** 3 + c[5] * math.log(T)
    return math.exp(ln)


def w_from_rh(t_c: float, rh: float, p: float = 101325.0) -> float:
    pw = rh * p_ws(t_c)
    return 0.621945 * pw / (p - pw)


def w_from_wb(tdb: float, twb: float, p: float = 101325.0) -> float:
    ws = 0.621945 * p_ws(twb) / (p - p_ws(twb))
    if twb >= 0:
        return ((2501 - 2.326 * twb) * ws - 1.006 * (tdb - twb)) / (2501 + 1.86 * tdb - 4.186 * twb)
    return ((2830 - 0.24 * twb) * ws - 1.006 * (tdb - twb)) / (2830 + 1.86 * tdb - 2.1 * twb)


def grains(w: float) -> float:
    return w * 7000.0
