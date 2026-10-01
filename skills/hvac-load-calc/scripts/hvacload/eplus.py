"""Independent cross-check: EnergyPlus heat-balance design-day loads, one zone per room.

Deliberately different from the Manual J engine so the two fail differently:
- dynamic heat balance per room with ideal loads (sizing factor 1.0, no safety factors);
- infiltration from effective leakage area (Sherman-Grimsrud, EnergyPlus built-in), not Manual J tables;
- attic, crawlspace and garage are free-floating zones, not assumed temperatures;
- ground-coupled surfaces use steady-state equivalent U-values (ISO 13370-style formulas implemented
  from the open literature) against an EN 12831-style effective ground temperature.

Outputs are sensible design loads per room (latent is reported by the Manual J engine only).
"""

from __future__ import annotations

import math
import re
import sqlite3
import subprocess
from pathlib import Path

from . import tools
from .geometry import Surface
from .model import Building

SOIL_K = 2.0  # W/mK, clay/silt (ISO 13370 default category)
RSI_IN = {"wall": 0.13, "ceiling": 0.10, "roof": 0.10, "floor": 0.17}
RSE = 0.04
GYP = ("Gypsum12mm", 0.0127, 0.16, 800.0, 1090.0)  # name, thickness m, k, rho, cp
CONC = ("Concrete100mm", 0.10, 1.4, 2240.0, 900.0)

# EnergyPlus ZoneInfiltration:EffectiveLeakageArea coefficients (EnergyPlus I/O Reference, from ASHRAE)
STACK = {1: 0.000145, 2: 0.000290, 3: 0.000435}
WIND = {1: (0.000319, 0.000420, 0.000494), 2: (0.000246, 0.000325, 0.000382), 3: (0.000174, 0.000231, 0.000271),
        4: (0.000104, 0.000137, 0.000161), 5: (0.000032, 0.000042, 0.000049)}


def _hp_id(sid: str) -> str:
    """HPXML id for a surface id (same sanitising as hpxml._sid)."""
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", sid)
    return s if re.match(r"[A-Za-z_]", s) else "id_" + s


def _obj(kind: str, *fields) -> str:
    vals = ["" if f is None else (f"{f:.6g}" if isinstance(f, float) else str(f)) for f in fields]
    body = ",\n    ".join(vals)
    return f"{kind},\n    {body};\n"


def _name(s: str) -> str:
    return re.sub(r"[,;!]", "_", s)


# ---------- ground coupling (ISO 13370-style) ----------

def slab_u(area, perim, r_floor=0.0, edge_r=0.0, edge_depth=0.0, vertical=True, w=0.3):
    """Equivalent U (W/m2K, soil included) of a slab on ground."""
    if perim <= 0.01:
        perim = 0.01
    B = area / (0.5 * perim)
    dt = w + SOIL_K * (RSI_IN["floor"] + r_floor + RSE)
    if dt < B:
        u = 2 * SOIL_K / (math.pi * B + dt) * math.log(math.pi * B / dt + 1)
    else:
        u = SOIL_K / (0.457 * B + dt)
    if edge_r > 0 and edge_depth > 0:
        dprime = edge_r * SOIL_K
        D = edge_depth
        if vertical:
            psi = -SOIL_K / math.pi * (math.log(2 * D / dt + 1) - math.log(2 * D / (dt + dprime) + 1))
        else:
            psi = -SOIL_K / math.pi * (math.log(D / dt + 1) - math.log(D / (dt + dprime) + 1))
        u = max(0.02, u + 2 * psi / B)
    return u


def basement_wall_u(depth, r_wall, w=0.3, dt=None):
    """Equivalent U (W/m2K, soil included) of the below-grade part of a basement wall."""
    depth = max(depth, 0.05)
    dw = SOIL_K * (RSI_IN["wall"] + r_wall + RSE)
    dt = dt if dt is not None else w + SOIL_K * (RSI_IN["floor"] + RSE)
    if dw >= dt:
        pass
    return 2 * SOIL_K / (math.pi * depth) * (1 + 0.5 * dt / (dt + depth)) * math.log(depth / dw + 1)


def basement_floor_u(area, perim, depth, r_floor=0.0, w=0.3):
    B = area / (0.5 * max(perim, 0.01))
    dt = w + SOIL_K * (RSI_IN["floor"] + r_floor + RSE)
    if dt + 0.5 * depth < B:
        return 2 * SOIL_K / (math.pi * B + dt + 0.5 * depth) * math.log(math.pi * B / (dt + 0.5 * depth) + 1)
    return SOIL_K / (0.457 * B + dt + 0.5 * depth)


def _primary(a: Surface, b: Surface, zones: dict) -> Surface:
    ca, cb = zones[a.zone].get("conditioned"), zones[b.zone].get("conditioned")
    if ca != cb:
        return a if ca else b
    for x, y in ((a, b), (b, a)):
        if x.category in ("attic_floor", "crawl_ceiling"):
            return y
    return a if a.id < b.id else b


def epw_stats(epw: str) -> dict:
    """Annual mean dry-bulb (C) and time zone from an EPW file."""
    tot, n, hdr = 0.0, 0, []
    with open(epw, encoding="latin-1") as fh:
        for i, line in enumerate(fh):
            f = line.split(",")
            if i == 0:
                hdr = f
            elif i >= 8 and len(f) > 6:
                tot += float(f[6])
                n += 1
    return {"annual_mean_c": tot / n if n else None, "time_zone": float(hdr[8]), "lat": float(hdr[6]),
            "lon": float(hdr[7])}


# ---------- writer ----------

def write(b: Building, geo: dict, design: dict, out_path: Path, shading: dict | None = None) -> dict:
    surfaces: list[Surface] = geo["surfaces"]
    zones = geo["zones"]
    by_id = {s.id: s for s in surfaces}
    lines: list[str] = []
    notes: list[str] = []
    add = lines.append

    add(_obj("Version", "25.2"))
    add(_obj("Timestep", 6))
    add(_obj("SimulationControl", "Yes", "No", "No", "Yes", "No", "No", 1))
    add(_obj("Building", _name(b.name), float(b.plan_north_deg), "Suburbs", 0.04, 0.4, "FullExterior", 50, 6))
    add(_obj("GlobalGeometryRules", "UpperLeftCorner", "Counterclockwise", "Relative"))  # Relative: North Axis applies
    stats = epw_stats(design["epw"]) if design.get("epw") else {}
    loc = design.get("location") or {}
    lat = loc.get("lat") if loc.get("lat") is not None else stats.get("lat")
    lon = loc.get("lon") if loc.get("lon") is not None else stats.get("lon")
    if lat is None or lon is None:
        raise SystemExit("site latitude/longitude unknown: set design.lat/lon or provide an EPW")
    add(_obj("Site:Location", "Site", float(lat), float(lon), float(stats.get("time_zone", round(lon / 15))),
             float(design["elevation_m"])))
    design = {**design, "annual_mean_c": design.get("annual_mean_c") or stats.get("annual_mean_c")}

    # effective ground temperature for design (EN 12831-style annual-mean method)
    t_in = design["indoor_heating_c"]
    t_mean = design.get("annual_mean_c")
    if t_mean is None:
        t_mean = design["heating_c"] + 12.0
        notes.append("annual mean outdoor temperature unknown; assumed heating design + 12 C")
    t_ground = t_in - 1.45 * (t_in - t_mean)
    # heating design day (January) sees the EN 12831-style effective temperature; the cooling design month sees
    # the undisturbed deep-ground temperature (annual mean), so summer ground losses are not overstated
    cd_month = int((design.get("cooling_day") or {}).get("month", 7))
    monthly = [float(t_ground)] * 12
    monthly[cd_month - 1] = float(t_mean)
    add(_obj("Site:GroundTemperature:BuildingSurface", *monthly))
    notes.append(f"ground-coupled surfaces: heating day {t_ground:.1f} C = Tin - 1.45 (Tin - annual mean {t_mean:.1f} C); "
                 f"cooling day {t_mean:.1f} C (annual mean)")

    # design days
    p_atm = 101325.0 * (1 - 2.25577e-5 * design["elevation_m"]) ** 5.2559
    cd = design.get("cooling_day") or {}
    hw = design.get("heating_wind_ms", 6.7)
    add(_obj("SizingPeriod:DesignDay", "Heating Design", 1, 21, "WinterDesignDay", float(design["heating_c"]), 0.0,
             "DefaultMultipliers", None, "Wetbulb", float(design["heating_c"]), None, None, None, None, p_atm, float(hw),
             0.0, "No", "No", "No", "ASHRAEClearSky", None, None, None, None, 0.0))
    solar = ("ASHRAETau", None, None, float(cd["taub"]), float(cd["taud"]), None) if cd.get("taub") else \
        ("ASHRAEClearSky", None, None, None, None, 1.0)
    add(_obj("SizingPeriod:DesignDay", "Cooling Design", int(cd.get("month", 7)), int(cd.get("day", 21)),
             "SummerDesignDay", float(design["cooling_c"]), float(design["daily_range_c"]), "DefaultMultipliers", None,
             "Wetbulb", float(design["cooling_wb_c"]), None, None, None, None, p_atm, float(cd.get("wind_ms", 3.4)),
             float(cd.get("wind_dir", 230)), "No", "No", "No", *solar))

    # schedules
    add(_obj("ScheduleTypeLimits", "Any", None, None, "Continuous"))
    add(_obj("Schedule:Constant", "AlwaysOn", "Any", 1.0))
    add(_obj("Schedule:Constant", "DualSetpointType", "Any", 4))
    add(_obj("Schedule:Constant", "HeatSP", "Any", float(design["indoor_heating_c"])))
    add(_obj("Schedule:Constant", "CoolSP", "Any", float(design["indoor_cooling_c"])))
    add(_obj("Schedule:Compact", "GainsSummerOnly", "Any", "Through: 12/31", "For: SummerDesignDay", "Until: 24:00", 1.0,
             "For: AllOtherDays", "Until: 24:00", 0.0))
    add(_obj("Schedule:Constant", "ActivityLevel", "Any", 126.0))  # 230 + 200 Btu/h per person

    # materials
    for nm, th, k, rho, cp in (GYP, CONC):
        add(_obj("Material", nm, "Smooth", th, k, rho, cp, 0.9, 0.5, 0.5))
    constructions: dict[str, str] = {}

    def nomass(name, r):
        add(_obj("Material:NoMass", name, "MediumRough", max(0.001, r), 0.9, 0.7, 0.7))

    def opaque(key: str, u_overall: float, kind: str, interzone=False, mass="gyp") -> str:
        name = _name(f"C_{key}")
        if name in constructions:
            return name
        r_tot = 1.0 / u_overall
        films = RSI_IN.get(kind, 0.13) + (RSI_IN.get(kind, 0.13) if interzone else RSE)
        mass_r = GYP[1] / GYP[2] if mass == "gyp" else CONC[1] / CONC[2]
        r_core = r_tot - films - mass_r
        if r_core < 0.001:
            notes.append(f"construction {key}: overall R {r_tot:.2f} is below films+mass; clamped")
        nomass(name + "_core", r_core)
        inner = GYP[0] if mass == "gyp" else CONC[0]
        constructions[name] = name
        add(_obj("Construction", name, name + "_core", inner))
        return name

    def reversed_of(cname: str) -> str:
        rname = cname + "_rev"
        if rname not in constructions:
            constructions[rname] = rname
            inner = GYP[0] if not cname.startswith("C_ground") else CONC[0]
            add(_obj("Construction", rname, inner, cname + "_core"))
        return rname

    # interior partition (adiabatic) with some mass
    nomass("PartitionCavity", 0.17)
    add(_obj("Construction", "Partition", GYP[0], "PartitionCavity", GYP[0]))

    # glazing & doors
    for pname, spec in b.fenestration.items():
        if spec.get("kind", "window") in ("door",) or float(spec.get("shgc", 0)) <= 0:
            nomass(f"Door_{_name(pname)}", 1.0 / spec["u_si"] - RSI_IN["wall"] - RSE)
            add(_obj("Construction", f"CF_{_name(pname)}", f"Door_{_name(pname)}"))
        else:
            add(_obj("WindowMaterial:SimpleGlazingSystem", f"Glz_{_name(pname)}", float(spec["u_si"]),
                     float(spec["shgc"]), None))
            add(_obj("Construction", f"CF_{_name(pname)}", f"Glz_{_name(pname)}"))
    # per-window summer shading (same coefficients the primary engine applied), as SHGC multipliers
    shading = shading or {}
    shaded: dict[tuple, str] = {}

    def glazing_construction(s: Surface) -> str:
        spec = b.fenestration[s.product]
        f = round(float(shading.get(_hp_id(s.id), 1.0)), 4)
        if f >= 0.9999 or s.kind == "door" or float(spec.get("shgc", 0)) <= 0:
            return f"CF_{_name(s.product)}"
        key = (s.product, f)
        if key not in shaded:
            nm = f"CF_{_name(s.product)}_sc{f:.3f}"
            add(_obj("WindowMaterial:SimpleGlazingSystem", f"Glz_{_name(s.product)}_sc{f:.3f}", float(spec["u_si"]),
                     float(spec["shgc"]) * f, None))
            add(_obj("Construction", nm, f"Glz_{_name(s.product)}_sc{f:.3f}"))
            shaded[key] = nm
        return shaded[key]
    if shading:
        notes.append("windows: SHGC multiplied by the summer shading coefficients the primary engine applied "
                     f"(range {min(shading.values()):.2f}-{max(shading.values()):.2f})")

    # zones
    cond_zones = [z for z, v in zones.items() if v.get("conditioned")]
    for z, v in zones.items():
        add(_obj("Zone", _name(z), 0.0, 0.0, 0.0, 0.0, 1, 1, None, float(v["volume"]), float(v["floor_area"]), None,
                 None, "Yes" if v.get("conditioned") else "No"))

    # surfaces
    def verts(v):
        return [f"{x:.4f}" for p in v for x in p]

    ground_cats = {"slab", "slab_garage", "slab_crawlspace"}
    for s in surfaces:
        if s.kind in ("window", "door", "skylight"):
            continue
        stype = {"wall": "Wall", "floor": "Floor", "ceiling": "Ceiling", "roof": "Roof"}[s.kind]
        kind = {"wall": "wall", "floor": "floor", "ceiling": "ceiling", "roof": "roof"}[s.kind]
        zone = _name(s.zone)
        if s.boundary == "adiabatic":
            add(_obj("BuildingSurface:Detailed", _name(s.id), stype, "Partition", zone, None, "Adiabatic", None,
                     "NoSun", "NoWind", None, len(s.vertices), *verts(s.vertices)))
            continue
        if s.boundary == "zone":
            # interzone pair: the primary side gets the forward construction, its partner the reverse
            partner = by_id[s.other_side]
            prim = _primary(s, partner, zones)
            key = f"iz_{prim.assembly or 'none'}_{prim.kind}"
            cname = opaque(key, prim.u_si or 1.0, prim.kind, interzone=True)
            if s is not prim:
                cname = reversed_of(cname)
            add(_obj("BuildingSurface:Detailed", _name(s.id), stype, cname, zone, None, "Surface", _name(s.other_side),
                     "NoSun", "NoWind", None, len(s.vertices), *verts(s.vertices)))
            continue
        if s.category in ground_cats:
            a = s.area
            asm = b.assemblies.get(s.assembly, {})
            r_floor = float(asm.get("under_r_ip", 0.0)) * 0.1761102 if asm.get("under_full") else 0.0
            edge_r = float(asm.get("perimeter_r_ip", 0.0)) * 0.1761102
            edge_d = float(asm.get("perimeter_depth_ft", 0.0)) * 0.3048
            depth = 0.0
            lv_el = b.level(s.level).elevation if s.level else 0.0
            if s.zone != "crawlspace" and lv_el < -0.3:
                depth = -lv_el
            if depth > 0:
                u = basement_floor_u(a, s.exposed_perimeter, depth, r_floor)
            else:
                u = slab_u(a, s.exposed_perimeter, r_floor, edge_r, edge_d)
            cname = opaque(f"ground_{s.id}", u, "floor", mass="conc")
            add(_obj("BuildingSurface:Detailed", _name(s.id), stype, cname, zone, None, "Ground", None, "NoSun",
                     "NoWind", None, len(s.vertices), *verts(s.vertices)))
            notes.append(f"{s.id}: ground-coupled U {u:.3f} W/m2K (area {a:.1f} m2, exposed perimeter "
                         f"{s.exposed_perimeter:.1f} m)")
            continue
        if s.boundary == "foundation":
            # split at grade: above-grade part to outdoors, below-grade part to ground
            (x1, y1, ztop), (_, _, zbot), (x2, y2, _), _ = s.vertices
            zg = max(zbot, min(ztop, 0.0))
            parts = []
            if ztop - zg > 0.01:
                parts.append(("ag", zg, ztop))
            if zg - zbot > 0.01:
                parts.append(("bg", zbot, zg))
            for tag, z0, z1 in parts:
                v = [(x1, y1, z1), (x1, y1, z0), (x2, y2, z0), (x2, y2, z1)]
                if tag == "ag":
                    cname = opaque(s.assembly or "fw", s.u_si, "wall")
                    add(_obj("BuildingSurface:Detailed", _name(s.id) + "_ag", stype, cname, zone, None, "Outdoors",
                             None, "SunExposed", "WindExposed", None, 4, *verts(v)))
                else:
                    r_wall = max(0.0, 1.0 / s.u_si - RSI_IN["wall"] - RSE)
                    u = basement_wall_u(s.depth_below_grade, r_wall)
                    cname = opaque(f"ground_bw_{s.assembly}_{s.depth_below_grade:.2f}", u, "wall", mass="conc")
                    add(_obj("BuildingSurface:Detailed", _name(s.id) + "_bg", stype, cname, zone, None, "Ground",
                             None, "NoSun", "NoWind", None, 4, *verts(v)))
            continue
        # outdoors
        u = s.u_si * s.area_factor  # keep U*A for sloped cathedral roofs drawn flat
        cname = opaque(f"{s.assembly}_{s.kind}_{s.area_factor:.3f}", u, kind)
        add(_obj("BuildingSurface:Detailed", _name(s.id), stype, cname, zone, None, "Outdoors", None, "SunExposed",
                 "WindExposed", None, len(s.vertices), *verts(s.vertices)))

    # subsurfaces
    for s in surfaces:
        if s.kind not in ("window", "door", "skylight"):
            continue
        host = by_id[s.parent]
        spec = b.fenestration[s.product]
        is_glass = float(spec.get("shgc", 0)) > 0 and spec.get("kind", "window") != "door"
        ftype = "Window" if s.kind in ("window", "skylight") and s.category != "glass_door" else (
            "GlassDoor" if is_glass else "Door")
        if not is_glass:
            ftype = "Door"
        host_name = _name(host.id)
        verts_sub = s.vertices
        if host.boundary == "foundation":
            host_name += "_ag"
            z_bot, z_top = min(v[2] for v in s.vertices), max(v[2] for v in s.vertices)
            ag_top = max(v[2] for v in host.vertices)
            if ag_top - 0.02 <= 0.01 or z_top - z_bot > ag_top - 0.02:
                notes.append(f"opening {s.id} is below grade (window well?): omitted from the cross-check model")
                continue
            if z_bot < 0.01:  # partly or fully below grade: shift up onto the above-grade wall
                dz = 0.01 - z_bot
                verts_sub = [(x, y, z + dz) for x, y, z in s.vertices]
                notes.append(f"opening {s.id} extends below grade: raised {dz:.2f} m in the cross-check model")
        other = None
        if host.boundary == "zone":
            # mirror subsurface on the partner wall
            partner = by_id[host.other_side]
            other = _name(s.id) + "_mirror"
            mv = [s.vertices[3], s.vertices[2], s.vertices[1], s.vertices[0]]
            add(_obj("FenestrationSurface:Detailed", other, "Door", f"CF_{_name(s.product)}", _name(partner.id),
                     _name(s.id), None, None, 1, 4, *verts(mv)))
        add(_obj("FenestrationSurface:Detailed", _name(s.id), ftype, glazing_construction(s), host_name,
                 other, None, None, 1, 4, *verts(verts_sub)))

    # HVAC: ideal loads per conditioned zone
    add(_obj("ThermostatSetpoint:DualSetpoint", "DualSP", "HeatSP", "CoolSP"))
    for z in cond_zones:
        n = _name(z)
        add(_obj("ZoneControl:Thermostat", f"{n} Thermostat", n, "DualSetpointType", "ThermostatSetpoint:DualSetpoint",
                 "DualSP"))
        add(_obj("Sizing:Zone", n, "SupplyAirTemperature", 14.0, None, "SupplyAirTemperature", 40.0, None, 0.0085,
                 0.008, None, 1.0, 1.0, "DesignDay", None, None, None, None, "DesignDay"))
        add(_obj("ZoneHVAC:IdealLoadsAirSystem", f"{n} Ideal", None, f"{n} Supply Node", None, None, 50.0, 13.0, 0.015,
                 0.009, "NoLimit", None, None, "NoLimit", None, None, None, None, "None", 0.7, "None", None, None,
                 "None", "NoEconomizer", "None", 0.0, 0.0))
        add(_obj("ZoneHVAC:EquipmentList", f"{n} Equipment", "SequentialLoad", "ZoneHVAC:IdealLoadsAirSystem",
                 f"{n} Ideal", 1, 1, None, None))
        add(_obj("ZoneHVAC:EquipmentConnections", n, f"{n} Equipment", f"{n} Supply Node", None, f"{n} Air Node",
                 f"{n} Return Node"))

    # infiltration: effective leakage area from blower door (flow exponent 0.65)
    at = b.raw.get("airtightness", {})
    cond_vol = sum(zones[z]["volume"] for z in cond_zones)
    if "ach50" in at or "cfm50" in at:
        q50 = float(at["ach50"]) * cond_vol / 3600 if "ach50" in at else float(at["cfm50"]) * 0.00047194745
        rho = 1.2
        ela_m2 = q50 * (4.0 / 50.0) ** 0.65 / math.sqrt(2 * 4.0 / rho)
        n_st = max(1, min(3, len({b.room(z).level for z in cond_zones if b.level(b.room(z).level).elevation > -0.3})))
        shelter = int(b.raw.get("site", {}).get("shielding_class", 4))
        shelter = max(1, min(5, shelter))
        cs, cw = STACK[n_st], WIND[shelter][n_st - 1]
        # apportion by above-grade exterior wall area (same basis as the Manual J room infiltration split)
        def ag_wall_area(s):
            if s.kind != "wall" or s.boundary not in ("outside", "foundation"):
                return 0.0
            if s.boundary == "outside":
                return s.area
            (x1, y1, ztop), (_, _, zbot), (x2, y2, _), _ = s.vertices
            return math.hypot(x2 - x1, y2 - y1) * max(0.0, ztop - max(zbot, 0.0))
        ext_area = {z: sum(ag_wall_area(s) for s in surfaces if s.zone == z) for z in cond_zones}
        tot = sum(ext_area.values()) or 1.0
        for z in cond_zones:
            ela_cm2 = ela_m2 * 1e4 * ext_area[z] / tot
            if ela_cm2 > 0.01:
                add(_obj("ZoneInfiltration:EffectiveLeakageArea", f"{_name(z)} ELA", _name(z), "AlwaysOn",
                         float(ela_cm2), cs, cw))
        notes.append(f"infiltration: ELA(4 Pa) {ela_m2 * 1e4:.0f} cm2 from {q50 * 2118.88:.0f} CFM50, "
                     f"stack {cs}, wind {cw} (shelter class {shelter}), apportioned by above-grade exterior wall area")
    else:
        notes.append("infiltration: no blower-door value; EnergyPlus infiltration omitted (cross-check incomplete)")

    # unconditioned zone air exchange (documented assumptions)
    for zid, zv in zones.items():
        if zv["kind"] != "attic":
            continue
        sla = 1 / 300 if zv["type"] == "attic_vented" else 1 / 3000
        add(_obj("ZoneInfiltration:EffectiveLeakageArea", f"{zid} ELA", zid, "AlwaysOn",
                 float(zv["floor_area"] * sla * 1e4), STACK[1], WIND[3][0]))
    if "crawlspace" in zones:
        sla = 1 / 150 if zones["crawlspace"]["type"] == "crawlspace_vented" else 1 / 1500
        add(_obj("ZoneInfiltration:EffectiveLeakageArea", "crawlspace ELA", "crawlspace", "AlwaysOn",
                 float(zones["crawlspace"]["floor_area"] * sla * 1e4), STACK[1], WIND[3][0]))
    for z, v in zones.items():
        if v["kind"] == "room" and not v["conditioned"]:
            add(_obj("ZoneInfiltration:DesignFlowRate", f"{_name(z)} Infil", _name(z), "AlwaysOn", "AirChanges/Hour",
                     None, None, None, 1.0, 1.0, 0.0, 0.0, 0.0))
    notes.append("unconditioned zones: vented attic SLA 1/300, vented crawlspace SLA 1/150, garage 1 ACH (assumptions)")

    # mechanical ventilation as balanced flow net of heat recovery
    vent = b.raw.get("ventilation", {})
    if vent.get("type", "none") != "none":
        flow = float(vent["cfm"]) * 0.00047194745 if "cfm" in vent else float(vent["lps"]) / 1000
        flow *= float(vent.get("hours", 24)) / 24
        eff = float(vent.get("asre", vent.get("sre", 0.0))) if vent["type"] in ("hrv", "erv") else 0.0
        fa = sum(zones[z]["floor_area"] for z in cond_zones)
        for z in cond_zones:
            q = flow * (1 - eff) * zones[z]["floor_area"] / fa
            add(_obj("ZoneVentilation:DesignFlowRate", f"{_name(z)} Vent", _name(z), "AlwaysOn", "Flow/Zone", q, None,
                     None, None, "Balanced", 0.0, 1.0, 1.0, 0.0, 0.0, 0.0))
        notes.append(f"mechanical ventilation {flow * 2118.88:.0f} CFM modelled as balanced flow x (1 - SRE {eff})")

    # internal gains (cooling design day only, Manual J magnitudes for comparability)
    gains = design["internal_gains"]
    for z in cond_zones:
        g = gains["per_room"].get(z, {})
        if g.get("occupants", 0) > 0:
            add(_obj("People", f"{_name(z)} People", _name(z), "GainsSummerOnly", "People", float(g["occupants"]),
                     None, None, 0.3, 230 / 430, "ActivityLevel"))
        if g.get("sensible_btuh", 0) > 0:
            w = (g["sensible_btuh"] + g.get("latent_btuh", 0)) * 0.29307107
            lat = g.get("latent_btuh", 0) / (g["sensible_btuh"] + g.get("latent_btuh", 0))
            add(_obj("ElectricEquipment", f"{_name(z)} Appliances", _name(z), "GainsSummerOnly", "EquipmentLevel",
                     float(w), None, None, float(lat), 0.3, 0.0))

    add(_obj("Output:Table:SummaryReports", "HVACSizingSummary", "ZoneComponentLoadSummary"))
    add(_obj("OutputControl:Table:Style", "HTML"))
    add(_obj("Output:SQLite", "SimpleAndTabular"))
    add(_obj("Output:Surfaces:List", "Details"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"idf": str(out_path), "notes": notes, "ground_temp_c": t_ground}


def run(idf: Path, out_dir: Path) -> dict:
    ep = tools.energyplus_exe()
    if not ep:
        raise SystemExit("EnergyPlus not installed: run `uv run scripts/hvacload.py setup`")
    out_dir.mkdir(parents=True, exist_ok=True)
    idd = ep.parent / "Energy+.idd"
    cmd = [str(ep), "-d", str(out_dir), "-i", str(idd), str(idf)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    err = out_dir / "eplusout.err"
    err_txt = err.read_text(encoding="utf-8", errors="replace") if err.exists() else ""
    severe = [ln for ln in err_txt.splitlines() if "** Severe" in ln or "**  Fatal" in ln or "** Fatal" in ln]
    geom = [ln.strip() for ln in err_txt.splitlines()
            if "** Warning" in ln and any(k in ln for k in ("base surface", "Subsurface", "not within", "vertices",
                                                             "enclosed", "Nonplanar", "degenerate"))]
    sql = out_dir / "eplusout.sql"
    return {"ok": p.returncode == 0 and sql.exists(), "returncode": p.returncode, "cmd": " ".join(cmd),
            "severe": severe[:40], "warnings": err_txt.count("** Warning"), "geometry_warnings": geom[:20],
            "err": str(err), "sql": str(sql),
            "stdout_tail": p.stdout[-2000:]}


def parse(sql_path: str, geo: dict) -> dict:
    con = sqlite3.connect(sql_path)
    cur = con.cursor()

    def table(report, tname):
        rows = cur.execute(
            "SELECT RowName, ColumnName, Value, Units FROM TabularDataWithStrings "
            "WHERE ReportName=? AND TableName=?", (report, tname)).fetchall()
        out: dict = {}
        for r, c, v, u in rows:
            out.setdefault(r, {})[c] = v
        return out

    heat = table("HVACSizingSummary", "Zone Sensible Heating")
    cool = table("HVACSizingSummary", "Zone Sensible Cooling")
    rooms = {}
    name_map = {_name(z).upper(): z for z in geo["zones"]}
    for zname in set(heat) | set(cool):
        z = name_map.get(zname.upper(), zname)
        h = heat.get(zname, {})
        c = cool.get(zname, {})
        rooms[z] = {"heating_w": float(h.get("Calculated Design Load") or 0),
                    "cooling_sensible_w": float(c.get("Calculated Design Load") or 0),
                    "cooling_peak": c.get("Date/Time Of Peak {TIMESTAMP}") or c.get("Date/Time Of Peak"),
                    "heating_peak": h.get("Date/Time Of Peak {TIMESTAMP}") or h.get("Date/Time Of Peak")}
    # component loads at the zone peak (ZoneComponentLoadSummary)
    comps = {}
    for z in rooms:
        for which in ("Estimated Heating Peak Load Components", "Estimated Cooling Peak Load Components"):
            rows = cur.execute(
                "SELECT RowName, ColumnName, Value FROM TabularDataWithStrings WHERE ReportName='Zone Component Load Summary' "
                "AND ReportForString=? AND TableName=?", (_name(z).upper(), which)).fetchall()
            d: dict = {}
            for r, c, v in rows:
                if c in ("Sensible - Instant", "Sensible - Delayed", "Total"):
                    try:
                        d.setdefault(r, {})[c] = float(v)
                    except (TypeError, ValueError):
                        pass
            comps.setdefault(z, {})["heating" if "Heating" in which else "cooling"] = d
    # surface azimuths as computed by EnergyPlus (orientation self-check)
    az = {}
    try:
        for name, azimuth in cur.execute("SELECT SurfaceName, Azimuth FROM Surfaces").fetchall():
            az[name] = azimuth
    except sqlite3.Error:
        pass
    con.close()
    for z, d in rooms.items():
        d["components"] = comps.get(z, {})
    cond = [z for z, v in geo["zones"].items() if v.get("conditioned")]
    total = {"heating_w": sum(rooms[z]["heating_w"] for z in cond if z in rooms),
             "cooling_sensible_w": sum(rooms[z]["cooling_sensible_w"] for z in cond if z in rooms),
             "note": "sum of room peaks (non-coincident for cooling)"}
    return {"method": "EnergyPlus heat-balance design days (ideal loads, one zone per room)", "rooms": rooms,
            "total": total, "eplus_azimuths": az}
