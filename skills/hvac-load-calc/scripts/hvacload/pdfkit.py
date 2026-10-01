"""PDF plan helpers: classify pages, render (with a coordinate grid), crop, extract vectors/text,
measure with a two-point calibration, and overlay the model on a page for visual QA.

Page coordinates are PDF points (1/72 in) with the origin at the TOP-LEFT of the page and y
increasing downward (pdfplumber convention). Rendered images use pixel = point * dpi / 72.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

DIM_RE = re.compile(
    r"""(?x)
    (\d{1,3}\s*'\s*-?\s*\d{1,2}(\s*\d/\d)?\s*"?)   # 12'-6"  12' 6"  12'-6 1/2"
    |(\d{1,3}\s*')                                 # 12'
    |(\d{1,2}(\.\d+)?\s?m\b)                       # 3.6 m
    |(\b\d{3,5}\s?mm\b)                            # 3600 mm
    """
)
# metric plans usually print millimetres without a unit, often with a space as thousands separator
MM_RE = re.compile(r"(?<![\d.,])\d{1,2}[ \u202f\u00a0]\d{3}(?![\d.,])|(?<![\d.,])\d{3,5}(?![\d.,])")
SCALE_RE = re.compile(r"""(?ix)
    (\d+(/\d+)?\s*"\s*=\s*\d+\s*'\s*-?\s*\d*\s*"?)   # 1/4" = 1'-0"
    |(\b1\s*:\s*\d{2,3}\b)                          # 1:50
    |(scale[^\\n]{0,30})
""")


def _font(size=12):
    for name in ("arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def info(pdf_path: str) -> dict:
    """Classify each page as vector, raster or mixed, and report scale notes and dimension text."""
    out = {"file": str(pdf_path), "pages": []}
    with pdfplumber.open(pdf_path) as pdf:
        for i, pg in enumerate(pdf.pages):
            W, H = float(pg.width), float(pg.height)
            imgs = []
            img_cover = 0.0
            small = 0
            for im in pg.images:
                w, h = im["x1"] - im["x0"], im["bottom"] - im["top"]
                cover = (w * h) / (W * H)
                img_cover += cover
                sw, sh = im.get("srcsize", (0, 0))
                if cover < 0.05:
                    small += 1
                    continue
                imgs.append({"bbox_pt": [round(im["x0"], 1), round(im["top"], 1), round(im["x1"], 1),
                                         round(im["bottom"], 1)],
                             "pixels": [sw, sh], "effective_dpi": round(sw / (w / 72), 0) if w else None,
                             "page_fraction": round(cover, 3)})
            n_lines, n_rects, n_curves = len(pg.lines), len(pg.rects), len(pg.curves)
            n_vec = n_lines + n_rects + n_curves
            text = pg.extract_text() or ""
            n_chars = len(pg.chars)
            if img_cover > 0.4 and n_vec < 200:
                kind = "raster"
            elif img_cover < 0.2 and (n_vec >= 20 or n_chars >= 200):
                kind = "vector"  # drawn content is real PDF paths/text (few images, if any)
            elif img_cover < 0.2:
                kind = "text_or_empty"
            else:
                kind = "mixed"
            dims = sorted({m.group(0).strip() for m in DIM_RE.finditer(text)})
            mm = sorted({m.group(0).strip() for m in MM_RE.finditer(text)}, key=lambda t: -len(t))
            scales = sorted({m.group(0).strip() for m in SCALE_RE.finditer(text)})
            big = max((im["effective_dpi"] or 0 for im in imgs if im["page_fraction"] > 0.2), default=None)
            out["pages"].append({
                "page": i + 1, "size_pt": [round(W, 1), round(H, 1)],
                "size_in": [round(W / 72, 2), round(H / 72, 2)],
                "kind": kind, "vector_paths": n_vec, "chars": n_chars, "images": imgs, "small_images": small,
                "image_coverage": round(img_cover, 3), "main_image_dpi": big,
                "scale_notes_in_text_layer": scales, "dimension_strings_in_text_layer": dims[:80],
                "metric_mm_like_numbers": mm[:80],
                "text_head": " | ".join(text.splitlines()[:6])[:300],
            })
    kinds = {p["kind"] for p in out["pages"]}
    if kinds <= {"raster", "text_or_empty"} and "raster" in kinds:
        out["overall"] = "raster"
    elif kinds <= {"vector", "text_or_empty"}:
        out["overall"] = "vector"
    else:
        out["overall"] = "mixed"
    if out["overall"] != "vector":
        out["warning"] = ("Raster content detected: geometry must be read visually from images. Expect lower "
                          "accuracy; build dimensions from printed dimension strings, never from a printed scale "
                          "note, and confirm the takeoff with the user.")
    return out


def render(pdf_path: str, page: int, out_png: str, dpi: int = 150, crop=None, grid: float | None = None) -> dict:
    """Render a page (1-based). crop = (x0, y0, x1, y1) in points. grid = spacing in points."""
    doc = pdfium.PdfDocument(pdf_path)
    pg = doc[page - 1]
    W, H = pg.get_size()
    scale = dpi / 72.0
    img = pg.render(scale=scale).to_pil().convert("RGB")
    ox = oy = 0.0
    if crop:
        x0, y0, x1, y1 = crop
        img = img.crop((int(x0 * scale), int(y0 * scale), int(x1 * scale), int(y1 * scale)))
        ox, oy = x0, y0
    if grid:
        d = ImageDraw.Draw(img, "RGBA")
        fs = max(11, int(dpi / 14))
        f = _font(fs)
        every = max(1, math.ceil(fs * 4.5 / (grid * scale)))  # label spacing >= ~4 label heights
        x_start = math.ceil(ox / grid) * grid
        y_start = math.ceil(oy / grid) * grid
        x, i = x_start, 0
        while (x - ox) * scale < img.width:
            px = (x - ox) * scale
            major = round(x / grid) % every == 0
            d.line([(px, 0), (px, img.height)], fill=(255, 0, 0, 110 if major else 45), width=1)
            if major:
                d.rectangle([px + 1, 1, px + 3 + fs * 2.4, 3 + fs], fill=(255, 255, 255, 200))
                d.text((px + 2, 2), f"{x:g}", fill=(200, 0, 0, 255), font=f)
            x += grid
            i += 1
        y = y_start
        while (y - oy) * scale < img.height:
            py = (y - oy) * scale
            major = round(y / grid) % every == 0
            d.line([(0, py), (img.width, py)], fill=(0, 0, 255, 110 if major else 45), width=1)
            if major:
                d.rectangle([1, py + 1, 3 + fs * 2.4, py + 3 + fs], fill=(255, 255, 255, 200))
                d.text((2, py + 2), f"{y:g}", fill=(0, 0, 200, 255), font=f)
            y += grid
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    return {"png": str(out_png), "page": page, "dpi": dpi, "page_size_pt": [W, H], "crop_pt": crop,
            "pixels": [img.width, img.height], "grid_pt": grid,
            "note": "grid labels are page points (origin top-left, y down); pixel = (pt - crop_origin) * dpi / 72"}


def _rotated_words(chars) -> list[dict]:
    """Group rotated (non-upright) characters into words in reading order (vertical dimension text)."""
    rot = [c for c in chars if not c.get("upright", True) and c["text"].strip()]
    cols: list[list[dict]] = []
    for c in sorted(rot, key=lambda c: (round(c["x0"]), c["top"])):
        for col in cols:
            if abs(col[0]["x0"] - c["x0"]) <= 1.0:
                col.append(c)
                break
        else:
            cols.append([c])
    words = []
    for col in cols:
        b = (col[0].get("matrix") or (1, 0, 0, 1, 0, 0))[1]
        col.sort(key=lambda c: -c["top"] if b > 0 else c["top"])  # b > 0: text reads bottom to top
        cur = [col[0]]
        for c in col[1:]:
            size = max(c.get("size", 6), 1)
            gap = abs(c["top"] - cur[-1]["top"]) - (c["bottom"] - c["top"])
            if gap > size * 1.5:
                words.append(cur)
                cur = [c]
            else:
                cur.append(c)
        words.append(cur)
    out = []
    for w in words:
        text, prev = "", None
        for c in w:
            if prev is not None and abs(c["top"] - prev["top"]) - (c["bottom"] - c["top"]) > max(c.get("size", 6), 1) * 0.25:
                text += " "
            text += c["text"]
            prev = c
        out.append({"text": text, "x0": round(min(c["x0"] for c in w), 1), "top": round(min(c["top"] for c in w), 1),
                    "x1": round(max(c["x1"] for c in w), 1), "bottom": round(max(c["bottom"] for c in w), 1),
                    "upright": False})
    return out


def vectors(pdf_path: str, page: int, min_len: float = 8.0) -> dict:
    """Line work, curves and positioned words (points, top-left origin). Long orthogonal lines are wall candidates;
    dimension_words holds imperial strings and metric millimetre numbers (incl. "3 200" and vertical text)."""
    with pdfplumber.open(pdf_path) as pdf:
        pg = pdf.pages[page - 1]
        lines = []
        for ln in pg.lines + [e for r in pg.rects for e in _rect_edges(r)]:
            x0, y0, x1, y1 = ln["x0"], ln["top"], ln["x1"], ln["bottom"]
            L = math.hypot(x1 - x0, y1 - y0)
            if L < min_len:
                continue
            lines.append({"x0": round(x0, 2), "y0": round(y0, 2), "x1": round(x1, 2), "y1": round(y1, 2),
                          "len": round(L, 2), "w": round(float(ln.get("linewidth") or ln.get("stroke_width") or 0), 2),
                          "orth": abs(x1 - x0) < 0.5 or abs(y1 - y0) < 0.5})
        curves = []
        for cv in pg.curves:
            pts = cv.get("pts") or []
            curves.append({"bbox": [round(cv["x0"], 1), round(cv["top"], 1), round(cv["x1"], 1), round(cv["bottom"], 1)],
                           "n_pts": len(pts), "fill": bool(cv.get("fill")),
                           "pts": [[round(x, 1), round(y, 1)] for x, y in pts[:40]]})
        words = [{"text": w["text"], "x0": round(w["x0"], 1), "top": round(w["top"], 1), "x1": round(w["x1"], 1),
                  "bottom": round(w["bottom"], 1), "upright": True}
                 for w in pg.extract_words(keep_blank_chars=True, x_tolerance=1.5, extra_attrs=["upright"])
                 if w.get("upright", True)]
        words += _rotated_words(pg.chars)
    dims = [w for w in words if DIM_RE.fullmatch(w["text"].strip() or "x") or MM_RE.fullmatch(w["text"].strip())]
    widths: dict[float, int] = {}
    for ln in lines:
        widths[ln["w"]] = widths.get(ln["w"], 0) + 1
    return {"page": page, "n_lines": len(lines), "stroke_widths": dict(sorted(widths.items())),
            "n_curves": len(curves), "lines": lines, "curves": curves, "words": words, "dimension_words": dims,
            "note": "curves include arcs and filled shapes (door swings, north arrow): an arrow is a small filled "
                    "curve; its bearing is the direction from the curve's base to its tip"}


def _rect_edges(r):
    x0, x1, t, b = r["x0"], r["x1"], r["top"], r["bottom"]
    base = {"linewidth": r.get("linewidth", 0)}
    return [dict(base, x0=x0, x1=x1, top=t, bottom=t), dict(base, x0=x0, x1=x1, top=b, bottom=b),
            dict(base, x0=x0, x1=x0, top=t, bottom=b), dict(base, x0=x1, x1=x1, top=t, bottom=b)]


_FRAC = {"½": " 1/2", "¼": " 1/4", "¾": " 3/4", "⅛": " 1/8", "⅜": " 3/8", "⅝": " 5/8", "⅞": " 7/8",
         "⅓": " 1/3", "⅔": " 2/3", "′": "'", "″": '"', "’": "'", "”": '"', "“": '"'}
_IMP_RE = re.compile(r"""^\s*(?:(?P<ft>\d+(?:\.\d+)?)\s*(?:'|ft)\s*[-\s]?\s*)?
                         (?:(?P<inch>\d+(?:\.\d+)?)?\s*(?:(?P<num>\d+)\s*/\s*(?P<den>\d+))?\s*(?:"|in)?)?\s*$""", re.X)
_MET_RE = re.compile(r"^\s*(?P<v>\d+(?:[.,]\d+)?)\s*(?P<u>mm|cm|m)\s*$")


def parse_length(s: str, units: str) -> float:
    """Parse 48ft, 12'-6", 10'-6 1/2", 6 1/2", 3'6", 3.6m, 3600mm into `units` (ft or m)."""
    t = str(s)
    for k, v in _FRAC.items():
        t = t.replace(k, v)
    m = _MET_RE.match(t)
    if m:
        v = float(m.group("v").replace(",", "."))
        metres = v * {"mm": 0.001, "cm": 0.01, "m": 1.0}[m.group("u")]
        return metres if units == "m" else metres / 0.3048
    m = _IMP_RE.match(t)
    has_digit = any(ch.isdigit() for ch in t)
    if not m or not has_digit or not ("'" in t or '"' in t or "ft" in t or "in" in t):
        raise ValueError(f"cannot parse length '{s}' (use e.g. 48ft, 12'-6\", 10'-6 1/2\", 3.6m, 3600mm)")
    feet = float(m.group("ft") or 0)
    inches = float(m.group("inch") or 0)
    if m.group("num"):
        inches += float(m.group("num")) / float(m.group("den"))
    feet += inches / 12
    return feet if units == "ft" else feet * 0.3048


def calibrate(a, b, length: str, units: str) -> float:
    """Plan units per page point from two page points spanning a known dimension."""
    d = math.dist(a, b)
    if d < 1:
        raise ValueError("calibration points are too close")
    return parse_length(length, units) / d


def to_plan(pt, origin, units_per_pt: float):
    """Page point -> plan coordinates (x right, y up) given the page point of plan (0, 0)."""
    return ((pt[0] - origin[0]) * units_per_pt, (origin[1] - pt[1]) * units_per_pt)


def overlay(pdf_path: str, page: int, building_raw: dict, calib: dict, out_png: str, dpi: int = 200,
            crop=None) -> dict:
    """Draw model rooms/openings (plan coords) on the rendered page using the calibration
    {origin_pt: [x, y], units_per_pt: s}. Misalignment = takeoff error. crop = (x0, y0, x1, y1) points;
    by default the model extent plus a margin."""
    doc = pdfium.PdfDocument(pdf_path)
    img = doc[page - 1].render(scale=dpi / 72).to_pil().convert("RGB")
    ox, oy = calib["origin_pt"]
    s = float(calib["units_per_pt"])
    k = dpi / 72.0
    level = calib.get("level")
    pts_all = [(ox + x / s, oy - y / s) for r in building_raw.get("rooms", [])
               if not level or r.get("level") == level for x, y in r["polygon"]]
    if crop is None and pts_all:
        m = 70  # keep the outer dimension chains in view
        crop = (min(p[0] for p in pts_all) - m, min(p[1] for p in pts_all) - m,
                max(p[0] for p in pts_all) + m, max(p[1] for p in pts_all) + m)
    cx0, cy0 = (crop[0], crop[1]) if crop else (0, 0)
    if crop:
        img = img.crop((int(crop[0] * k), int(crop[1] * k), int(crop[2] * k), int(crop[3] * k)))
    d = ImageDraw.Draw(img, "RGBA")
    f = _font(max(10, int(dpi / 16)))

    def px(x, y):
        return ((ox + x / s - cx0) * k, (oy - y / s - cy0) * k)

    palette = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180), (70, 240, 240),
               (240, 50, 230), (210, 245, 60), (0, 128, 128), (170, 110, 40)]
    for i, r in enumerate(building_raw.get("rooms", [])):
        if level and r.get("level") != level:
            continue
        col = palette[i % len(palette)]
        pts = [px(x, y) for x, y in r["polygon"]]
        d.polygon(pts, fill=col + (28,))
        d.line(pts + pts[:1], fill=col + (230,), width=2)
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        tw = len(r["id"]) * f.size * 0.3
        d.rectangle([cx - tw, cy - f.size * 0.6, cx + tw, cy + f.size * 0.6], fill=(255, 255, 255, 150))
        d.text((cx, cy), r["id"], fill=col + (255,), font=f, anchor="mm")
    rooms = {r["id"]: r for r in building_raw.get("rooms", [])}
    for o in building_raw.get("openings", []):
        if o.get("at") is None or (level and rooms.get(o["room"], {}).get("level") != level):
            continue
        x, y = px(*o["at"])
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(0, 0, 255, 255), width=2)
        d.text((x + 7, y - f.size - 2), o.get("id", ""), fill=(0, 0, 255, 230), font=f)
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    return {"png": str(out_png), "page": page, "dpi": dpi, "crop_pt": crop}


def profile(pdf_path: str, page: int, crop, axis: str = "x", dpi: int = 300, min_fraction: float = 0.35,
            dark: int = 110) -> dict:
    """Find straight dark lines in a (raster) page crop: axis='x' finds vertical lines (their x in points),
    axis='y' horizontal lines (their y). A line is a run of pixel columns/rows whose dark fraction over the crop
    is >= min_fraction. Use it to locate dimension extension lines and wall faces precisely."""
    import numpy as np

    doc = pdfium.PdfDocument(pdf_path)
    k = dpi / 72.0
    img = doc[page - 1].render(scale=k).to_pil().convert("L")
    x0, y0, x1, y1 = crop
    a = np.asarray(img.crop((int(x0 * k), int(y0 * k), int(x1 * k), int(y1 * k))))
    frac = (a < dark).mean(axis=0 if axis == "x" else 1)
    lines, i = [], 0
    while i < len(frac):
        if frac[i] >= min_fraction:
            j = i
            while j + 1 < len(frac) and frac[j + 1] >= min_fraction:
                j += 1
            w = frac[i:j + 1]
            centre = (i + (w * np.arange(len(w))).sum() / w.sum()) / k + (x0 if axis == "x" else y0)
            lines.append({"pt": round(float(centre), 2), "width_pt": round((j - i + 1) / k, 2),
                          "dark_fraction": round(float(w.max()), 2)})
            i = j + 1
        else:
            i += 1
    return {"page": page, "axis": axis, "crop_pt": list(crop), "dpi": dpi, "lines": lines,
            "note": "x lines are vertical (positions along x); narrow the crop to one band to isolate a feature"}


def dump(obj) -> str:
    return json.dumps(obj, indent=2)
