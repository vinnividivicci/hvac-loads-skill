"""Write an HPXML file from the surface list, run OpenStudio-HPXML's ACCA Manual J design-load
calculation (--skip-simulation), and parse room-by-room results.

HPXML element ids reuse the surface ids from geometry.py, so every line of the engine's
component breakdown maps back to a surface (and from there to the plans).
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from . import tools
from .geometry import Surface
from .model import Building
from .units import W_PER_BTUH, c_to_f, m2_to_ft2, m_to_ft, dc_to_df

NS = "http://hpxmlonline.com/2025/12"
ET.register_namespace("", NS)

LOC = {  # zone kind -> HPXML location
    "attic_vented": "attic - vented", "attic_unvented": "attic - unvented",
    "crawlspace_vented": "crawlspace - vented", "crawlspace_unvented": "crawlspace - unvented",
    "garage": "garage", "basement_unconditioned": "basement - unconditioned",
}


def _sid(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", s)
    return s if re.match(r"[A-Za-z_]", s) else "id_" + s


def _e(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, f"{{{NS}}}{tag}", {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def _r_ip(u_si: float) -> float:
    return round(5.678263 / u_si, 3)


def _num(x, nd=2):
    return f"{x:.{nd}f}"


def write(b: Building, geo: dict, design: dict, out_path: Path) -> dict:
    surfaces: list[Surface] = geo["surfaces"]
    zones = geo["zones"]
    by_id = {s.id: s for s in surfaces}
    raw = b.raw
    cond_rooms = [r for r in b.rooms if r.conditioned]
    attic_loc = LOC.get(zones.get("attic", {}).get("type", "attic_vented"), "attic - vented")
    crawl_loc = LOC.get(zones.get("crawlspace", {}).get("type", "crawlspace_vented"), "crawlspace - vented")

    def room_loc(rid):
        r = b.room(rid)
        if not r.conditioned:
            return LOC[r.type]
        lv = b.level(r.level)
        return "basement - conditioned" if lv.elevation < -0.3 else "conditioned space"

    def zone_loc(zid):
        if zid.startswith("attic"):
            return attic_loc
        if zid == "crawlspace":
            return crawl_loc
        return room_loc(zid)

    root = ET.Element(f"{{{NS}}}HPXML", {"schemaVersion": "5.0"})
    hdr = _e(root, "XMLTransactionHeaderInformation")
    _e(hdr, "XMLType", "HPXML")
    _e(hdr, "XMLGeneratedBy", "hvacload")
    _e(hdr, "CreatedDateAndTime", "2000-01-01T00:00:00-07:00")
    _e(hdr, "Transaction", "create")
    _e(root, "SoftwareInfo")
    bld = _e(root, "Building")
    _e(bld, "BuildingID", id="MyBuilding")
    site = _e(bld, "Site")
    _e(site, "SiteID", id="SiteID")
    loc = design.get("location", {})
    if loc.get("lat") is not None:
        geo_el = _e(site, "GeoLocation")
        _e(geo_el, "Latitude", _num(loc["lat"], 4))
        _e(geo_el, "Longitude", _num(loc["lon"], 4))
    if design.get("elevation_m") is not None:
        _e(site, "Elevation", _num(m_to_ft(design["elevation_m"]), 1))
    ps = _e(bld, "ProjectStatus")
    _e(ps, "EventType", "proposed workscope")
    det = _e(bld, "BuildingDetails")

    # ---- summary
    summ = _e(det, "BuildingSummary")
    bsite = _e(summ, "Site")
    _e(bsite, "Surroundings", "stand-alone")
    shielding = raw.get("site", {}).get("shielding")
    if shielding:
        _e(bsite, "ShieldingofHome", shielding)
    bc = _e(summ, "BuildingConstruction")
    _e(bc, "ResidentialFacilityType", "single-family detached")
    cond_levels = sorted({r.level for r in cond_rooms}, key=lambda lid: b.level(lid).elevation)
    above = [lid for lid in cond_levels if b.level(lid).elevation >= -0.3]
    _e(bc, "NumberofConditionedFloors", _num(len(cond_levels), 1))
    _e(bc, "NumberofConditionedFloorsAboveGrade", _num(max(1, len(above)), 1))
    n_bed = raw.get("bedrooms")
    if n_bed is None:
        n_bed = sum(1 for r in cond_rooms if r.type == "bedroom")
    _e(bc, "NumberofBedrooms", int(n_bed))
    n_bath = raw.get("bathrooms")
    if n_bath is None:
        n_bath = sum(1 for r in cond_rooms if r.type == "bath")
    if n_bath:
        _e(bc, "NumberofBathrooms", int(n_bath))
    cfa = sum(zones[r.id]["floor_area"] for r in cond_rooms)
    vol = sum(zones[r.id]["volume"] for r in cond_rooms)
    _e(bc, "ConditionedFloorArea", _num(m2_to_ft2(cfa), 1))
    _e(bc, "ConditionedBuildingVolume", _num(vol / 0.0283168, 0))
    ext = _e(summ, "extension")
    sz = _e(ext, "HVACSizingControl")
    mj = _e(sz, "ManualJInputs")
    _e(mj, "HeatingDesignTemperature", _num(c_to_f(design["heating_c"]), 1))
    _e(mj, "CoolingDesignTemperature", _num(c_to_f(design["cooling_c"]), 1))
    _e(mj, "DailyTemperatureRange", design["daily_range_class"])
    _e(mj, "HeatingSetpoint", _num(c_to_f(design["indoor_heating_c"]), 1))
    _e(mj, "CoolingSetpoint", _num(c_to_f(design["indoor_cooling_c"]), 1))
    _e(mj, "HumiditySetpoint", _num(design["indoor_rh"], 2))
    if design.get("humidity_difference_gr") is not None:
        _e(mj, "HumidityDifference", _num(design["humidity_difference_gr"], 1))
    gains = design["internal_gains"]
    _e(mj, "InternalLoadsSensible", _num(gains["sensible_btuh_total"], 0))
    _e(mj, "InternalLoadsLatent", _num(gains["latent_btuh_total"], 0))
    _e(mj, "NumberofOccupants", _num(gains["occupants_total"], 1))
    if raw.get("site", {}).get("shielding_class"):
        _e(mj, "InfiltrationShieldingClass", int(raw["site"]["shielding_class"]))
    _e(mj, "InfiltrationMethod", "blower door" if "leakiness" not in raw.get("airtightness", {}) else
       "default infiltration table")

    # ---- climate
    crz = _e(det, "ClimateandRiskZones")
    if design.get("climate_zone_iecc"):
        cz = _e(crz, "ClimateZoneIECC")
        _e(cz, "Year", 2021)
        _e(cz, "ClimateZone", design["climate_zone_iecc"])
    ws = _e(crz, "WeatherStation")
    _e(ws, "SystemIdentifier", id="WeatherStation")
    _e(ws, "Name", Path(design["epw"]).stem)
    wext = _e(ws, "extension")
    _e(wext, "EPWFilePath", str(Path(design["epw"]).resolve()).replace("\\", "/"))

    # ---- zones / spaces
    zel = _e(_e(det, "Zones"), "Zone")
    _e(zel, "SystemIdentifier", id="ConditionedZone")
    _e(zel, "ZoneType", "conditioned")
    spaces = _e(zel, "Spaces")
    for r in cond_rooms:
        sp = _e(spaces, "Space")
        _e(sp, "SystemIdentifier", id=_sid(r.id))
        _e(sp, "FloorArea", _num(m2_to_ft2(zones[r.id]["floor_area"]), 2))
        spx = _e(_e(sp, "extension"), "ManualJInputs")
        _e(spx, "InternalLoadsSensible", _num(gains["per_room"][r.id]["sensible_btuh"], 0))
        _e(spx, "InternalLoadsLatent", _num(gains["per_room"][r.id]["latent_btuh"], 0))
        _e(spx, "NumberofOccupants", _num(gains["per_room"][r.id]["occupants"], 2))
        if design.get("fenestration_procedure"):
            _e(spx, "FenestrationLoadProcedure", design["fenestration_procedure"])

    # ---- enclosure
    enc = _e(det, "Enclosure")
    ai = _e(_e(enc, "AirInfiltration"), "AirInfiltrationMeasurement")
    _e(ai, "SystemIdentifier", id="AirInfiltrationMeasurement1")
    at = raw.get("airtightness", {})
    if "leakiness" in at:
        _e(ai, "LeakinessDescription", at["leakiness"])
    else:
        _e(ai, "HousePressure", "50.0")
        bal = _e(ai, "BuildingAirLeakage")
        if "cfm50" in at:
            _e(bal, "UnitofMeasure", "CFM")
            _e(bal, "AirLeakage", _num(float(at["cfm50"]), 1))
        else:
            _e(bal, "UnitofMeasure", "ACH")
            _e(bal, "AirLeakage", _num(float(at["ach50"]), 2))
        _e(ai, "InfiltrationVolume", _num(vol / 0.0283168, 0))

    if "attic" in zones:
        a = _e(_e(enc, "Attics"), "Attic")
        _e(a, "SystemIdentifier", id="Attic1")
        _e(_e(_e(a, "AtticType"), "Attic"), "Vented", str(zones["attic"]["type"] == "attic_vented").lower())
    fnds = []
    if "crawlspace" in zones:
        fnds.append(("Crawlspace", "Vented", str(zones["crawlspace"]["type"] == "crawlspace_vented").lower()))
    if any(room_loc(r.id) == "basement - conditioned" for r in cond_rooms):
        fnds.append(("Basement", "Conditioned", "true"))
    if any(r.type == "basement_unconditioned" for r in b.rooms):
        fnds.append(("Basement", "Conditioned", "false"))
    if fnds:
        fe = _e(enc, "Foundations")
        for i, (typ, key, val) in enumerate(fnds):
            f = _e(fe, "Foundation")
            _e(f, "SystemIdentifier", id=f"Foundation{i + 1}")
            _e(_e(_e(f, "FoundationType"), typ), key, val)

    attic = b.attic
    roof_type = attic.get("roof_type", "asphalt or fiberglass shingles")
    roof_color = attic.get("roof_color", "medium")
    pitch = float(attic.get("roof_pitch", 6.0))

    def roof_el(parent, s: Surface, interior: str, area_ft2: float, space=None):
        el = _e(parent, "Roof")
        _e(el, "SystemIdentifier", id=_sid(s.id))
        if space:
            _e(el, "AttachedToSpace", idref=_sid(space))
        _e(el, "InteriorAdjacentTo", interior)
        _e(el, "Area", _num(area_ft2, 2))
        if s.azimuth is not None:
            _e(el, "Azimuth", int(round(s.azimuth)) % 360)
        _e(el, "RoofType", roof_type)
        _e(el, "RoofColor", roof_color)
        _e(el, "Pitch", _num(pitch, 2))
        _e(el, "RadiantBarrier", str(bool(attic.get("radiant_barrier", False))).lower())
        ins = _e(el, "Insulation")
        _e(ins, "SystemIdentifier", id=_sid(s.id) + "Insulation")
        _e(ins, "AssemblyEffectiveRValue", _r_ip(s.u_si))

    roofs = [s for s in surfaces if s.kind == "roof"]
    if roofs:
        re_ = _e(enc, "Roofs")
        for s in roofs:
            if s.zone.startswith("attic"):
                roof_el(re_, s, attic_loc, m2_to_ft2(s.area))
            else:
                space = s.room if b.room(s.room).conditioned else None
                roof_el(re_, s, room_loc(s.room), m2_to_ft2(s.area), space)

    wall_cats = {"wall_exterior", "wall_to_garage", "wall_to_basement_unconditioned", "wall_garage_exterior",
                 "wall_attic_gable"}
    walls = [s for s in surfaces if s.kind == "wall" and s.category in wall_cats
             and not (s.category in ("wall_to_garage", "wall_to_basement_unconditioned") and not b.room(s.room).conditioned)]
    if walls:
        we = _e(enc, "Walls")
        for s in walls:
            asm = b.assemblies.get(s.assembly, {})
            el = _e(we, "Wall")
            _e(el, "SystemIdentifier", id=_sid(s.id))
            if s.room and b.room(s.room).conditioned:
                _e(el, "AttachedToSpace", idref=_sid(s.room))
            if s.category in ("wall_exterior", "wall_garage_exterior", "wall_attic_gable"):
                ext_to = "outside"
            else:
                ext_to = zone_loc(s.adjacent_zone)
            _e(el, "ExteriorAdjacentTo", ext_to)
            _e(el, "InteriorAdjacentTo", attic_loc if s.zone.startswith("attic") else room_loc(s.room))
            if s.category == "wall_attic_gable":
                _e(el, "AtticWallType", "gable")
            _e(_e(el, "WallType"), asm.get("wall_type", "WoodStud"))
            _e(el, "Area", _num(m2_to_ft2(s.area), 2))
            _e(el, "Azimuth", int(round(s.azimuth)) % 360)
            if asm.get("siding"):
                _e(el, "Siding", asm["siding"])
            _e(el, "Color", asm.get("color", "medium"))
            ins = _e(el, "Insulation")
            _e(ins, "SystemIdentifier", id=_sid(s.id) + "Insulation")
            _e(ins, "AssemblyEffectiveRValue", _r_ip(s.u_si))

    fwalls = [s for s in surfaces if s.category in ("wall_basement", "wall_crawlspace")]
    if fwalls:
        fe = _e(enc, "FoundationWalls")
        for s in fwalls:
            asm = b.assemblies.get(s.assembly, {})
            el = _e(fe, "FoundationWall")
            _e(el, "SystemIdentifier", id=_sid(s.id))
            if s.room and b.room(s.room).conditioned:
                _e(el, "AttachedToSpace", idref=_sid(s.room))
            _e(el, "ExteriorAdjacentTo", "ground")
            _e(el, "InteriorAdjacentTo", crawl_loc if s.zone == "crawlspace" else room_loc(s.room))
            _e(el, "Type", asm.get("foundation_type", "solid concrete"))
            h = s.vertices[0][2] - s.vertices[1][2]
            _e(el, "Height", _num(m_to_ft(h), 3))
            _e(el, "Area", _num(m2_to_ft2(s.area), 2))
            _e(el, "Azimuth", int(round(s.azimuth)) % 360)
            if asm.get("thickness_in"):
                _e(el, "Thickness", _num(float(asm["thickness_in"]), 1))
            _e(el, "DepthBelowGrade", _num(min(m_to_ft(s.depth_below_grade), m_to_ft(h)), 3))
            ins = _e(el, "Insulation")
            _e(ins, "SystemIdentifier", id=_sid(s.id) + "Insulation")
            _e(ins, "AssemblyEffectiveRValue", _r_ip(s.u_si))

    floor_cats = {"ceiling_attic": ("ceiling", attic_loc), "ceiling_garage": ("ceiling", attic_loc),
                  "floor_crawlspace": ("floor", crawl_loc), "floor_exposed": ("floor", "outside"),
                  "floor_over_garage": ("floor", "garage"),
                  "floor_over_basement_unconditioned": ("floor", "basement - unconditioned"),
                  "ceiling_to_garage": ("ceiling", "garage")}
    floors = [s for s in surfaces if s.category in floor_cats and s.room and
              (b.room(s.room).conditioned or s.category == "ceiling_garage")]
    if floors:
        fe = _e(enc, "Floors")
        for s in floors:
            asm = b.assemblies.get(s.assembly, {})
            which, ext_to = floor_cats[s.category]
            el = _e(fe, "Floor")
            _e(el, "SystemIdentifier", id=_sid(s.id))
            if b.room(s.room).conditioned:
                _e(el, "AttachedToSpace", idref=_sid(s.room))
            _e(el, "ExteriorAdjacentTo", ext_to)
            _e(el, "InteriorAdjacentTo", room_loc(s.room))
            _e(el, "FloorOrCeiling", which)
            _e(_e(el, "FloorType"), asm.get("floor_type", "WoodFrame"))
            _e(el, "Area", _num(m2_to_ft2(s.area), 2))
            ins = _e(el, "Insulation")
            _e(ins, "SystemIdentifier", id=_sid(s.id) + "Insulation")
            _e(ins, "AssemblyEffectiveRValue", _r_ip(s.u_si))

    slabs = [s for s in surfaces if s.category in ("slab", "slab_garage", "slab_crawlspace")]
    if slabs:
        se = _e(enc, "Slabs")
        for s in slabs:
            asm = b.assemblies.get(s.assembly, {})
            el = _e(se, "Slab")
            _e(el, "SystemIdentifier", id=_sid(s.id))
            if s.room and b.room(s.room).conditioned:
                _e(el, "AttachedToSpace", idref=_sid(s.room))
            _e(el, "InteriorAdjacentTo", crawl_loc if s.zone == "crawlspace" else room_loc(s.room))
            _e(el, "Area", _num(m2_to_ft2(s.area), 2))
            thick = asm.get("thickness_in", 0.0 if s.category == "slab_crawlspace" else 4.0)
            _e(el, "Thickness", _num(float(thick), 1))
            _e(el, "ExposedPerimeter", _num(m_to_ft(s.exposed_perimeter), 2))
            pi = _e(el, "PerimeterInsulation")
            _e(pi, "SystemIdentifier", id=_sid(s.id) + "PerimeterInsulation")
            lay = _e(pi, "Layer")
            _e(lay, "NominalRValue", _num(float(asm.get("perimeter_r_ip", 0.0)), 1))
            _e(lay, "InsulationDepth", _num(float(asm.get("perimeter_depth_ft", 0.0)), 2))
            ui = _e(el, "UnderSlabInsulation")
            _e(ui, "SystemIdentifier", id=_sid(s.id) + "UnderSlabInsulation")
            lay = _e(ui, "Layer")
            _e(lay, "NominalRValue", _num(float(asm.get("under_r_ip", 0.0)), 1))
            if asm.get("under_full"):
                _e(lay, "InsulationSpansEntireSlab", "true")
            else:
                _e(lay, "InsulationWidth", _num(float(asm.get("under_width_ft", 0.0)), 2))
            sx = _e(el, "extension")
            _e(sx, "CarpetFraction", _num(float(asm.get("carpet_fraction", 0.0)), 2))
            _e(sx, "CarpetRValue", _num(float(asm.get("carpet_r_ip", 0.0)), 2))

    wins = [s for s in surfaces if s.kind == "window"]
    if wins:
        we = _e(enc, "Windows")
        for s in wins:
            spec = b.fenestration[s.product]
            el = _e(we, "Window")
            _e(el, "SystemIdentifier", id=_sid(s.id))
            _e(el, "Area", _num(m2_to_ft2(s.area), 2))
            _e(el, "Azimuth", int(round(s.azimuth)) % 360)
            _e(el, "UFactor", _num(s.u_si / 5.678263, 3))
            _e(el, "SHGC", _num(max(0.01, s.shgc or spec.get("shgc", 0.3)), 3))
            if spec.get("interior_shading"):
                sh = _e(el, "InteriorShading")
                _e(sh, "SystemIdentifier", id=_sid(s.id) + "InteriorShading")
                _e(sh, "Type", spec["interior_shading"])
            _e(el, "AttachedToWall", idref=_sid(s.parent))
    skys = [s for s in surfaces if s.kind == "skylight"]
    if skys:
        ke = _e(enc, "Skylights")
        for s in skys:
            el = _e(ke, "Skylight")
            _e(el, "SystemIdentifier", id=_sid(s.id))
            _e(el, "Area", _num(m2_to_ft2(s.area), 2))
            host = by_id[s.parent]
            _e(el, "Azimuth", int(round(host.azimuth or 180)) % 360)
            _e(el, "UFactor", _num(s.u_si / 5.678263, 3))
            _e(el, "SHGC", _num(max(0.01, s.shgc or 0.3), 3))
            _e(el, "AttachedToRoof", idref=_sid(s.parent))
    doors = [s for s in surfaces if s.kind == "door" and b.room(s.room).conditioned]
    if doors:
        de = _e(enc, "Doors")
        for s in doors:
            el = _e(de, "Door")
            _e(el, "SystemIdentifier", id=_sid(s.id))
            _e(el, "AttachedToWall", idref=_sid(s.parent))
            _e(el, "Area", _num(m2_to_ft2(s.area), 2))
            _e(el, "Azimuth", int(round(s.azimuth)) % 360)
            _e(el, "RValue", _num(5.678263 / s.u_si, 2))

    # ---- systems
    sysel = _e(det, "Systems")
    hv = _e(sysel, "HVAC")
    plant = _e(hv, "HVACPlant")
    hvac = raw.get("hvac", {})
    ducted = hvac.get("distribution", "ducted") == "ducted"
    prim = _e(plant, "PrimarySystems")
    _e(prim, "PrimaryHeatingSystem", idref="HeatingSystem1")
    _e(prim, "PrimaryCoolingSystem", idref="CoolingSystem1")
    h = _e(plant, "HeatingSystem")
    _e(h, "SystemIdentifier", id="HeatingSystem1")
    _e(h, "AttachedToZone", idref="ConditionedZone")
    if ducted:
        _e(h, "DistributionSystem", idref="HVACDistribution1")
        _e(_e(h, "HeatingSystemType"), "Furnace")
        _e(h, "HeatingSystemFuel", "natural gas")
        eff = _e(h, "AnnualHeatingEfficiency")
        _e(eff, "Units", "AFUE")
        _e(eff, "Value", "0.95")
    else:
        _e(_e(h, "HeatingSystemType"), "ElectricResistance")
        _e(h, "HeatingSystemFuel", "electricity")
        eff = _e(h, "AnnualHeatingEfficiency")
        _e(eff, "Units", "Percent")
        _e(eff, "Value", "1.0")
    _e(h, "FractionHeatLoadServed", "1.0")
    c = _e(plant, "CoolingSystem")
    _e(c, "SystemIdentifier", id="CoolingSystem1")
    _e(c, "AttachedToZone", idref="ConditionedZone")
    if ducted:
        _e(c, "DistributionSystem", idref="HVACDistribution1")
        _e(c, "CoolingSystemType", "central air conditioner")
    else:
        _e(c, "CoolingSystemType", "room air conditioner")
    _e(c, "CoolingSystemFuel", "electricity")
    if ducted:
        _e(c, "CompressorType", "single stage")
    _e(c, "FractionCoolLoadServed", "1.0")
    ceff = _e(c, "AnnualCoolingEfficiency")
    if ducted:
        _e(ceff, "Units", "SEER2")
        _e(ceff, "Value", "14.3")
    else:
        _e(ceff, "Units", "CEER")
        _e(ceff, "Value", "10.0")
    ctl = _e(hv, "HVACControl")
    _e(ctl, "SystemIdentifier", id="HVACControl1")
    _e(ctl, "SetpointTempHeatingSeason", _num(c_to_f(design["indoor_heating_c"]), 1))
    _e(ctl, "SetpointTempCoolingSeason", _num(c_to_f(design["indoor_cooling_c"]), 1))
    if ducted:
        dist = _e(hv, "HVACDistribution")
        _e(dist, "SystemIdentifier", id="HVACDistribution1")
        ad = _e(_e(dist, "DistributionSystemType"), "AirDistribution")
        _e(ad, "AirDistributionType", "regular velocity")
        ducts = hvac.get("ducts", {})
        loc_map = {"attic": attic_loc, "crawlspace": crawl_loc, "garage": "garage", "conditioned": "conditioned space",
                   "basement": "basement - conditioned", "basement_unconditioned": "basement - unconditioned",
                   "outside": "outside"}
        dloc = loc_map.get(ducts.get("location", "conditioned"), "conditioned space")
        # leakage "to outside": none by default for ducts inside the conditioned space; otherwise the documented
        # default (listed in the report by design.resolve) unless the user gave a value
        leak = ducts.get("leakage_cfm25") or (
            {"supply": 0.0, "return": 0.0} if dloc == "conditioned space"
            else {"supply": 0.04, "return": 0.04, "fraction_of_cfa": True})
        for dt in ("supply", "return"):
            dlm = _e(ad, "DuctLeakageMeasurement")
            _e(dlm, "DuctType", dt)
            dl = _e(dlm, "DuctLeakage")
            val = leak.get(dt, 0.0)
            if leak.get("fraction_of_cfa"):
                val = val * m2_to_ft2(cfa)  # CFM25 per ft2 of CFA
            _e(dl, "Units", "CFM25")
            _e(dl, "Value", _num(float(val), 1))
            _e(dl, "TotalOrToOutside", "to outside")
        for i, dt in enumerate(("supply", "return")):
            d = _e(ad, "Ducts")
            _e(d, "SystemIdentifier", id=f"Ducts{i + 1}")
            _e(d, "DuctType", dt)
            _e(d, "DuctInsulationRValue", _num(float(ducts.get(f"{dt}_r_ip", 6.0 if dloc != "conditioned space" else 0.0)), 1))
            _e(d, "DuctLocation", dloc)
            _e(d, "FractionDuctArea", "1.0")
        _e(dist, "ConditionedFloorAreaServed", _num(m2_to_ft2(cfa), 1))

    vent = raw.get("ventilation", {})
    vtype = vent.get("type", "none")
    if vtype != "none":
        fan_type = {"exhaust": "exhaust only", "supply": "supply only", "balanced": "balanced",
                    "hrv": "heat recovery ventilator", "erv": "energy recovery ventilator"}[vtype]
        mv = _e(_e(_e(sysel, "MechanicalVentilation"), "VentilationFans"), "VentilationFan")
        _e(mv, "SystemIdentifier", id="VentilationFan1")
        _e(mv, "FanType", fan_type)
        cfm = float(vent["cfm"]) if "cfm" in vent else float(vent["lps"]) * 2.118880
        _e(mv, "RatedFlowRate", _num(cfm, 1))
        _e(mv, "HoursInOperation", _num(float(vent.get("hours", 24)), 1))
        _e(mv, "UsedForWholeBuildingVentilation", "true")
        if vtype == "erv":
            _e(mv, "TotalRecoveryEfficiency", _num(float(vent.get("tre", 0.5)), 2))
        if vtype in ("hrv", "erv"):
            if vent.get("asre") is not None:  # adjusted/apparent sensible recovery efficiency, used as is
                _e(mv, "AdjustedSensibleRecoveryEfficiency", _num(float(vent["asre"]), 2))
            else:  # rated SRE (HVI / CSA C439), converted by the engine to an apparent effectiveness
                _e(mv, "SensibleRecoveryEfficiency", _num(float(vent.get("sre", 0.65)), 2))

    # Minimal appliances/plug loads required by the OpenStudio-HPXML validator. They do not affect
    # Manual J design loads (internal gains come from ManualJInputs above).
    apl = _e(det, "Appliances")
    _e(_e(apl, "Refrigerator"), "SystemIdentifier", id="Refrigerator1")
    ml = _e(_e(det, "MiscLoads"), "PlugLoad")
    _e(ml, "SystemIdentifier", id="PlugLoad1")
    _e(ml, "PlugLoadType", "other")

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    return {"hpxml": str(out_path), "ids": {_sid(s.id): s.id for s in surfaces},
            "space_ids": {_sid(r.id): r.id for r in cond_rooms}}


def run(xml_path: Path, out_dir: Path) -> dict:
    os_exe, osh = tools.openstudio_exe(), tools.oshpxml_root()
    if not (os_exe and osh):
        raise SystemExit("OpenStudio / OpenStudio-HPXML not installed: run `uv run scripts/hvacload.py setup`")
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(os_exe), str(osh / "workflow" / "run_simulation.rb"), "-x", str(xml_path), "-o", str(out_dir),
           "--skip-simulation", "--output-format", "json"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    log = (out_dir / "run" / "run.log")
    res = out_dir / "run" / "results_design_load_details.json"
    ok = res.exists()
    return {"ok": ok, "cmd": " ".join(cmd), "returncode": p.returncode,
            "stdout_tail": p.stdout[-3000:], "stderr_tail": p.stderr[-3000:],
            "log": log.read_text(encoding="utf-8", errors="replace")[-6000:] if log.exists() else "",
            "results": str(res) if ok else None, "annual": str(out_dir / "run" / "results_annual.json")}


def window_shading(run_dir: Path) -> dict:
    """Summer shading coefficients (interior x exterior) that OpenStudio-HPXML defaulted for each window.
    Read back from the defaulted run/in.xml so the cross-check uses the same assumption."""
    p = Path(run_dir) / "run" / "in.xml"
    if not p.exists():
        return {}
    ns = {"h": NS}
    out = {}
    for w in ET.parse(p).getroot().iterfind(".//h:Window", ns):
        wid = w.find("h:SystemIdentifier", ns).get("id")
        f = 1.0
        for tag in ("InteriorShading", "ExteriorShading"):
            el = w.find(f"h:{tag}/h:SummerShadingCoefficient", ns)
            if el is not None and el.text:
                f *= float(el.text)
        out[wid] = f
    return out


def parse(results_path: str, idmap: dict) -> dict:
    j = json.loads(Path(results_path).read_text(encoding="utf-8"))
    ids, spaces = idmap["ids"], idmap["space_ids"]
    out = {"method": "ACCA Manual J (OpenStudio-HPXML)", "rooms": {}, "total": {}, "components": {}}
    for key, block in j.items():
        m = re.match(r"Report: [^:]+: (.+): Loads$", key)
        if not m:
            continue
        name = m.group(1)
        tot = block.get("Total", {})
        comps = []
        for ck, cv in block.items():
            if ck == "Total":
                continue
            cat, _, sid = ck.partition(": ")
            comps.append({"category": cat, "surface": ids.get(sid, sid) if sid else None,
                          "area_ft2": cv.get("Area (ft^2)"),
                          "heating_w": (cv.get("Heating (Btuh)") or 0) * W_PER_BTUH,
                          "cooling_sensible_w": (cv.get("Cooling Sensible (Btuh)") or 0) * W_PER_BTUH,
                          "cooling_latent_w": (cv.get("Cooling Latent (Btuh)") or 0) * W_PER_BTUH})
        rec = {"heating_w": (tot.get("Heating (Btuh)") or 0) * W_PER_BTUH,
               "cooling_sensible_w": (tot.get("Cooling Sensible (Btuh)") or 0) * W_PER_BTUH,
               "cooling_latent_w": (tot.get("Cooling Latent (Btuh)") or 0) * W_PER_BTUH,
               "components": comps}
        if name in spaces:
            out["rooms"][spaces[name]] = rec
        elif name == "ConditionedZone" or name == "Loads" or "Zone" in name:
            out["total"] = rec
    if not out["total"] and "Report: MyBuilding: Loads" in j:
        blk = j["Report: MyBuilding: Loads"]["Total"]
        out["total"] = {"heating_w": blk.get("Heating (Btuh)", 0) * W_PER_BTUH,
                        "cooling_sensible_w": blk.get("Cooling Sensible (Btuh)", 0) * W_PER_BTUH,
                        "cooling_latent_w": blk.get("Cooling Latent (Btuh)", 0) * W_PER_BTUH}
    return out
