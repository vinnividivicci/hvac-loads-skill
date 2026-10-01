# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy>=1.26",
#   "shapely>=2.0",
#   "pdfplumber>=0.11",
#   "pypdfium2>=4.30",
#   "pillow>=10",
#   "openpyxl>=3.1",
# ]
# ///
"""hvacload: command-line helpers for the hvac-load-calc skill.

Run with uv (dependencies install automatically):
    uv run scripts/hvacload.py <command> [options]
Run any command with -h for its options.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _stream in (sys.stdout, sys.stderr):  # accents in names and help text on Windows consoles
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def _cmd_setup(a):
    from hvacload import tools

    tools.print_json(tools.setup(force=a.force))


def _cmd_doctor(a):
    from hvacload import tools

    rep = tools.doctor()
    tools.print_json(rep)
    sys.exit(0 if rep["ready"] else 1)


def _pts(s: str):
    return [tuple(float(v) for v in p.split(",")) for p in s.split(";") if p.strip()]


def _cmd_pdf_info(a):
    from hvacload import pdfkit

    print(pdfkit.dump(pdfkit.info(a.pdf)))


def _cmd_pdf_render(a):
    from hvacload import pdfkit

    crop = tuple(float(v) for v in a.crop.split(",")) if a.crop else None
    print(pdfkit.dump(pdfkit.render(a.pdf, a.page, a.out, dpi=a.dpi, crop=crop, grid=a.grid)))


def _cmd_pdf_vectors(a):
    from hvacload import pdfkit

    res = pdfkit.vectors(a.pdf, a.page, min_len=a.min_len)
    Path(a.out).write_text(pdfkit.dump(res), encoding="utf-8")
    print(pdfkit.dump({k: v for k, v in res.items() if k not in ("lines", "words", "curves")} | {"written": a.out}))


def _cmd_pdf_measure(a):
    from hvacload import pdfkit

    (p1, p2) = _pts(a.calib_points)
    s = pdfkit.calibrate(p1, p2, a.calib_length, a.units)
    metres_per_pt = s * (0.3048 if a.units == "ft" else 1.0)
    out = {"units_per_pt": s, "units": a.units,
           "implied_scale": f"1:{metres_per_pt / (0.0254 / 72):.0f} on this page (compare with any printed scale note)",
           "check": "calibrate on the LONGEST dimension string; verify with a second one in the other direction"}
    if a.origin:
        origin = _pts(a.origin)[0]
        out["origin_pt"] = origin
        out["points"] = [{"pt": p, "plan": [round(c, 3) for c in pdfkit.to_plan(p, origin, s)]}
                         for p in _pts(a.points or "")]
    if a.lengths:
        segs = _pts(a.lengths)
        out["lengths"] = [round(math.dist(segs[i], segs[i + 1]) * s, 3) for i in range(0, len(segs) - 1, 2)]
    ok = True
    if a.verify_points and a.verify_length:
        v1, v2 = _pts(a.verify_points)
        s2 = pdfkit.calibrate(v1, v2, a.verify_length, a.units)
        diff = 100 * (s2 - s) / s
        ok = abs(diff) <= 1.0
        out["verify"] = {"units_per_pt": s2, "diff_pct": round(diff, 2), "ok": ok,
                         "note": "within 1 % is expected; more means a distorted scan or a misread dimension"}
    else:
        out["verify"] = "not checked: pass --verify-points/--verify-length (a dimension in the other axis)"
    print(json.dumps(out, indent=2))
    sys.exit(0 if ok else 1)


def _cmd_overlay(a):
    from hvacload import pdfkit

    bpath = _building_path(a.project)
    raw = json.loads(bpath.read_text(encoding="utf-8"))
    cals = raw.get("source", {}).get("calibrations") or []
    if not cals:
        raise SystemExit("building.json source.calibrations is empty: add {page, origin_pt, units_per_pt, level}")
    pdf = a.pdf or raw.get("source", {}).get("pdf")
    pdf = str((bpath.parent / pdf).resolve()) if pdf and not Path(pdf).is_absolute() else pdf
    outs = []
    for cal in cals:
        out = bpath.parent / "work" / f"overlay_p{cal['page']}_{cal.get('level', 'all')}.png"
        crop = tuple(float(v) for v in a.crop.split(",")) if a.crop else None
        outs.append(pdfkit.overlay(pdf, cal["page"], raw, cal, str(out), dpi=a.dpi, crop=crop))
    print(json.dumps(outs, indent=2))


def _cmd_pdf_profile(a):
    from hvacload import pdfkit

    crop = tuple(float(v) for v in a.crop.split(","))
    print(pdfkit.dump(pdfkit.profile(a.pdf, a.page, crop, a.axis, dpi=a.dpi, min_fraction=a.min_fraction)))


def _cmd_preview_png(a):
    from hvacload import report

    import re as _re

    html = Path(a.html) if a.html.endswith(".html") else _building_path(a.html).parent / "work" / "model3d_preview.html"
    m = _re.search(r'"levels":(\[.*?\])', html.read_text(encoding="utf-8"))
    level_ids = [lv["id"] for lv in json.loads(m.group(1))] if m else []
    if a.level:
        level_ids = [a.level]
    mode = f"&mode={a.mode}" if a.mode else ""
    views = [("iso", "view=iso" + mode)] + [(f"top_{lid}", f"view=top&roof=0&level={lid}" + mode) for lid in level_ids]
    shots = []
    for name, q in views:
        shots.append(report.screenshot(html, html.parent / f"{html.stem}_{name}.png", q))
    print(json.dumps({"png": shots, "note": "look at these, then show them to the user (or have them open the HTML)"
                      if all(shots) else "no headless Edge/Chrome found, or rendering failed"}, indent=2))


def _cmd_clone(a):
    from hvacload import pipeline

    print(json.dumps(pipeline.clone(Path(a.src), Path(a.dst), keep_design=a.keep_design), indent=2))


def _cmd_nbc(a):
    from hvacload import codes

    print(json.dumps(codes.lookup(a.place, a.pdf), indent=2, ensure_ascii=False))


def _building_path(p: str) -> Path:
    path = Path(p)
    return path / "building.json" if path.is_dir() else path


def _cmd_init(a):
    from hvacload import pipeline

    print(json.dumps(pipeline.init(Path(a.project), Path(a.pdf) if a.pdf else None, a.name or ""), indent=2))


def _cmd_weather(a):
    from hvacload import pipeline

    print(json.dumps(pipeline.weather_cmd(a), indent=2, default=str))


def _cmd_check(a):
    from hvacload import pipeline, viewer
    from hvacload.model import ModelError

    try:
        b, geo, rep = pipeline.check(a.project, geometry_only=a.geometry_only)
    except ModelError as e:
        print(json.dumps({"ok": False, "stage": "model", "errors": e.errors}, indent=2))
        sys.exit(2)
    work = _building_path(a.project).parent / "work"
    html = viewer.build(b, geo, work / "model3d_preview.html",
                        subtitle="PREVIEW before load calculation - confirm the geometry with the user")
    if a.geometry_only:
        rep["note"] = "geometry-only check: thermal inputs not validated yet; run `check` again before `run`"
    rep["preview_3d"] = html
    rep.pop("info", None) if a.brief else None
    print(json.dumps(rep, indent=2, default=str))
    sys.exit(0 if rep["ok"] else 1)


def _cmd_run(a):
    from hvacload import pipeline
    from hvacload.model import ModelError

    try:
        res = pipeline.run(Path(a.project), lang=a.lang, with_eplus=not a.no_eplus, pdf=a.pdf, force=a.force)
    except ModelError as e:
        res = {"ok": False, "stage": "model/design", "errors": e.errors}
    print(json.dumps(res, indent=2, default=str))
    sys.exit(0 if res.get("ok") else 1)


def _cmd_assembly(a):
    from hvacload import assembly

    print(json.dumps(assembly.effective(assembly.parse(a.layers), si=a.si), indent=2))


def _cmd_selftest(a):
    from hvacload import pipeline

    res = pipeline.selftest()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["ok"] else 1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="hvacload", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="download the pinned engines (OpenStudio/EnergyPlus, OpenStudio-HPXML)")
    s.add_argument("--force", action="store_true", help="re-download even if present")
    s.set_defaults(fn=_cmd_setup)

    s = sub.add_parser("doctor", help="check that engines are installed; exit 1 if not")
    s.set_defaults(fn=_cmd_doctor)

    s = sub.add_parser("pdf-info", help="classify pages (vector/raster/mixed), list scale notes and dimension text")
    s.add_argument("pdf")
    s.set_defaults(fn=_cmd_pdf_info)

    s = sub.add_parser("pdf-render", help="render a page or crop to PNG, optionally with a labelled point grid")
    s.add_argument("pdf")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--out", required=True)
    s.add_argument("--dpi", type=int, default=150)
    s.add_argument("--crop", help="x0,y0,x1,y1 in page points (top-left origin)")
    s.add_argument("--grid", type=float, help="grid spacing in page points, labels are page coordinates")
    s.set_defaults(fn=_cmd_pdf_render)

    s = sub.add_parser("pdf-vectors", help="extract line work + positioned words from a vector page to JSON")
    s.add_argument("pdf")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--out", required=True)
    s.add_argument("--min-len", type=float, default=8.0, help="ignore lines shorter than this (points)")
    s.set_defaults(fn=_cmd_pdf_vectors)

    s = sub.add_parser("pdf-profile", help="locate straight dark lines (extension lines, wall faces) in a page crop")
    s.add_argument("pdf")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--crop", required=True, help="x0,y0,x1,y1 in page points: a narrow band across the feature")
    s.add_argument("--axis", default="x", choices=["x", "y"], help="x: vertical lines, y: horizontal lines")
    s.add_argument("--dpi", type=int, default=300)
    s.add_argument("--min-fraction", type=float, default=0.35, help="dark share of the band needed to count as a line")
    s.set_defaults(fn=_cmd_pdf_profile)

    s = sub.add_parser("pdf-measure", help="two-point scale calibration; convert page points to plan coordinates")
    s.add_argument("--calib-points", required=True, help='"x1,y1;x2,y2" page points at the ends of a dimension')
    s.add_argument("--calib-length", required=True, help="real length of that dimension, e.g. 48ft, 12'-6\", 14.6m")
    s.add_argument("--units", default="ft", choices=["ft", "m"])
    s.add_argument("--origin", help='"x,y" page point that becomes plan (0,0)')
    s.add_argument("--points", help='"x,y;x,y;..." page points to convert to plan coordinates')
    s.add_argument("--lengths", help='"x1,y1;x2,y2;x3,y3;x4,y4" pairs of page points to measure')
    s.add_argument("--verify-points", help='"x1,y1;x2,y2" ends of a dimension in the OTHER axis')
    s.add_argument("--verify-length", help="its printed length; exit 1 if the two scales differ by more than 1 %%")
    s.set_defaults(fn=_cmd_pdf_measure)

    s = sub.add_parser("assembly", help="effective R/U of a layered assembly (parallel path through framing)")
    s.add_argument("--layers", required=True,
                   help='e.g. "outside:0.17,siding:0.62,sheathing:0.62,studs:13|4.38@0.25,gypsum:0.45,inside:0.68"')
    s.add_argument("--si", action="store_true", help="layer values are RSI (m2K/W) instead of IP R")
    s.set_defaults(fn=_cmd_assembly)

    s = sub.add_parser("selftest", help="verify the engine install against OpenStudio-HPXML's ACCA regression case")
    s.set_defaults(fn=_cmd_selftest)

    s = sub.add_parser("init", help="create a project folder, copy + classify the PDF, render pages, write a starter building.json")
    s.add_argument("project")
    s.add_argument("--pdf")
    s.add_argument("--name")
    s.set_defaults(fn=_cmd_init)

    s = sub.add_parser("weather", help="find design-weather stations, or download one and write design conditions")
    s.add_argument("--lat", type=float, help="site latitude (also recorded with --url --write)")
    s.add_argument("--lon", type=float, help="site longitude")
    s.add_argument("--country", default="USA", help="USA or Canada")
    s.add_argument("--n", type=int, default=5)
    s.add_argument("--url", help="station zip URL from the list")
    s.add_argument("--project", help="project folder to update with --write")
    s.add_argument("--write", action="store_true", help="write the design block into building.json")
    s.add_argument("--heating", default="99", choices=["99", "99.6"], help="heating design percentile (Manual J: 99)")
    s.add_argument("--cooling", default="1", choices=["0.4", "1", "2"], help="cooling design percentile (Manual J: 1)")
    s.add_argument("--label")
    s.add_argument("--heating-c", type=float, help="override heating design temperature (C), e.g. NBC January 2.5%%")
    s.add_argument("--heating-src")
    s.add_argument("--cooling-c", type=float)
    s.add_argument("--cooling-src")
    s.add_argument("--wetbulb-c", type=float)
    s.add_argument("--wetbulb-src")
    s.add_argument("--indoor-heating-c", type=float, help="e.g. 22 for CSA F280 / NBC practice")
    s.add_argument("--indoor-cooling-c", type=float)
    s.add_argument("--indoor-src")
    s.add_argument("--site-elevation-m", type=float, help="site elevation (default: the station's)")
    s.set_defaults(fn=_cmd_weather)

    s = sub.add_parser("check", help="validate building.json, run takeoff QA gates, write a 3D preview")
    s.add_argument("project")
    s.add_argument("--brief", action="store_true", help="omit the detailed info block")
    s.add_argument("--geometry-only", action="store_true",
                   help="geometry QA before assemblies and windows are defined (the step-5 gate)")
    s.set_defaults(fn=_cmd_check)

    s = sub.add_parser("run", help="run Manual J (OpenStudio-HPXML) + EnergyPlus cross-check; write report, 3D, takeoff")
    s.add_argument("project")
    s.add_argument("--lang", default="en", choices=["en", "fr"])
    s.add_argument("--pdf", action="store_true", help="also print the report to PDF (needs Edge/Chrome)")
    s.add_argument("--no-eplus", action="store_true", help="skip the EnergyPlus cross-check")
    s.add_argument("--force", action="store_true", help="run despite QA errors (only after the user accepts them)")
    s.set_defaults(fn=_cmd_run)

    s = sub.add_parser("overlay", help="draw the model's rooms/openings over the plan page(s) for visual QA")
    s.add_argument("project", help="project folder or building.json")
    s.add_argument("--pdf", help="override source.pdf")
    s.add_argument("--dpi", type=int, default=200)
    s.add_argument("--crop", help="x0,y0,x1,y1 in page points (default: model extent + margin)")
    s.set_defaults(fn=_cmd_overlay)

    s = sub.add_parser("preview-png", help="render the 3D viewer to PNG (3D + top view) with headless Edge/Chrome")
    s.add_argument("html", help="project folder (uses work/model3d_preview.html) or an .html file (e.g. out/model3d.html)")
    s.add_argument("--level", help="only this level's top view (default: one top view per level)")
    s.add_argument("--mode", choices=["type", "boundary", "u", "heat", "cool"])
    s.set_defaults(fn=_cmd_preview_png)

    s = sub.add_parser("clone", help="copy a project's building.json to a new folder for a what-if run")
    s.add_argument("src")
    s.add_argument("dst")
    s.add_argument("--keep-design", action="store_true", help="keep the design block (same site)")
    s.set_defaults(fn=_cmd_clone)

    s = sub.add_parser("nbc", help="look up NBC 2020 Table C-2 design values for a Canadian municipality")
    s.add_argument("--place", required=True, help="municipality as listed, e.g. Montréal, Québec, Gatineau")
    s.add_argument("--pdf", help="path to the NBC 2020 PDF (default: download the free NRC copy once)")
    s.set_defaults(fn=_cmd_nbc)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
