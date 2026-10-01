"""Effective thermal resistance of layered assemblies (parallel-path method).

Layers are given as `name:R` (series layers) and one optional framed layer `cavity:R_cavity|R_framing@fraction`.
All R in IP (h.ft2.F/Btu) unless --si. Air films are layers too (e.g. inside:0.68, outside:0.17).
"""

from __future__ import annotations

RSI_PER_RIP = 0.1761102


def parse(spec: str) -> list[dict]:
    layers = []
    for item in [s.strip() for s in spec.split(",") if s.strip()]:
        name, _, val = item.partition(":")
        if "|" in val:
            rc, _, rest = val.partition("|")
            rf, _, frac = rest.partition("@")
            layers.append({"name": name, "framed": True, "r_cavity": float(rc), "r_framing": float(rf),
                           "fraction": float(frac)})
        else:
            layers.append({"name": name, "framed": False, "r": float(val)})
    if sum(1 for lay in layers if lay["framed"]) > 1:
        raise ValueError("only one framed layer is supported (parallel path)")
    return layers


def effective(layers: list[dict], si: bool = False) -> dict:
    series = sum(lay["r"] for lay in layers if not lay["framed"])
    framed = next((lay for lay in layers if lay["framed"]), None)
    if framed:
        f = framed["fraction"]
        u = (1 - f) / (series + framed["r_cavity"]) + f / (series + framed["r_framing"])
        r = 1 / u
    else:
        r = series
    r_ip = r / RSI_PER_RIP if si else r
    return {"r_ip": round(r_ip, 2), "rsi": round(r_ip * RSI_PER_RIP, 3), "u_ip": round(1 / r_ip, 4),
            "u_si": round(1 / (r_ip * RSI_PER_RIP), 4),
            "method": "parallel path" + (f" (framing fraction {framed['fraction']:.0%})" if framed else " (series only)"),
            "layers": layers, "note": "overall value, air films included only if listed as layers"}
