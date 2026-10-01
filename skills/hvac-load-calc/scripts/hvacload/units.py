"""Unit conversions. Internally everything is SI (m, m2, W, W/m2K, degC)."""

from __future__ import annotations

FT = 0.3048
IN = 0.0254
LENGTH = {"m": 1.0, "mm": 0.001, "cm": 0.01, "ft": FT, "in": IN}

W_PER_BTUH = 0.29307107
RSI_PER_RIP = 0.1761102  # m2K/W per h.ft2.F/Btu
M2_PER_FT2 = FT * FT
M3S_PER_CFM = 0.00047194745


def f_to_c(f: float) -> float:
    return (f - 32.0) / 1.8


def c_to_f(c: float) -> float:
    return c * 1.8 + 32.0


def dc_to_df(dc: float) -> float:
    return dc * 1.8


def w_to_btuh(w: float) -> float:
    return w / W_PER_BTUH


def btuh_to_w(b: float) -> float:
    return b * W_PER_BTUH


def m2_to_ft2(a: float) -> float:
    return a / M2_PER_FT2


def m_to_ft(x: float) -> float:
    return x / FT


def u_si_to_r_ip(u: float) -> float:
    return 1.0 / (u / 5.678263)


def r_ip_to_u_si(r: float) -> float:
    return 5.678263 / r


def temp_c(value, unit: str) -> float:
    unit = (unit or "C").upper()
    return f_to_c(value) if unit.startswith("F") else float(value)


def thermal_u_si(spec: dict) -> float:
    """Overall U (W/m2K, air films included) from any of: u_si, u_ip, rsi, r_ip."""
    if "u_si" in spec:
        return float(spec["u_si"])
    if "u_ip" in spec:
        return float(spec["u_ip"]) * 5.678263
    if "rsi" in spec:
        return 1.0 / float(spec["rsi"])
    if "r_ip" in spec:
        return 1.0 / (float(spec["r_ip"]) * RSI_PER_RIP)
    raise ValueError(f"no thermal value (u_si/u_ip/rsi/r_ip) in {spec}")
