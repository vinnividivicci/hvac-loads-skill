"""Resolve design conditions and internal gains from building.json into one dict used by both engines.

Nothing here is defaulted silently: a missing design temperature or weather file is an error.
Defaults that ARE applied (setpoints, humidity, internal gains) are listed in `defaults_applied`
so the report can show them.
"""

from __future__ import annotations

from pathlib import Path

from .model import Building, ModelError, design_value_c
from .psychro import grains, pressure_at, w_from_rh, w_from_wb
from .units import dc_to_df, f_to_c
from .weather import daily_range_class

OCC_SENSIBLE_BTUH = 230.0  # Manual J per-occupant values, as used by OpenStudio-HPXML
OCC_LATENT_BTUH = 200.0


def resolve(b: Building, geo: dict) -> dict:
    d = b.raw.get("design") or {}
    errs, applied = [], []
    out: dict = {"label": d.get("label", ""), "sources": {}}

    def need(key, unit="F"):
        if d.get(key) is None:
            errs.append(f"design.{key} is required (with value, unit and src)")
            return None
        spec = d[key]
        if isinstance(spec, dict) and spec.get("src"):
            out["sources"][key] = spec["src"]
        else:
            errs.append(f"design.{key}: add a 'src' saying where the value comes from")
        return design_value_c(spec, unit)

    out["heating_c"] = need("heating_outdoor")
    out["cooling_c"] = need("cooling_outdoor")
    wb = d.get("cooling_wetbulb")
    out["cooling_wb_c"] = design_value_c(wb) if wb is not None else None
    if wb is None:
        errs.append("design.cooling_wetbulb (mean coincident wet bulb) is required for latent loads")
    elif isinstance(wb, dict) and wb.get("src"):
        out["sources"]["cooling_wetbulb"] = wb["src"]

    for key, default_f, label in (("indoor_heating", 70.0, "Manual J 70 F"), ("indoor_cooling", 75.0, "Manual J 75 F")):
        if d.get(key) is None:
            out[f"{key}_c"] = f_to_c(default_f)
            applied.append(f"design.{key} defaulted to {label}")
        else:
            out[f"{key}_c"] = design_value_c(d[key])
    out["indoor_rh"] = float(d.get("indoor_rh", 0.5))
    if "indoor_rh" not in d:
        applied.append("design.indoor_rh defaulted to 50%")

    dr = d.get("daily_range")
    if isinstance(dr, str):
        out["daily_range_class"] = dr
        out["daily_range_c"] = {"low": 7.0, "medium": 11.0, "high": 15.0}[dr]
    elif isinstance(dr, dict):
        rc = float(dr["value"]) if dr.get("unit", "C").upper().startswith("C") else float(dr["value"]) / 1.8
        out["daily_range_c"] = rc
        out["daily_range_class"] = daily_range_class(dc_to_df(rc))
    else:
        errs.append('design.daily_range is required ({"value": 11, "unit": "C"} or "low"/"medium"/"high")')

    w = d.get("weather") or {}
    epw = w.get("epw")
    p = None
    if epw:
        p = Path(epw)
        if not p.is_absolute() and b.path:
            p = (b.path.parent / p).resolve()
    if (p is None or not p.exists()) and w.get("source_url"):
        # portable projects: re-fetch the station files from the recorded URL into the local cache
        from .weather import download
        p = Path(download(w["source_url"])["epw"])
    if p is None:
        errs.append("design.weather.epw (or weather.source_url) is required (run `hvacload.py weather ... --write`)")
    elif not p.exists():
        errs.append(f"design.weather.epw not found: {p}")
    else:
        out["epw"] = str(p)
    at = b.raw.get("airtightness") or {}
    if not any(k in at for k in ("ach50", "cfm50", "leakiness")):
        errs.append("airtightness is required: {\"ach50\": ...} or {\"cfm50\": ...} (blower door) or "
                    "{\"leakiness\": \"tight\"|\"average\"|...}; ask the user (interview batch 2)")
    out["weather"] = w
    out["climate_zone_iecc"] = d.get("climate_zone_iecc")
    out["elevation_m"] = float(d.get("elevation_m", 0.0))
    out["location"] = {"lat": d.get("lat"), "lon": d.get("lon")}
    out["cooling_day"] = d.get("cooling_day", {"month": 7, "day": 21})
    out["heating_wind_ms"] = float(d.get("heating_wind_ms", 6.7))
    out["fenestration_procedure"] = d.get("fenestration_procedure")
    out["method_note"] = d.get("method_note", "")

    if errs:
        raise ModelError(errs)

    # humidity difference (grains) for Manual J latent loads
    p_atm = pressure_at(out["elevation_m"])
    w_out = w_from_wb(out["cooling_c"], out["cooling_wb_c"], p_atm)
    w_in = w_from_rh(out["indoor_cooling_c"], out["indoor_rh"], p_atm)
    out["w_out"], out["w_in"] = w_out, w_in
    out["humidity_difference_gr"] = round(grains(w_out - w_in), 1)

    hv = b.raw.get("hvac") or {}
    if hv.get("distribution", "ducted") == "ducted":
        du = hv.get("ducts") or {}
        loc = du.get("location")
        if not loc:
            applied.append("ducts: no location given, assumed inside conditioned space (no duct losses); ASK where "
                           "they run, attic or crawlspace ducts can add 20-60 %")
        elif loc != "conditioned" and not du.get("leakage_cfm25"):
            applied.append(f"ducts in {loc}: leakage to outside defaulted to 0.04 CFM25 per ft2 of floor area for "
                           "supply and for return")
        if loc and loc != "conditioned" and not any(k in du for k in ("supply_r_ip", "return_r_ip")):
            applied.append(f"ducts in {loc}: insulation defaulted to R-6")
        if loc == "conditioned" and du.get("leakage_cfm25") and any(v for k, v in du["leakage_cfm25"].items()
                                                                     if k in ("supply", "return")):
            applied.append("ducts inside conditioned space but leakage to outside was entered: check it")

    out["internal_gains"] = _gains(b, geo, applied)
    out["defaults_applied"] = applied
    return out


def _gains(b: Building, geo: dict, applied: list[str]) -> dict:
    g = b.raw.get("internal_gains") or {}
    cond = [r for r in b.rooms if r.conditioned]
    beds = [r for r in cond if r.type == "bedroom"]
    n_bed = b.raw.get("bedrooms", len(beds))
    occ_total = g.get("occupants")
    if occ_total is None:
        occ_total = n_bed + 1
        applied.append(f"occupants defaulted to bedrooms + 1 = {occ_total} (Manual J)")
    app_s = g.get("appliance_sensible_btuh")
    if app_s is None:
        app_s = 2400.0
        applied.append("appliance sensible gain defaulted to 2400 Btu/h (Manual J, one refrigerator)")
    app_l = float(g.get("appliance_latent_btuh", 0.0))
    per = {r.id: {"occupants": 0.0, "sensible_btuh": 0.0, "latent_btuh": 0.0} for r in cond}
    explicit = {r.id for r in cond if r.raw.get("occupants") is not None}
    for r in cond:
        if r.id in explicit:
            per[r.id]["occupants"] = float(r.raw["occupants"])
        if r.raw.get("internal_sensible_btuh") is not None:
            per[r.id]["sensible_btuh"] = float(r.raw["internal_sensible_btuh"])
    if not explicit:
        left = float(occ_total)
        for r in beds:
            if left <= 0:
                break
            per[r.id]["occupants"] = 1.0
            left -= 1
        rank = {"living": 0, "great_room": 1, "family": 2}
        living = sorted([r for r in cond if r.type in rank],
                        key=lambda r: (rank[r.type], -geo["zones"][r.id]["floor_area"])) or \
            sorted(cond, key=lambda r: -geo["zones"][r.id]["floor_area"])
        if left > 0:
            per[living[0].id]["occupants"] += left
        applied.append("occupants allocated one per bedroom, remainder to the main living room")
    if not any(r.raw.get("internal_sensible_btuh") is not None for r in cond):
        kitchens = [r for r in cond if r.type == "kitchen"] or \
                   sorted(cond, key=lambda r: -geo["zones"][r.id]["floor_area"])
        per[kitchens[0].id]["sensible_btuh"] = float(app_s)
        per[kitchens[0].id]["latent_btuh"] = app_l
        applied.append(f"appliance gain placed in {kitchens[0].id}")
    occ = sum(v["occupants"] for v in per.values())
    return {"occupants_total": occ, "sensible_btuh_total": sum(v["sensible_btuh"] for v in per.values()),
            "latent_btuh_total": sum(v["latent_btuh"] for v in per.values()), "per_room": per,
            "occupant_sensible_btuh": OCC_SENSIBLE_BTUH, "occupant_latent_btuh": OCC_LATENT_BTUH}
