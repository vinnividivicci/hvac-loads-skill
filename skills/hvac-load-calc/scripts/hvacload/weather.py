"""Design weather: find the nearest climate.onebuilding.org station, download its EPW/DDY/STAT,
and extract ASHRAE design conditions from the DDY (the EPW header is NOT used: OpenStudio 3.11
cannot parse the 2025-format header and silently falls back to computed values).

Data is downloaded at run time into HVACLOAD_HOME/weather; nothing is bundled with the skill.
climate.onebuilding.org asks users to cite it; record the station URL in the project.
"""

from __future__ import annotations

import io
import math
import re
import urllib.request
import zipfile
from pathlib import Path

from .tools import weather_dir

INDEXES = {
    "USA": "https://climate.onebuilding.org/sources/Region4_USA_TMYx_EPW_Processing_locations.xlsx",
    "Canada": "https://climate.onebuilding.org/sources/Region4_Canada_TMYx_EPW_Processing_locations.xlsx",
    "CanadaCWEC": "https://climate.onebuilding.org/sources/CWEC2020v2_EPW_Processing_locations.xlsx",
}


def _fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "hvacload/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    return dest


def _load_index(region: str) -> list[dict]:
    import openpyxl

    path = _fetch(INDEXES[region], weather_dir() / f"index_{region}.xlsx")
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h else "" for h in next(rows)]

    def col(*names):
        for n in names:
            for i, h in enumerate(header):
                if h.lower().startswith(n.lower()):
                    return i
        return None

    ci = {"city": col("City"), "state": col("State", "Province"), "wmo": col("WMO"), "lat": col("Latitude"),
          "lon": col("Longitude"), "elev": col("Elevation"), "url": col("URL")}
    out = []
    for r in rows:
        try:
            url = r[ci["url"]]
            if not url or not str(url).endswith(".zip"):
                continue
            out.append({"station": r[ci["city"]], "state": r[ci["state"]] if ci["state"] is not None else "",
                        "wmo": r[ci["wmo"]], "lat": float(r[ci["lat"]]), "lon": float(r[ci["lon"]]),
                        "elevation_m": float(r[ci["elev"]] or 0), "url": str(url), "index": region})
        except (TypeError, ValueError):
            continue
    return out


def _haversine_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _rank(url: str) -> int:
    """Prefer the most recent TMYx period, then CWEC2020."""
    m = re.search(r"TMYx\.(\d{4})-(\d{4})", url)
    if m:
        return int(m.group(2))
    if "CWEC2020" in url:
        return 2019
    if "TMYx" in url:
        return 2000
    return 1900


def find(lat: float, lon: float, country: str = "USA", n: int = 5) -> list[dict]:
    regions = ["Canada", "CanadaCWEC"] if country.lower().startswith("ca") else ["USA"]
    rows = [r for reg in regions for r in _load_index(reg)]
    best: dict = {}
    for r in rows:
        key = r["wmo"]
        if key not in best or _rank(r["url"]) > _rank(best[key]["url"]):
            best[key] = r
    for r in best.values():
        r["distance_km"] = round(_haversine_km((lat, lon), (r["lat"], r["lon"])), 1)
    return sorted(best.values(), key=lambda r: r["distance_km"])[:n]


def download(url: str) -> dict:
    name = url.rsplit("/", 1)[-1]
    zpath = _fetch(url, weather_dir() / name)
    folder = weather_dir() / name[:-4]
    if not folder.exists():
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(folder)
    files = {p.suffix.lower().lstrip("."): p for p in folder.iterdir()}
    return {"folder": str(folder), "epw": str(files.get("epw", "")), "ddy": str(files.get("ddy", "")),
            "stat": str(files.get("stat", "")), "source_url": url}


def _idf_objects(text: str):
    text = re.sub(r"!.*", "", text)
    for chunk in text.split(";"):
        fields = [f.strip() for f in chunk.split(",")]
        if fields and fields[0]:
            yield fields


def parse_ddy(path: str) -> dict:
    """Return {name: {...}} for every SizingPeriod:DesignDay in the DDY file."""
    txt = Path(path).read_text(encoding="latin-1")
    out = {}
    for f in _idf_objects(txt):
        if f[0].lower() != "sizingperiod:designday":
            continue
        g = lambda i, conv=float: conv(f[i]) if len(f) > i and f[i] not in ("",) else None  # noqa: E731
        try:
            out[f[1]] = {
                "month": g(2, int), "day": g(3, int), "day_type": f[4],
                "max_db_c": g(5), "daily_range_c": g(6), "humidity_type": f[9] if len(f) > 9 else "",
                "humidity_value": g(10), "humidity_ratio": g(12), "enthalpy": g(13), "pressure_pa": g(15),
                "wind_ms": g(16), "wind_dir": g(17), "solar_model": f[21] if len(f) > 21 else "",
                "taub": g(24), "taud": g(25), "clearness": g(26),
            }
        except (ValueError, IndexError):
            continue
    return out


def parse_stat(path: str) -> dict:
    txt = Path(path).read_text(encoding="latin-1")
    out = {}
    m = re.search(r'Climate Zone\s+"([0-9][A-C]?)"\s*\(ASHRAE Standard 169', txt) or         re.search(r'Climate type\s+"([0-9][A-C]?)"\s*\(ASHRAE', txt)
    if m:
        out["ashrae_climate_zone"] = m.group(1)
    m = re.search(r"(\d{2,5}) annual \(standard\) heating degree-days \(18\.3C baseline\)", txt) or         re.search(r"(\d{2,5}) annual \(wthr file\) heating degree-days \(18C baseline\)", txt)
    if m:
        out["hdd18"] = int(m.group(1))
        out["hdd_note"] = "HDD from the STAT file (ASHRAE long-term if 'standard' was present). For Canadian code "                           "zones use NBC Table C-2 HDD, not this value."
    return out


def epw_header(path: str) -> dict:
    with open(path, encoding="latin-1") as fh:
        lines = [next(fh) for _ in range(8)]
    loc = lines[0].split(",")
    out = {"city": loc[1], "state": loc[2], "country": loc[3], "wmo": loc[5], "lat": float(loc[6]),
           "lon": float(loc[7]), "tz": float(loc[8]), "elevation_m": float(loc[9])}
    gt = [ln for ln in lines if ln.startswith("GROUND TEMPERATURES")]
    if gt:
        f = gt[0].strip().split(",")
        n = int(f[1]) if f[1] else 0
        depths = []
        i = 2
        for _ in range(n):
            depth = float(f[i])
            temps = [float(x) for x in f[i + 4:i + 16]]
            depths.append({"depth_m": depth, "monthly_c": temps})
            i += 16
        out["ground_temperatures"] = depths
    return out


def design_summary(files: dict) -> dict:
    """ASHRAE design conditions (from DDY) + EPW location + STAT climate zone."""
    dd = parse_ddy(files["ddy"]) if files.get("ddy") else {}

    def pick(pattern):
        for name, d in dd.items():
            if re.search(pattern, name, re.I):
                return name, d
        return None, None

    out = {"source_url": files.get("source_url"), "epw": files.get("epw"), "ddy": files.get("ddy"),
           "note": "ASHRAE climatic design conditions as published in the OneBuilding DDY file; cite "
                   "climate.onebuilding.org and the ASHRAE Handbook edition named in the DDY."}
    if files.get("epw"):
        out["location"] = epw_header(files["epw"])
    if files.get("stat"):
        out.update(parse_stat(files["stat"]))
    for key, pat in {
        "heating_99.6": r"Htg 99\.6% Condns DB", "heating_99": r"Htg 99% Condns DB",
        "cooling_0.4": r"Clg \.4% Condns DB=>MWB", "cooling_1": r"Clg 1% Condns DB=>MWB",
        "cooling_2": r"Clg 2% Condns DB=>MWB",
    }.items():
        name, d = pick(pat)
        if d:
            out[key] = {"name": name, "db_c": d["max_db_c"], "daily_range_c": d["daily_range_c"],
                        "humidity_type": d["humidity_type"], "humidity_value": d["humidity_value"],
                        "wind_ms": d["wind_ms"], "month": d["month"], "day": d["day"],
                        "solar_model": d["solar_model"], "taub": d["taub"], "taud": d["taud"]}
    m = re.search(r"(\d{4}) ASHRAE", Path(files["ddy"]).read_text(encoding="latin-1")) if files.get("ddy") else None
    if m:
        out["ashrae_edition"] = m.group(1)
    return out


def daily_range_class(range_f: float) -> str:
    """Manual J daily range class from the cooling-month mean daily range in degF."""
    return "low" if range_f < 16 else ("medium" if range_f <= 25 else "high")
