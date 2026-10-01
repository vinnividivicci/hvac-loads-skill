"""Takeoff QA gates: run before any load calculation and show the results to the user.

Checks are split into errors (must fix before running loads) and warnings (review with the user).
"""

from __future__ import annotations

import math

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .geometry import summarize
from .model import Building, LENGTH
from .pdfkit import parse_length

AREA_TOL = 0.02  # 2 % between stated and modelled areas
CHAIN_TOL_FT = 1.0 / 12  # 1 inch


def _len_units(v, units: str) -> float:
    """A number (already in plan units) or a string like 12'-6" / 3.6m, returned in plan units."""
    if isinstance(v, (int, float)):
        return float(v)
    return parse_length(str(v), "m") / LENGTH[units]


def check(b: Building, geo: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = list(geo.get("warnings", []))
    info: dict = {}
    k = LENGTH[b.units]
    a2 = k * k  # plan units^2 -> m2
    src = b.raw.get("source", {})

    if src.get("kind") in ("raster", "mixed"):
        warnings.append("RASTER INPUT: geometry was read visually from images; accuracy is lower than for vector "
                        "PDFs. Confirm every room size and window with the user.")

    # footprint gaps (unassigned floor area inside the building outline)
    for lv in b.levels:
        polys = [Polygon(r.polygon) for r in b.rooms if r.level == lv.id]
        if not polys:
            continue
        u = unary_union(polys)
        holes = []
        for g in getattr(u, "geoms", [u]):
            for ring in g.interiors:
                hole = Polygon(ring)
                if hole.area > 0.05:
                    c = hole.centroid
                    holes.append(f"{hole.area / a2:.1f} {b.units}2 near ({c.x / k:.1f}, {c.y / k:.1f})")
        if holes:
            warnings.append(f"level {lv.id}: unassigned area inside the footprint (missing room, stair or chase?): "
                            + "; ".join(holes))
        n_parts = len(getattr(u, "geoms", [u]))
        if n_parts > 1:
            warnings.append(f"level {lv.id}: rooms form {n_parts} disconnected groups; check for gaps between rooms")

    # stated vs modelled areas
    zones = geo["zones"]
    cond_area = sum(z["floor_area"] for z in zones.values() if z.get("conditioned")) / a2
    garage_area = sum(z["floor_area"] for zid, z in zones.items() if z.get("type") == "garage") / a2
    glazing = sum(s.area for s in geo["surfaces"] if s.category in ("window", "glass_door", "skylight")
                  and zones.get(s.zone, {}).get("conditioned")) / a2
    info["modelled"] = {"conditioned_area": round(cond_area, 1), "garage_area": round(garage_area, 1),
                        "glazing_area": round(glazing, 1), "units": f"{b.units}2"}
    stated = src.get("stated") or {}
    recon = []
    for key, val in (("conditioned_area", cond_area), ("garage_area", garage_area), ("glazing_area", glazing)):
        if key in stated:
            s_val = float(stated[key])
            d = (val - s_val) / s_val if s_val else 0.0
            ok = abs(d) <= AREA_TOL
            recon.append({"item": key, "stated": s_val, "modelled": round(val, 1), "delta_pct": round(100 * d, 1),
                          "ok": ok})
            note = (src.get("stated_notes") or {}).get(key)
            recon[-1]["resolution"] = note
            if not ok and not note:
                (errors if abs(d) > 0.05 else warnings).append(
                    f"{key}: modelled {val:.1f} vs stated {s_val:.1f} {b.units}2 ({100 * d:+.1f} %); find the cause "
                    "or explain it in source.stated_notes")
            elif not ok and abs(d) > 0.05:
                warnings.append(f"{key}: modelled {val:.1f} vs stated {s_val:.1f} {b.units}2 ({100 * d:+.1f} %), "
                                f"explained: {note}")
    if not stated:
        warnings.append("no stated areas recorded in source.stated; area reconciliation not possible "
                        "(look for an area schedule or title-block areas on the plans)")
    info["reconciliation"] = recon

    # dimension chains: parts must add up to the total; optional check against the model extent
    chains = []
    above_grade = [lv for lv in b.levels if lv.elevation >= -0.3] or b.levels
    for ch in src.get("dimension_chains") or []:
        try:
            parts = [_len_units(p, b.units) for p in ch.get("parts", [])]
            total = _len_units(ch["total"], b.units) if ch.get("total") is not None else None
        except ValueError as e:
            errors.append(f"dimension chain '{ch.get('label', '')}': {e}")
            continue
        rec = {"label": ch.get("label", ""), "sum_parts": round(sum(parts), 4), "total": total,
               "resolution": ch.get("resolution")}
        tol = CHAIN_TOL_FT * (0.3048 / k)
        if total is not None and parts and abs(sum(parts) - total) > tol:
            rec["drawing_inconsistent"] = True
            if not ch.get("resolution"):
                warnings.append(f"dimension chain '{rec['label']}': parts sum to {sum(parts):.3f} but total is "
                                f"{total:.3f} {b.units}; the drawing is inconsistent here. Decide which to trust "
                                "(usually the overall), tell the user, and record it as the chain's 'resolution'")
        if ch.get("axis") in ("x", "y") and total is not None:
            lv = ch.get("level") or above_grade[0].id
            polys = [Polygon(r.polygon) for r in b.rooms if r.level == lv]
            if polys:
                minx, miny, maxx, maxy = unary_union(polys).bounds
                span = (maxx - minx if ch["axis"] == "x" else maxy - miny) / k
                rec["model_span"] = round(span, 4)
                if abs(span - total) > tol:
                    errors.append(f"dimension chain '{rec['label']}': model spans {span:.3f} {b.units} along "
                                  f"{ch['axis']} but the drawing says {total:.3f}")
        chains.append(rec)
    if not chains:
        warnings.append("no dimension chains recorded in source.dimension_chains; add the overall dimensions "
                        "(with axis) so the model extent is checked against the drawing")
    info["dimension_chains"] = chains

    # site vs foundation (plans drawn for another climate)
    fnd = b.foundation.get("type", "")
    if b.is_canada and fnd.startswith("crawlspace") and float(b.foundation.get("depth_below_grade", 0.0)) < 1.0:
        warnings.append("Canadian site with a shallow crawlspace foundation: check frost protection. The plans may "
                        "come from another climate; ask whether to model them as drawn")
    info["rooms"] = [{"id": r.id, "name": r.name, "level": r.level, "type": r.type, "conditioned": r.conditioned,
                      "area_m2": round(zones[r.id]["floor_area"], 2),
                      **({f"area_{b.units}2": round(zones[r.id]["floor_area"] / a2, 1)} if b.units != "m" else {})}
                     for r in b.rooms]
    for key, getter in (("stated_rooms", lambda i: zones.get(i, {}).get("floor_area")),
                        ("stated_levels", lambda i: sum(z["floor_area"] for rid, z in zones.items()
                                                        if z.get("level") == i and z.get("conditioned")))):
        for ident, s_val in (src.get(key) or {}).items():
            got = getter(ident)
            if got is None:
                errors.append(f"source.{key}: '{ident}' is not a room/level id")
                continue
            d = (got / a2 - float(s_val)) / float(s_val)
            if abs(d) > AREA_TOL:
                warnings.append(f"{key} {ident}: modelled {got / a2:.1f} vs printed {float(s_val):.1f} {b.units}2 "
                                f"({100 * d:+.1f} %)")
    for s in geo["surfaces"]:
        if s.kind in ("window", "door") and max(v[2] for v in s.vertices) <= 0.02:
            warnings.append(f"opening {s.id} is entirely below grade (window well?): check its sill and the level "
                            "elevation; the cross-check omits it")

    # openings and rooms
    rooms_with_windows = {s.room for s in geo["surfaces"] if s.category in ("window", "glass_door")}
    for r in b.rooms:
        if r.type == "bedroom" and r.id not in rooms_with_windows:
            warnings.append(f"bedroom {r.id} has no window (egress windows are normally required): check the plan")
    ext_rooms = {s.room for s in geo["surfaces"] if s.category in ("wall_exterior", "wall_basement")}
    for r in b.rooms:
        if r.conditioned and r.id not in ext_rooms and zones[r.id]["floor_area"] > 14.0:
            warnings.append(f"room {r.id} has no exterior wall; confirm it is interior")

    # provenance
    unsourced = []
    for r in b.rooms:
        if not r.raw.get("src"):
            unsourced.append(f"room {r.id}")
    for o in b.openings:
        if not (o.raw.get("src") or o.label):
            unsourced.append(f"opening {o.id}")
    for name, a in b.assemblies.items():
        if not a.get("src"):
            unsourced.append(f"assembly {name}")
    for name, f in b.fenestration.items():
        if not f.get("src"):
            unsourced.append(f"fenestration {name}")
    for key in ("airtightness", "ventilation", "hvac"):
        v = b.raw.get(key)
        if v is None:
            unsourced.append(f"{key} (missing)")
        elif isinstance(v, dict) and not v.get("src"):
            unsourced.append(key)
    if unsourced:
        warnings.append("inputs without a recorded source (src): " + ", ".join(unsourced))
    info["unsourced"] = unsourced

    # glazing by orientation
    orient: dict[str, float] = {}
    for s in geo["surfaces"]:
        if s.category in ("window", "glass_door") and zones.get(s.zone, {}).get("conditioned"):
            o = "NESW"[int(((s.azimuth + 45) % 360) // 90)]
            orient[o] = orient.get(o, 0.0) + s.area / a2
    info["glazing_by_orientation"] = {k2: round(v, 1) for k2, v in sorted(orient.items())}
    if cond_area:
        info["window_to_floor_pct"] = round(100 * glazing / cond_area, 1)
    info["areas_by_zone_m2"] = {z: {c: round(v, 2) for c, v in d.items()} for z, d in summarize(geo).items()}
    return {"errors": errors, "warnings": warnings, "info": info, "ok": not errors}
