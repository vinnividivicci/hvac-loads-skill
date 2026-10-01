"""Combine engine results: room table, method comparison, surface takeoff (the "spreadsheet" view)."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .geometry import Surface
from .model import Building
from .units import W_PER_BTUH, c_to_f, m2_to_ft2, m_to_ft

HEAT_FLAG, COOL_FLAG = 0.20, 0.30  # rule-of-thumb disagreement thresholds between methods

MJ_CAT = {"Above Grade Walls": "walls", "Below Grade Walls": "ground contact", "Ceilings": "ceilings/roofs",
          "Roofs": "ceilings/roofs", "Floors": "floors", "Slabs": "ground contact", "Windows": "windows",
          "Skylights": "windows", "AED Excursion": "windows", "Doors": "doors", "Infiltration": "infiltration",
          "Ventilation": "ventilation", "Ducts": "ducts", "Internal Gains": "internal gains",
          "Blower Heat": "ducts", "Piping": "ducts"}
EP_CAT = {"Exterior Wall": "walls", "Interzone Wall": "walls", "Ground Contact Wall": "ground contact",
          "Other Wall": "walls", "Roof": "ceilings/roofs", "Interzone Ceiling": "ceilings/roofs",
          "Other Roof": "ceilings/roofs", "Exterior Floor": "floors", "Interzone Floor": "floors",
          "Ground Contact Floor": "ground contact", "Other Floor": "floors", "Fenestration Conduction": "windows", "Fenestration Solar": "windows",
          "Opaque Door": "doors", "Infiltration": "infiltration", "Zone Ventilation": "ventilation",
          "People": "internal gains", "Lights": "internal gains", "Equipment": "internal gains"}
# excluded from the like-for-like total: ducts and ventilation are modelled by the primary method only; ground
# contact is method-sensitive by design (Manual J tables at outdoor design temperature vs ISO 13370-style U-values
# against an EN 12831 effective ground temperature) and is reported side by side instead
EXCLUDED_FROM_CROSSCHECK = ("ducts", "ventilation", "ground contact")


GROUND_CATEGORIES = ("slab", "slab_garage", "slab_crawlspace", "wall_basement")


def ground_ids(geo: dict) -> set:
    return {s.id for s in geo["surfaces"] if s.category in GROUND_CATEGORIES}


def above_grade_foundation_ua(geo: dict) -> dict:
    """W/K of the above-grade part of each room's foundation walls. The primary engine books whole foundation
    walls as ground contact; the cross-check models the part above grade as an exterior wall, so this part is
    moved to ground contact on the cross-check side for a like-for-like comparison (steady state on the
    heating design day)."""
    out: dict = defaultdict(float)
    for s in geo["surfaces"]:
        if s.boundary == "foundation" and s.room and s.u_si:
            (x1, y1, ztop), (_, _, zbot), (x2, y2, _), _ = s.vertices
            h_ag = max(0.0, ztop - max(zbot, 0.0))
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            out[s.room] += s.u_si * length * h_ag
    return dict(out)


def mj_by_category(rec: dict, which: str, ground: set | None = None) -> dict:
    """Primary-engine components by comparison category. Ground contact is identified by surface id,
    because the engine books a slab under a conditioned room as 'Floors'."""
    out = defaultdict(float)
    key = {"heating": "heating_w", "cooling": "cooling_sensible_w"}[which]
    for c in rec.get("components", []):
        cat = "ground contact" if ground and c.get("surface") in ground else MJ_CAT.get(c["category"], c["category"])
        out[cat] += c[key]
    return dict(out)


def ep_by_category(rec: dict, which: str) -> dict:
    out = defaultdict(float)
    for row, vals in rec.get("components", {}).get(which, {}).items():
        if row == "Grand Total":
            continue
        sens = vals.get("Sensible - Instant", 0.0) + vals.get("Sensible - Delayed", 0.0)
        out[EP_CAT.get(row, row)] += -sens if which == "heating" else sens  # heating: losses positive
    return dict(out)


def compare(mj: dict, ep: dict | None, cond_rooms: list[str], ground: set | None = None,
            ag_ua: dict | None = None, heating_dt: float = 0.0) -> dict:
    """Room-by-room comparison on a like-for-like basis: envelope + infiltration (+ internal gains for
    cooling). Ducts and mechanical ventilation are excluded because only the primary method models them."""
    if not ep:
        return {"available": False}
    rows, flags = [], []
    tot = defaultdict(float)
    for rid in cond_rooms:
        m = mj["rooms"].get(rid, {})
        e = ep["rooms"].get(rid, {})
        mh = mj_by_category(m, "heating", ground)
        mc = mj_by_category(m, "cooling", ground)
        # room total minus excluded components (not the sum of listed components: with the "peak" fenestration
        # procedure the room total carries a glazing increment that is not itemised)
        mh_like = m.get("heating_w", 0.0) - sum(mh.get(k, 0.0) for k in EXCLUDED_FROM_CROSSCHECK)
        mc_like = m.get("cooling_sensible_w", 0.0) - sum(mc.get(k, 0.0) for k in EXCLUDED_FROM_CROSSCHECK)
        # EnergyPlus room loads include mechanical ventilation (ZoneVentilation); the primary engine books it at
        # system level, so remove it here for a like-for-like comparison
        eph, epc = ep_by_category(e, "heating"), ep_by_category(e, "cooling")
        ag = (ag_ua or {}).get(rid, 0.0) * heating_dt
        eph["ground contact"] = eph.get("ground contact", 0.0) + ag
        eh = e.get("heating_w", 0.0) - sum(eph.get(k, 0.0) for k in EXCLUDED_FROM_CROSSCHECK)
        if e.get("cooling_sensible_w", 0.0) > 0:
            ec = e["cooling_sensible_w"] - sum(epc.get(k, 0.0) for k in EXCLUDED_FROM_CROSSCHECK)
        else:  # room needs no cooling in EnergyPlus (e.g. ground-cooled basement): use its non-ground gains
            ec = max(0.0, sum(v for k, v in epc.items() if k not in EXCLUDED_FROM_CROSSCHECK))
        tot["mj_ground_h"] += mh.get("ground contact", 0.0)
        tot["ep_ground_h"] += eph.get("ground contact", 0.0)
        dh = (eh - mh_like) / mh_like if mh_like > 50 else None
        dc = (ec - mc_like) / mc_like if mc_like > 50 else None
        row = {"room": rid, "mj_heating_like_w": mh_like, "ep_heating_w": eh, "delta_heating": dh,
               "mj_cooling_like_w": mc_like, "ep_cooling_w": ec, "delta_cooling": dc,
               "ep_cooling_peak": e.get("cooling_peak")}
        rows.append(row)
        for k2, v in (("mj_h", mh_like), ("ep_h", eh), ("mj_c", mc_like), ("ep_c", ec)):
            tot[k2] += v
        if dh is not None and abs(dh) > HEAT_FLAG and abs(eh - mh_like) > 150:
            flags.append(f"{rid}: heating differs by {100 * dh:+.0f} % between methods")
        if dc is not None and abs(dc) > COOL_FLAG and abs(ec - mc_like) > 150:
            flags.append(f"{rid}: sensible cooling differs by {100 * dc:+.0f} % between methods")
    cats = {}
    for which in ("heating", "cooling"):
        a, b = defaultdict(float), defaultdict(float)
        for rid in cond_rooms:
            for k2, v in mj_by_category(mj["rooms"].get(rid, {}), which, ground).items():
                a[k2] += v
            for k2, v in ep_by_category(ep["rooms"].get(rid, {}), which).items():
                b[k2] += v
            if which == "heating":  # same reallocation as in the room comparison above
                ag = (ag_ua or {}).get(rid, 0.0) * heating_dt
                b["walls"] -= ag
                b["ground contact"] += ag
        # system-level components the primary engine books on the zone, not the rooms
        zone = mj_by_category(mj.get("total", {}), which, ground) if mj.get("total", {}).get("components") else {}
        for k2 in ("ventilation", "ducts"):
            if zone.get(k2) and not a.get(k2):
                a[k2] = zone[k2]
        cats[which] = {k2: {"mj_w": a.get(k2, 0.0), "ep_w": b.get(k2, 0.0)} for k2 in sorted(set(a) | set(b))}
    th = (tot["ep_h"] - tot["mj_h"]) / tot["mj_h"] if tot["mj_h"] else None
    tc = (tot["ep_c"] - tot["mj_c"]) / tot["mj_c"] if tot["mj_c"] else None
    if th is not None and abs(th) > HEAT_FLAG:
        flags.insert(0, f"WHOLE HOUSE: heating differs by {100 * th:+.0f} % between methods (envelope + infiltration)")
    if tc is not None and abs(tc) > COOL_FLAG:
        flags.insert(0, f"WHOLE HOUSE: sensible cooling differs by {100 * tc:+.0f} % between methods")
    g_mj, g_ep = tot["mj_ground_h"], tot["ep_ground_h"]
    ground_note = None
    if g_mj > 50 or g_ep > 50:
        ground_note = (f"Ground-contact heat loss (slabs, below-grade walls): primary {g_mj:,.0f} W vs cross-check "
                       f"{g_ep:,.0f} W. The methods differ by design (Manual J tables against the outdoor design "
                       "temperature vs ISO 13370-style U-values against an EN 12831 effective ground temperature); "
                       "this component is shown side by side and excluded from the like-for-like total.")
    return {"available": True, "rooms": rows, "totals": dict(tot), "delta_heating": th, "delta_cooling": tc,
            "ground_note": ground_note,
            "categories": cats, "flags": flags,
            "basis": "Like-for-like: above-grade envelope conduction + infiltration (+ internal gains and solar for "
                     "cooling). Ducts and mechanical ventilation are excluded (modelled by the primary method only); "
                     "ground contact is compared separately. "
                     f"Flag thresholds (rule of thumb, not a standard): heating {int(HEAT_FLAG * 100)} %, "
                     f"cooling {int(COOL_FLAG * 100)} %."}


def room_table(b: Building, geo: dict, mj: dict, design: dict) -> list[dict]:
    zones = geo["zones"]
    dt_heat_f = float(b.raw.get("airflow", {}).get("heating_supply_dt_f", 50.0))
    dt_cool_f = float(b.raw.get("airflow", {}).get("cooling_supply_dt_f", 20.0))
    rows = []
    for r in b.rooms:
        if not r.conditioned:
            continue
        m = mj["rooms"].get(r.id, {})
        h, cs, cl = m.get("heating_w", 0.0), m.get("cooling_sensible_w", 0.0), m.get("cooling_latent_w", 0.0)
        fa = zones[r.id]["floor_area"]
        rows.append({
            "room": r.id, "name": r.name, "level": r.level, "floor_area_m2": fa, "floor_area_ft2": m2_to_ft2(fa),
            "heating_w": h, "heating_btuh": h / W_PER_BTUH, "cooling_sensible_w": cs,
            "cooling_sensible_btuh": cs / W_PER_BTUH, "cooling_latent_btuh": cl / W_PER_BTUH,
            "heating_w_per_m2": h / fa if fa else 0.0, "cooling_w_per_m2": cs / fa if fa else 0.0,
            "heating_cfm": (h / W_PER_BTUH) / (1.08 * dt_heat_f) if h else 0.0,
            "cooling_cfm": (cs / W_PER_BTUH) / (1.08 * dt_cool_f) if cs else 0.0,
        })
    return rows


def sanity(b: Building, geo: dict, mj: dict) -> dict:
    cfa = sum(z["floor_area"] for z in geo["zones"].values() if z.get("conditioned"))
    t = mj.get("total", {})
    h, cs, cl = t.get("heating_w", 0.0), t.get("cooling_sensible_w", 0.0), t.get("cooling_latent_w", 0.0)
    tons = (cs + cl) / W_PER_BTUH / 12000 if (cs + cl) else 0.0
    return {"conditioned_area_m2": cfa, "conditioned_area_ft2": m2_to_ft2(cfa),
            "heating_w_per_m2": h / cfa if cfa else 0.0, "heating_btuh_per_ft2": (h / W_PER_BTUH) / m2_to_ft2(cfa) if cfa else 0.0,
            "cooling_w_per_m2": cs / cfa if cfa else 0.0,
            "ft2_per_ton": m2_to_ft2(cfa) / tons if tons else None,
            "heating_to_cooling": h / cs if cs else None,
            "sensible_heat_ratio": cs / (cs + cl) if (cs + cl) else None}


def takeoff_csv(b: Building, geo: dict, design: dict, path: Path) -> None:
    """One row per surface: the auditable quantity takeoff (areas, U, UA, adjacency, orientation)."""
    dt = design["indoor_heating_c"] - design["heating_c"]
    cols = ["surface", "zone", "room", "kind", "category", "boundary", "adjacent_zone", "parent", "area_m2",
            "net_area_m2", "area_ft2", "net_area_ft2", "azimuth_deg", "tilt_deg", "assembly", "u_si", "u_ip",
            "ua_w_per_k", "ua_x_design_dt_w", "exposed_perimeter_m", "depth_below_grade_m", "label"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for s in geo["surfaces"]:
            net = s.net_area if s.kind in ("wall", "roof", "ceiling", "floor") else s.area
            ua = (s.u_si or 0.0) * net if s.boundary in ("outside", "foundation", "zone", "ground") else 0.0
            w.writerow([s.id, s.zone, s.room or "", s.kind, s.category, s.boundary, s.adjacent_zone or "",
                        s.parent or "", f"{s.area:.3f}", f"{net:.3f}", f"{m2_to_ft2(s.area):.2f}",
                        f"{m2_to_ft2(net):.2f}", "" if s.azimuth is None else f"{s.azimuth:.1f}", f"{s.tilt:.1f}",
                        s.assembly or s.product or "", "" if s.u_si is None else f"{s.u_si:.4f}",
                        "" if s.u_si is None else f"{s.u_si / 5.678263:.4f}", f"{ua:.3f}",
                        f"{ua * dt:.1f}" if s.boundary == "outside" else "",
                        f"{s.exposed_perimeter:.2f}" if s.exposed_perimeter else "",
                        f"{s.depth_below_grade:.2f}" if s.depth_below_grade else "", s.label])
