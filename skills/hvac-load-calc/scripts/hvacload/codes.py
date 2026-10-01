"""NBC Appendix C (Table C-2) climatic design values: look up a municipality in the free NBC PDF.

The NBC is published free of charge by the National Research Council of Canada. Nothing is bundled:
the PDF is downloaded at run time (or the user points to their own copy) and cached in HVACLOAD_HOME/codes.
The row is returned as printed, with a best-effort split into columns and the page number, so the
value can be verified on the page before use.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from pathlib import Path

from .tools import home

NBC2020_URL = "https://nrc-publications.canada.ca/eng/view/ft/?id=515340b5-f4e0-4798-be69-692e4ec423e8"
COLUMNS = ["elevation_m", "jan_2.5pct_c", "jan_1pct_c", "jul_2.5pct_dry_c", "jul_2.5pct_wet_c", "hdd_below_18c"]
NUM_RE = re.compile(r"[-−–]?\d+(?:[.,]\d+)?")


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t)
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


def _pdf(path: str | None) -> Path:
    if path:
        return Path(path)
    dest = home() / "codes" / "nbc2020.pdf"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(NBC2020_URL, headers={"User-Agent": "Mozilla/5.0 (hvacload)"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        if not data.startswith(b"%PDF"):
            raise SystemExit("the NRC link did not return a PDF; download the NBC 2020 PDF from the NRC Publications "
                             "Archive yourself and pass it with --pdf")
        dest.write_bytes(data)
    return dest


def _table_pages(pdf: Path) -> dict:
    cache = pdf.with_suffix(".tableC2.json")
    if cache.exists() and cache.stat().st_mtime >= pdf.stat().st_mtime:
        return json.loads(cache.read_text(encoding="utf-8"))
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    pages = {}
    for i in range(len(doc)):
        text = doc[i].get_textpage().get_text_range()
        if "Table C-2" in text and ("Design Temperature" in text or "January" in text):
            pages[str(i + 1)] = text
    cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def lookup(place: str, pdf_path: str | None = None) -> dict:
    pdf = _pdf(pdf_path)
    pages = _table_pages(pdf)
    if not pages:
        return {"ok": False, "error": "no Table C-2 pages found in this PDF", "pdf": str(pdf)}
    key = _norm(place)
    num = r"[-−–]?\d+"
    # an entry = the place name (optionally "(City Hall)" etc.) directly followed by elevation, Jan 2.5 %, Jan 1 %,
    # July dry, July wet, HDD. Region headings ("Montréal Region") are not followed by numbers and are skipped.
    row_re = re.compile(r"(?<![a-z])" + re.escape(key) + r"(?:-[a-z']+)*\s*(\([^)]*\))?\s+" + r"\s+".join([f"({num})"] * 6))
    hits = []
    for pno, text in pages.items():
        flat = " ".join(text.split())
        norm = _norm(flat)  # same length as flat for precomposed accents
        for m in row_re.finditer(norm):
            name = flat[m.start():m.start(2) if m.group(1) is None else m.end(1)].strip()
            vals = [flat[m.start(i):m.end(i)].replace("−", "-").replace("–", "-") for i in range(2, 8)]
            hits.append({"page": int(pno), "entry": name, "values": dict(zip(COLUMNS, vals)),
                         "context": flat[max(0, m.start() - 40):m.end() + 60]})
    hits.sort(key=lambda h: (_norm(h["entry"]).split(" (")[0] != key, h["page"]))
    return {"ok": bool(hits), "pdf": str(pdf), "source": "NBC 2020, Division B, Appendix C, Table C-2",
            "matches": hits[:20],
            "verify": "Column split is a guess from the printed row: check it on the page, e.g. `pdf-render <pdf> "
                      "--page N --dpi 150`, then cite the edition, table and municipality in design.*.src"}
