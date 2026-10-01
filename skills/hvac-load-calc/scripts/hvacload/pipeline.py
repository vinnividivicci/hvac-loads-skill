"""Project-level commands: init, weather, check, run, selftest."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from . import design as design_mod
from . import eplus, geometry, hpxml, model, pdfkit, qa, report, results, tools, viewer, weather
from .units import W_PER_BTUH

STARTER = {
    "schema": model.SCHEMA,
    "units": "ft",
    "project": {"name": "", "address": "", "jurisdiction": "", "north_arrow_deg": 0, "units_system": "IP"},
    "source": {"pdf": "", "kind": "", "stated": {}, "dimension_chains": [], "calibrations": []},
    "levels": [],
    "foundation": {"type": None},
    "attic": {"type": "vented", "roof_pitch": None},
    "rooms": [],
    "openings": [],
    "assemblies": {},
    "surface_assemblies": {},
    "fenestration": {},
    "airtightness": {},
    "ventilation": {"type": "none"},
    "hvac": {"distribution": "ducted"},
    "internal_gains": {},
    "design": {},
    "assumptions": [],
}


def bpath(project: str | Path) -> Path:
    p = Path(project).resolve()
    return p / "building.json" if p.is_dir() else p


def init(project: Path, pdf: Path | None, name: str) -> dict:
    project.mkdir(parents=True, exist_ok=True)
    (project / "work").mkdir(exist_ok=True)
    out = {"project": str(project)}
    starter = json.loads(json.dumps(STARTER))
    starter["project"]["name"] = name or project.name
    if pdf:
        (project / "plans").mkdir(exist_ok=True)
        dest = project / "plans" / pdf.name
        if pdf.resolve() != dest.resolve():
            shutil.copy2(pdf, dest)
        inf = pdfkit.info(str(dest))
        (project / "work" / "pdf_info.json").write_text(json.dumps(inf, indent=2), encoding="utf-8")
        pages = []
        for pg in inf["pages"]:
            png = project / "work" / "pages" / f"p{pg['page']}.png"
            pdfkit.render(str(dest), pg["page"], str(png), dpi=100)
            pages.append({"page": pg["page"], "kind": pg["kind"], "png": str(png),
                          "main_image_dpi": pg.get("main_image_dpi"), "scale_notes": pg["scale_notes_in_text_layer"]})
        starter["source"]["pdf"] = f"plans/{pdf.name}"
        starter["source"]["kind"] = inf["overall"]
        imperial = sum(len(p["dimension_strings_in_text_layer"]) for p in inf["pages"])
        metric = sum(len(p.get("metric_mm_like_numbers", [])) for p in inf["pages"])
        if metric > 3 * max(imperial, 1):
            starter["units"] = "mm"
            starter["project"]["units_system"] = "SI"
        out["units_guess"] = f"{starter['units']} (imperial-looking strings: {imperial}, metric-looking numbers: " \
                             f"{metric}); check on the drawings"
        out.update(pdf_kind=inf["overall"], pages=pages, warning=inf.get("warning"))
    b = project / "building.json"
    if not b.exists():
        b.write_text(json.dumps(starter, indent=2), encoding="utf-8")
        out["building_json"] = str(b) + " (starter written)"
    else:
        out["building_json"] = str(b) + " (exists, not overwritten)"
    return out


def weather_cmd(a) -> dict:
    if a.url is None:
        st = weather.find(a.lat, a.lon, a.country, a.n)
        return {"stations": [{k: s[k] for k in ("station", "state", "wmo", "distance_km", "elevation_m", "url")}
                             for s in st],
                "next": "pick one and run: weather --url <url> --project <dir> --write"}
    files = weather.download(a.url)
    summ = weather.design_summary(files)
    res = {"design_conditions": {k: v for k, v in summ.items() if k not in ("epw", "ddy")}, "files": files}
    if a.project and a.write:
        bp = bpath(a.project)
        raw = json.loads(bp.read_text(encoding="utf-8"))
        loc = summ.get("location", {})
        ed = summ.get("ashrae_edition", "")
        station = f"{loc.get('city', '')} (WMO {loc.get('wmo', '')})"
        h = summ.get(f"heating_{a.heating}")
        c = summ.get(f"cooling_{a.cooling}")
        if not h or not c:
            raise SystemExit(f"design day heating_{a.heating} / cooling_{a.cooling} not found in the DDY")
        d = raw.get("design") or {}
        notes = []
        prev = (d.get("weather") or {}).get("station")
        if prev and prev != station:
            notes.append(f"station changed from {prev} to {station}: every station-derived value was refreshed; "
                         "re-check indoor setpoints, label and any overrides")
        for key in ("heating_outdoor", "cooling_outdoor", "cooling_wetbulb"):  # never keep another site's values
            d.pop(key, None)
        d["label"] = a.label or f"ASHRAE {ed} {a.heating}% heating / {a.cooling}% cooling, {station}"
        d["heating_outdoor"] = {"value": h["db_c"], "unit": "C",
                                "src": f"ASHRAE {ed} Fundamentals ch.14 {a.heating}% heating DB, {station}, via OneBuilding DDY"}
        d["cooling_outdoor"] = {"value": c["db_c"], "unit": "C",
                                "src": f"ASHRAE {ed} {a.cooling}% cooling DB, {station}, via OneBuilding DDY"}
        d["cooling_wetbulb"] = {"value": c["humidity_value"], "unit": "C",
                                "src": f"ASHRAE {ed} {a.cooling}% mean coincident wet bulb, {station}"}
        d["daily_range"] = {"value": c["daily_range_c"], "unit": "C", "src": f"ASHRAE {ed} mean daily range, {station}"}
        d["weather"] = {"epw": files["epw"], "ddy": files["ddy"], "station": station, "source_url": files["source_url"]}
        if a.lat is not None and a.lon is not None:  # the site, not the station
            d["lat"], d["lon"] = a.lat, a.lon
            d["station_distance_km"] = round(weather._haversine_km((a.lat, a.lon), (loc["lat"], loc["lon"])), 1)
        elif d.get("lat") is None:
            d["lat"], d["lon"] = loc.get("lat"), loc.get("lon")
            notes.append("site coordinates unknown: pass --lat/--lon of the site with --url (station coordinates used)")
        d["station_elevation_m"] = loc.get("elevation_m", 0.0)
        if a.site_elevation_m is not None:
            d["elevation_m"] = a.site_elevation_m
            if abs(a.site_elevation_m - d["station_elevation_m"]) > 100:
                notes.append(f"site is {a.site_elevation_m - d['station_elevation_m']:+.0f} m from the station elevation: "
                             "design temperatures may need adjusting; consider a closer station or local data")
        else:
            d["elevation_m"] = d["station_elevation_m"]
        d["cooling_day"] = {"month": c["month"], "day": c["day"], "taub": c.get("taub"), "taud": c.get("taud"),
                            "wind_ms": c.get("wind_ms")}
        if summ.get("ashrae_climate_zone"):
            d["climate_zone_iecc"] = summ["ashrae_climate_zone"]
        else:
            d.pop("climate_zone_iecc", None)
            notes.append("no ASHRAE climate zone in the STAT file: set design.climate_zone_iecc by hand")
        if d.get("station_distance_km", 0) > 25:
            notes.append(f"station is {d['station_distance_km']} km from the site: tell the user, consider a closer one")
        for key in ("indoor_heating", "indoor_cooling"):
            if key in d and getattr(a, f"{key}_c") is None:
                notes.append(f"kept existing design.{key} = {d[key]}")
        # explicit overrides (e.g. NBC Appendix C values or the engineer's own data)
        for key, val, s in (("heating_outdoor", a.heating_c, a.heating_src), ("cooling_outdoor", a.cooling_c, a.cooling_src),
                            ("cooling_wetbulb", a.wetbulb_c, a.wetbulb_src)):
            if val is not None:
                if not s:
                    raise SystemExit(f"--{key.split('_')[0]}-src is required with an override value")
                d[key] = {"value": val, "unit": "C", "src": s}
        if a.indoor_heating_c is not None:
            d["indoor_heating"] = {"value": a.indoor_heating_c, "unit": "C", "src": a.indoor_src or "user"}
        if a.indoor_cooling_c is not None:
            d["indoor_cooling"] = {"value": a.indoor_cooling_c, "unit": "C", "src": a.indoor_src or "user"}
        raw["design"] = d
        bp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        res["written"] = str(bp)
        res["design"] = d
        res["notes"] = notes
        res["comparison_c"] = {
            "heating_used": d["heating_outdoor"]["value"], "ashrae_99.6": (summ.get("heating_99.6") or {}).get("db_c"),
            "ashrae_99": (summ.get("heating_99") or {}).get("db_c"),
            "cooling_used": d["cooling_outdoor"]["value"], "ashrae_1": (summ.get("cooling_1") or {}).get("db_c"),
            "wetbulb_used": d["cooling_wetbulb"]["value"], "ashrae_1_mcwb": (summ.get("cooling_1") or {}).get("humidity_value"),
            "note": "show this spread to the user; a design wet bulb that is not coincident (e.g. NBC July 2.5% wet) "
                    "overstates latent loads compared with the ASHRAE mean coincident wet bulb"}
    return res


def check(project, geometry_only: bool = False) -> tuple[model.Building, dict, dict]:
    b = model.load(bpath(project), geometry_only=geometry_only)
    geo = geometry.build(b)
    rep = qa.check(b, geo)
    return b, geo, rep


def run(project: Path, lang: str = "en", with_eplus: bool = True, pdf: bool = False, force: bool = False) -> dict:
    bp = bpath(project)
    proj_dir = bp.parent
    b, geo, rep = check(bp)
    if rep["errors"] and not force:
        return {"ok": False, "stage": "qa", "errors": rep["errors"], "warnings": rep["warnings"],
                "hint": "fix the takeoff (or rerun with --force after confirming with the user)"}
    d = design_mod.resolve(b, geo)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = proj_dir / "runs" / stamp
    out_dir = proj_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    idmap = hpxml.write(b, geo, d, run_dir / "manualj" / "in.xml")
    r1 = hpxml.run(Path(idmap["hpxml"]), run_dir / "manualj")
    if not r1["ok"]:
        errs = [ln for ln in r1["log"].splitlines() if ln.startswith("Error")]
        return {"ok": False, "stage": "manualj", "errors": errs or [r1["stdout_tail"], r1["stderr_tail"]],
                "hpxml": idmap["hpxml"]}
    mj = hpxml.parse(r1["results"], idmap)
    ep, ep_meta, r2 = None, {}, None
    if with_eplus:
        ep_meta = eplus.write(b, geo, d, run_dir / "energyplus" / "in.idf",
                              shading=hpxml.window_shading(run_dir / "manualj"))
        r2 = eplus.run(Path(ep_meta["idf"]), run_dir / "energyplus")
        for gw in r2.get("geometry_warnings", []):
            ep_meta.setdefault("notes", []).append(f"EnergyPlus geometry warning: {gw}")
        if r2["ok"]:
            ep = eplus.parse(r2["sql"], geo)
            ours = {s.id.upper(): s.azimuth for s in geo["surfaces"] if s.kind == "wall" and s.azimuth is not None}
            mism = [k for k, v in ep["eplus_azimuths"].items()
                    if k in ours and abs(((ours[k] - v) + 180) % 360 - 180) > 1.0]
            if mism:
                ep_meta.setdefault("notes", []).append(f"ORIENTATION MISMATCH on {len(mism)} surfaces: {mism[:5]}")
        else:
            ep_meta.setdefault("notes", []).append("EnergyPlus failed: " + "; ".join(r2["severe"][:5]))
    cond = [r.id for r in b.rooms if r.conditioned]
    comp = results.compare(mj, ep, cond, results.ground_ids(geo), results.above_grade_foundation_ua(geo),
                           d["indoor_heating_c"] - d["heating_c"])
    rows = results.room_table(b, geo, mj, d)
    san = results.sanity(b, geo, mj)
    results.takeoff_csv(b, geo, d, out_dir / "takeoff.csv")
    viewer.build(b, geo, out_dir / "model3d.html", mj, lang=lang)
    digest = hashlib.sha256(bp.read_bytes()).hexdigest()[:16]
    doc = tools.doctor()
    meta = {"building.json sha256": digest, "run folder": str(run_dir), "HPXML": idmap["hpxml"],
            "EnergyPlus IDF": ep_meta.get("idf", "not run"), "takeoff": str(out_dir / "takeoff.csv"),
            "3D model": str(out_dir / "model3d.html"),
            "engines": f"OpenStudio {doc.get('openstudio_version')} / {doc.get('energyplus_version')} / "
                       f"OpenStudio-HPXML {doc.get('oshpxml_version')}",
            "hvacload": __import__("hvacload").__version__}
    rpt = report.build(b, geo, d, mj, comp, ep_meta, rep, rows, san, meta, out_dir / f"report_{lang}.html", lang)
    pdf_path = report.to_pdf(Path(rpt), out_dir / f"report_{lang}.pdf") if pdf else None
    summary = {
        "ok": True, "method": mj["method"], "design_label": d.get("label"),
        "heating_w": round(mj["total"].get("heating_w", 0)), "heating_btuh": round(mj["total"].get("heating_w", 0) / W_PER_BTUH),
        "cooling_sensible_w": round(mj["total"].get("cooling_sensible_w", 0)),
        "cooling_sensible_btuh": round(mj["total"].get("cooling_sensible_w", 0) / W_PER_BTUH),
        "cooling_latent_btuh": round(mj["total"].get("cooling_latent_w", 0) / W_PER_BTUH),
        "rooms": {r["room"]: {"heating_btuh": round(r["heating_btuh"]), "cooling_sensible_btuh": round(r["cooling_sensible_btuh"]),
                              "heating_w": round(r["heating_w"]), "cooling_sensible_w": round(r["cooling_sensible_w"])}
                  for r in rows},
        "crosscheck": {"available": comp.get("available"), "delta_heating_pct": None if comp.get("delta_heating") is None
                       else round(100 * comp["delta_heating"], 1), "delta_cooling_pct": None if comp.get("delta_cooling") is None
                       else round(100 * comp["delta_cooling"], 1), "flags": comp.get("flags", [])},
        "qa_warnings": rep["warnings"], "qa_errors": rep["errors"], "defaults_applied": d["defaults_applied"],
        "outputs": {"report": rpt, "pdf": pdf_path, "model3d": str(out_dir / "model3d.html"),
                    "takeoff": str(out_dir / "takeoff.csv"), "results": str(out_dir / "results.json"),
                    "run_dir": str(run_dir)},
    }
    (out_dir / "results.json").write_text(json.dumps({"summary": summary, "manualj": mj, "energyplus": ep,
                                                      "comparison": comp, "rooms": rows, "sanity": san,
                                                      "design": {k: v for k, v in d.items() if k != "internal_gains"},
                                                      "internal_gains": d["internal_gains"]}, indent=2, default=str),
                                          encoding="utf-8")
    return summary


def selftest() -> dict:
    """Verify the engine install against OpenStudio-HPXML's own ACCA example and stored result."""
    import csv

    osh = tools.oshpxml_root()
    if not osh:
        return {"ok": False, "error": "OpenStudio-HPXML not installed (run setup)"}
    xml = osh / "workflow" / "tests" / "ACCA_Examples" / "Bob_Ross_Residence.xml"
    base = osh / "workflow" / "tests" / "base_results" / "results_acca_hvac.csv"
    expected = expected_c = None
    with open(base, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["HPXML"] == "Bob_Ross_Residence.xml":
                expected = float(row["HVAC Design Load: Heating: Total (Btu/h)"])
                expected_c = float(row["HVAC Design Load: Cooling Sensible: Total (Btu/h)"])
    out = tools.home() / "selftest"
    r = hpxml.run(xml, out)
    if not r["ok"]:
        return {"ok": False, "error": r["log"][-1500:]}
    j = json.loads(Path(r["results"]).read_text())
    key = next((k for k in j if k.endswith("Conditioned: Loads")), "Report: MyBuilding: Loads")
    got = j.get(key, {}).get("Total", {}).get("Heating (Btuh)")
    got_c = j.get(key, {}).get("Total", {}).get("Cooling Sensible (Btuh)")
    ok = (expected is not None and got is not None and abs(got - expected) <= max(1.0, 0.001 * expected)
          and expected_c is not None and got_c is not None and abs(got_c - expected_c) <= max(1.0, 0.001 * expected_c))
    return {"ok": ok, "case": "ACCA Bob Ross Residence (OpenStudio-HPXML regression file)",
            "heating_btuh_expected": expected, "heating_btuh_got": got,
            "cooling_sensible_btuh_expected": expected_c, "cooling_sensible_btuh_got": got_c,
            "energyplus": tools.doctor().get("energyplus_version")}


def clone(src: Path, dst: Path, keep_design: bool = False) -> dict:
    """Copy a project's building.json to a new project folder for a what-if run."""
    sp = bpath(src)
    raw = json.loads(sp.read_text(encoding="utf-8"))
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "work").mkdir(exist_ok=True)
    pdf = raw.get("source", {}).get("pdf")
    if pdf and not Path(pdf).is_absolute():
        raw["source"]["pdf"] = str((sp.parent / pdf).resolve())
    reset = []
    if not keep_design:
        raw["design"] = {}
        reset.append("design (run `weather ... --write` for the new site)")
    raw.setdefault("assumptions", []).append({"item": "what-if", "value": f"cloned from {sp.parent.name}",
                                              "basis": "hvacload clone"})
    out = dst / "building.json"
    if out.exists():
        raise SystemExit(f"{out} exists; choose an empty folder")
    out.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return {"building_json": str(out), "reset": reset,
            "next": "edit the fields that change (site, assemblies, airtightness, ventilation, ducts, report "
                    "language), ask the CSA F280 question if the new site is in Canada, then check and run"}
