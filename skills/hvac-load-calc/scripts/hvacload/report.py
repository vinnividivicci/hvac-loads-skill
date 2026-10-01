"""Printable HTML report (English or French) with inputs, sources, QA, results and the method cross-check.

A PDF is produced with a locally installed Chromium browser (Edge/Chrome) in headless mode if available.
Text written by the agent (src, labels, assumptions) is printed verbatim: write it in the report language.
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path

from .model import Building
from .units import W_PER_BTUH, c_to_f

L = {
    "en": {
        "title": "Residential heating and cooling design loads", "notice_h": "Professional-use notice",
        "notice": "This report was produced with open-source engines driven by an AI assistant. It is a design aid for a "
                  "qualified professional, like a calculation spreadsheet: it is not an ACCA-approved Manual J report "
                  "and not a CSA F280-verified calculation. The professional who uses it remains responsible for "
                  "verifying the inputs, the method and the results before relying on them.",
        "raster": "The plans were supplied as a rasterized (scanned) PDF. Geometry was read visually, which is less "
                  "reliable than a vector PDF.",
        "raster_ok": "The geometry was reviewed and confirmed by the user on {date}.",
        "raster_no": "The geometry has NOT been recorded as confirmed by the user: treat it with extra care.",
        "summary": "Summary", "whole": "Whole house", "heating": "Heating", "cool_s": "Cooling, sensible",
        "cool_l": "Cooling, latent", "cool_t": "Cooling, total", "design": "Design conditions",
        "rooms": "Room-by-room loads", "room": "Room", "area": "Floor area", "cfm_h": "Heating airflow",
        "cfm_c": "Cooling airflow", "components": "Load components (primary method, whole house)",
        "cross": "Independent cross-check", "inputs": "Inputs and their sources", "qa": "Takeoff quality checks",
        "assump": "Assumptions and defaults", "files": "Files and versions", "warnings": "Items to review",
        "method": "Method", "source": "Source", "outdoor": "Outdoor", "indoor": "Indoor", "category": "Category",
        "delta": "Difference", "ratios": "Sanity ratios", "generated": "Generated", "daily_range": "Daily range",
        "dhum": "Humidity difference", "weather": "Weather station", "rh": "RH",
        "weather_note": "ASHRAE design conditions as distributed in the station's DDY file (climate.onebuilding.org).",
        "airflow_note": "Room airflow = room sensible load / (air factor × supply ΔT), with ΔT {dth} heating and {dtc} "
                        "cooling. The whole-house total is the block load, which can be lower than the sum of room "
                        "peaks for cooling. Room loads exclude system-level mechanical ventilation (included in the "
                        "whole-house total). Latent loads are computed for the whole house only.",
        "comp_note": "Components of the whole-house block load, as reported by the primary engine.",
        "like": "like-for-like", "rooms_h": "Rooms", "cat_h": "By category", "ep_notes": "Cross-check model notes",
        "not_run": "The EnergyPlus cross-check did not run; see the run log.",
        "assemblies": "Assemblies", "name": "Name", "desc": "Description", "windows": "Windows and doors",
        "product": "Product", "systems": "Airtightness, ventilation and systems", "gains": "Internal gains allocation",
        "occ": "Occupants", "appl": "Appliances", "item": "Item", "stated": "Stated on plans", "modelled": "Modelled",
        "chain": "Dimension chain", "sum_parts": "Sum of parts", "total": "Total", "span": "Model span",
        "resolution": "Resolution", "glazing": "Glazing by orientation", "wfr": "window-to-floor",
        "excluded": "excluded from like-for-like", "ton": "ton",
        "basis": "Like-for-like: above-grade envelope conduction + infiltration (+ internal gains and solar for "
                 "cooling). Ducts and mechanical ventilation are excluded (modelled by the primary method only); ground "
                 "contact is compared separately. Flag thresholds (rule of thumb, not a standard): heating {h} %, "
                 "cooling {c} %.",
        "ground": "Ground contact (slabs, foundation walls): primary {mj} W vs cross-check {ep} W. The methods differ by "
                  "design (Manual J tables against the outdoor design temperature vs ISO 13370-style U-values against "
                  "an EN 12831 effective ground temperature), so this line is shown side by side, not compared.",
        "flag_h": "{room}: heating differs by {d} between methods", "flag_c": "{room}: sensible cooling differs by {d} "
                  "between methods", "flag_wh": "WHOLE HOUSE: heating differs by {d} between methods",
        "flag_wc": "WHOLE HOUSE: sensible cooling differs by {d} between methods",
        "cats": {"walls": "walls", "ceilings/roofs": "ceilings / roofs", "floors": "floors",
                 "ground contact": "ground contact", "windows": "windows", "doors": "doors",
                 "infiltration": "infiltration", "ventilation": "ventilation", "ducts": "ducts",
                 "internal gains": "internal gains"},
        "keys": {"ach50": "ACH50", "cfm50": "CFM50", "leakiness": "leakiness", "type": "type", "cfm": "flow (cfm)",
                 "lps": "flow (L/s)", "sre": "sensible recovery", "tre": "total recovery", "hours": "hours/day",
                 "distribution": "distribution", "ducts": "ducts", "location": "location", "supply_r_ip": "supply R",
                 "return_r_ip": "return R", "leakage_cfm25": "leakage (CFM25)", "occupants": "occupants",
                 "appliance_sensible_btuh": "appliances, sensible (Btu/h)",
                 "appliance_latent_btuh": "appliances, latent (Btu/h)"},
        "rows": {"airtightness": "Airtightness", "ventilation": "Ventilation", "hvac": "HVAC",
                 "internal_gains": "Internal gains"},
        "vals": {}, "orient": {"N": "N", "E": "E", "S": "S", "W": "W"},
        "items": {"conditioned_area": "conditioned floor area", "garage_area": "garage area",
                  "glazing_area": "glazing area"},
        "explained": "explained", "station_only": "The weather station supplies only the daily range, the solar "
                      "model and ground temperatures; the design temperatures above come from the sources listed.",
    },
    "fr": {
        "title": "Charges de chauffage et de climatisation de conception (résidentiel)",
        "notice_h": "Avis d'utilisation professionnelle",
        "notice": "Ce rapport a été produit avec des moteurs de calcul libres pilotés par un assistant IA. Il s'agit d'un "
                  "outil d'aide à la conception pour un professionnel qualifié, au même titre qu'un chiffrier : ce "
                  "n'est pas un rapport Manual J approuvé par l'ACCA ni un calcul vérifié selon la norme CSA F280. Le "
                  "professionnel qui l'utilise demeure responsable de vérifier les données, la méthode et les résultats.",
        "raster": "Les plans ont été fournis en PDF matriciel (numérisé). La géométrie a été lue visuellement, ce qui est "
                  "moins fiable qu'un PDF vectoriel.",
        "raster_ok": "La géométrie a été revue et confirmée par l'utilisateur le {date}.",
        "raster_no": "La confirmation de la géométrie par l'utilisateur n'a PAS été consignée : l'utiliser avec prudence.",
        "summary": "Sommaire", "whole": "Bâtiment entier", "heating": "Chauffage", "cool_s": "Climatisation, sensible",
        "cool_l": "Climatisation, latente", "cool_t": "Climatisation, totale", "design": "Conditions de conception",
        "rooms": "Charges pièce par pièce", "room": "Pièce", "area": "Surface de plancher", "cfm_h": "Débit chauffage",
        "cfm_c": "Débit climatisation", "components": "Composantes de charge (méthode principale, bâtiment entier)",
        "cross": "Contre-vérification indépendante", "inputs": "Données d'entrée et sources",
        "qa": "Contrôles de qualité du relevé", "assump": "Hypothèses et valeurs par défaut",
        "files": "Fichiers et versions", "warnings": "Éléments à vérifier", "method": "Méthode", "source": "Source",
        "outdoor": "Extérieur", "indoor": "Intérieur", "category": "Catégorie", "delta": "Écart",
        "ratios": "Ratios de vraisemblance", "generated": "Généré le", "daily_range": "Écart diurne",
        "dhum": "Écart d'humidité", "weather": "Station météo", "rh": "HR",
        "weather_note": "Conditions de conception ASHRAE telles que diffusées dans le fichier DDY de la station "
                        "(climate.onebuilding.org).",
        "airflow_note": "Débit par pièce = charge sensible de la pièce / (facteur d'air × ΔT de soufflage), avec ΔT "
                        "{dth} en chauffage et {dtc} en climatisation. Le total du bâtiment est la charge globale, qui "
                        "peut être inférieure à la somme des pointes des pièces en climatisation. Les charges par pièce "
                        "excluent la ventilation mécanique (comptée au niveau du système, incluse dans le total). Les "
                        "charges latentes sont calculées pour le bâtiment entier seulement.",
        "comp_note": "Composantes de la charge globale du bâtiment, telles que rapportées par le moteur principal.",
        "like": "comparable", "rooms_h": "Pièces", "cat_h": "Par catégorie",
        "ep_notes": "Notes du modèle de contre-vérification",
        "not_run": "La contre-vérification EnergyPlus n'a pas été exécutée ; voir le journal.",
        "assemblies": "Assemblages", "name": "Nom", "desc": "Description", "windows": "Fenêtres et portes",
        "product": "Produit", "systems": "Étanchéité, ventilation et systèmes", "gains": "Répartition des gains internes",
        "occ": "Occupants", "appl": "Appareils", "item": "Élément", "stated": "Indiqué aux plans", "modelled": "Modélisé",
        "chain": "Chaîne de cotes", "sum_parts": "Somme des parties", "total": "Total", "span": "Étendue du modèle",
        "resolution": "Résolution", "glazing": "Vitrage par orientation", "wfr": "fenêtres / plancher",
        "excluded": "exclu de la comparaison", "ton": "tonne",
        "basis": "Comparaison à base égale : conduction de l'enveloppe hors sol + infiltration (+ gains internes et "
                 "solaires en climatisation). Les conduits et la ventilation mécanique sont exclus (modélisés par la "
                 "méthode principale seulement) ; le contact avec le sol est présenté séparément. Seuils de "
                 "signalement (règle empirique, non normative) : chauffage {h} %, climatisation {c} %.",
        "ground": "Contact avec le sol (dalles, murs de fondation) : méthode principale {mj} W, contre-vérification "
                  "{ep} W. Les méthodes diffèrent par conception (tables Manual J à la température extérieure de "
                  "calcul, ou valeurs U de type ISO 13370 avec une température de sol effective EN 12831) : cette "
                  "ligne est présentée côte à côte, sans comparaison.",
        "flag_h": "{room} : écart de {d} en chauffage entre les méthodes",
        "flag_c": "{room} : écart de {d} en climatisation sensible entre les méthodes",
        "flag_wh": "BÂTIMENT ENTIER : écart de {d} en chauffage entre les méthodes",
        "flag_wc": "BÂTIMENT ENTIER : écart de {d} en climatisation sensible entre les méthodes",
        "cats": {"walls": "murs", "ceilings/roofs": "plafonds / toits", "floors": "planchers",
                 "ground contact": "contact avec le sol", "windows": "fenêtres", "doors": "portes",
                 "infiltration": "infiltration", "ventilation": "ventilation", "ducts": "conduits",
                 "internal gains": "gains internes"},
        "keys": {"ach50": "CAH50", "cfm50": "PCM50", "leakiness": "étanchéité", "type": "type", "cfm": "débit (pcm)",
                 "lps": "débit (L/s)", "sre": "récupération sensible", "tre": "récupération totale",
                 "hours": "heures/jour", "distribution": "distribution", "ducts": "conduits", "location": "emplacement",
                 "supply_r_ip": "R alimentation", "return_r_ip": "R retour", "leakage_cfm25": "fuites (PCM25)",
                 "occupants": "occupants", "appliance_sensible_btuh": "appareils, sensible (Btu/h)",
                 "appliance_latent_btuh": "appareils, latent (Btu/h)"},
        "rows": {"airtightness": "Étanchéité à l'air", "ventilation": "Ventilation", "hvac": "CVCA",
                 "internal_gains": "Gains internes"},
        "vals": {"low": "faible", "medium": "moyen", "high": "élevé", "hrv": "VRC", "erv": "VRE",
                 "none": "aucune", "exhaust": "extraction", "supply": "alimentation", "balanced": "équilibrée",
                 "ducted": "à conduits", "ductless": "sans conduits", "hydronic": "hydronique",
                 "conditioned": "espace conditionné", "attic": "entretoit", "crawlspace": "vide sanitaire",
                 "garage": "garage", "basement": "sous-sol", "True": "oui", "False": "non"},
        "orient": {"N": "N", "E": "E", "S": "S", "W": "O"},
        "items": {"conditioned_area": "surface de plancher conditionnée", "garage_area": "surface du garage",
                  "glazing_area": "surface vitrée"},
        "explained": "expliqué", "station_only": "La station météo ne fournit que l'écart diurne, le modèle solaire et "
                      "les températures du sol ; les températures de conception ci-dessus proviennent des sources "
                      "indiquées.",
    },
}

CSS = """
:root{--ink:#1f2328;--muted:#5b636e;--line:#d8d4cc;--bg:#fff;--warn:#fff4e5;--warnb:#e0a64b;--bad:#fdecea;--badb:#d9534f}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--ink:#e8eaed;--muted:#9aa4b1;--line:#3a414b;--bg:#16191d;--warn:#3a2f1c;--bad:#3a1f1f}}
body{background:var(--bg);color:var(--ink);font:13.5px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:1000px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-bottom:2px solid var(--line);padding-bottom:4px}h3{font-size:14px;margin:16px 0 6px}
.meta{color:var(--muted)}table{border-collapse:collapse;width:100%;margin:6px 0 10px;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}th{font-weight:600;background:#8881}
td.n,th.n{text-align:right;white-space:nowrap}.box{border-left:4px solid var(--warnb);background:var(--warn);padding:8px 12px;margin:10px 0;border-radius:4px}
.box.bad{border-color:var(--badb);background:var(--bad)}.box.info{border-color:#6b8fb3;background:#6b8fb31a}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:10px 0}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px}.kpi b{font-size:20px;display:block}.kpi span{color:var(--muted);font-size:12px}
.small{font-size:12px;color:var(--muted)}ul{margin:4px 0 8px 18px;padding:0}.muted{color:var(--muted)}
@media print{body{max-width:none;padding:0}h2{break-after:avoid}tr{break-inside:avoid}}
"""


def _t(x) -> str:
    return html.escape(str(x))


class Fmt:
    """Language-aware numbers and units (French: narrow no-break space thousands, decimal comma)."""

    def __init__(self, lang: str, ip: bool):
        self.fr, self.ip = lang == "fr", ip

    def n(self, v, nd=0) -> str:
        if v is None:
            return "–"
        s = f"{v:,.{nd}f}"
        return s.replace(",", "\u202f").replace(".", ",") if self.fr else s

    def pct(self, v) -> str:
        if v is None:
            return "–"
        return f"{'−' if v < 0 else '+'}{self.n(abs(100 * v))} %"

    def load(self, w) -> str:
        return f"{self.n(w / W_PER_BTUH)} Btu/h" if self.ip else f"{self.n(w)} W"

    def area(self, m2) -> str:
        return f"{self.n(m2 * 10.7639)} ft²" if self.ip else f"{self.n(m2, 1)} m²"

    def temp(self, c) -> str:
        return f"{self.n(c, 1)} °C ({self.n(c_to_f(c), 1)} °F)"

    def flow(self, cfm) -> str:
        return f"{self.n(cfm)} cfm" if self.ip else f"{self.n(cfm * 0.4719)} L/s"


def _kv(d: dict, T: dict, F: Fmt) -> str:
    parts = []
    for k, v in d.items():
        if k == "src":
            continue
        label = T["keys"].get(k, k.replace("_", " "))
        tv = lambda x: T["vals"].get(str(x), x) if not isinstance(x, float) else F.n(x, 2)  # noqa: E731
        if isinstance(v, dict):
            v = ", ".join(f"{T['keys'].get(k2, k2)}: {tv(v2)}" for k2, v2 in v.items() if k2 != "src")
        else:
            v = tv(v)
        parts.append(f"{_t(label)}: {_t(v)}")
    return "; ".join(parts)


def build(b: Building, geo: dict, design: dict, mj: dict, comp: dict, ep_meta: dict, qa: dict, rooms: list,
          sanity: dict, meta: dict, out_html: Path, lang: str = "en") -> str:
    T = L.get(lang, L["en"])
    ip = (b.raw.get("project", {}).get("units_system") or ("SI" if b.is_canada else "IP")).upper() == "IP"
    F = Fmt(lang, ip)
    cat = lambda k: T["cats"].get(k, k)  # noqa: E731
    tot = mj.get("total", {})
    h, cs, cl = tot.get("heating_w", 0.0), tot.get("cooling_sensible_w", 0.0), tot.get("cooling_latent_w", 0.0)
    out = [f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'><meta name='viewport' "
           f"content='width=device-width,initial-scale=1'><title>{_t(b.name)}</title><style>{CSS}</style></head><body>"]
    proj = b.raw.get("project", {})
    out.append(f"<h1>{_t(T['title'])}</h1><div class='meta'>{_t(b.name)}"
               f"{' · ' + _t(proj['address']) if proj.get('address') else ''} · {T['generated']} {date.today().isoformat()}</div>")
    out.append(f"<div class='box info'><b>{T['notice_h']}.</b> {_t(T['notice'])}</div>")
    src = b.raw.get("source", {})
    if src.get("kind") in ("raster", "mixed"):
        conf = src.get("geometry_confirmed")
        extra = T["raster_ok"].format(date=_t(conf)) if conf else T["raster_no"]
        out.append(f"<div class='box bad'>{_t(T['raster'])} {extra}</div>")

    from .results import COOL_FLAG, HEAT_FLAG
    rname = {r.id: r.name for r in b.rooms}
    notes = b.raw.get("crosscheck_notes") or {}
    flags, explained = [], []
    if comp.get("available"):
        if comp.get("delta_heating") is not None and abs(comp["delta_heating"]) > HEAT_FLAG:
            flags.append(T["flag_wh"].format(d=F.pct(comp["delta_heating"])))
        if comp.get("delta_cooling") is not None and abs(comp["delta_cooling"]) > COOL_FLAG:
            flags.append(T["flag_wc"].format(d=F.pct(comp["delta_cooling"])))
        for r in comp["rooms"]:
            dh, dc = r["delta_heating"], r["delta_cooling"]
            if dh is not None and abs(dh) > HEAT_FLAG and abs(r["ep_heating_w"] - r["mj_heating_like_w"]) > 150:
                flags.append((r["room"], T["flag_h"].format(room=rname.get(r["room"], r["room"]), d=F.pct(dh))))
            if dc is not None and abs(dc) > COOL_FLAG and abs(r["ep_cooling_w"] - r["mj_cooling_like_w"]) > 150:
                flags.append((r["room"], T["flag_c"].format(room=rname.get(r["room"], r["room"]), d=F.pct(dc))))
    flags = [("whole", f) if isinstance(f, str) else f for f in flags]
    open_flags = [f for key, f in flags if not notes.get(key)]
    explained = [f"{f} — {T['explained']} : {notes[key]}" if lang == "fr" else f"{f} — {T['explained']}: {notes[key]}"
                 for key, f in flags if notes.get(key)]
    review = list(qa.get("errors", [])) + open_flags
    soft = [w for w in qa.get("warnings", []) if not w.startswith("RASTER")]
    if review or soft or explained:
        out.append(f"<h2>{T['warnings']}</h2>")
        if review:
            out.append("<div class='box bad'><ul>" + "".join(f"<li>{_t(x)}</li>" for x in review) + "</ul></div>")
        if soft:
            out.append("<div class='box'><ul>" + "".join(f"<li>{_t(x)}</li>" for x in soft) + "</ul></div>")
    if explained:
        out.append("<div class='box info'><ul>" + "".join(f"<li>{_t(x)}</li>" for x in explained) + "</ul></div>")

    # summary
    out.append(f"<h2>{T['summary']}</h2><div class='kpis'>")
    for label, w in ((T["heating"], h), (T["cool_s"], cs), (T["cool_l"], cl), (T["cool_t"], cs + cl)):
        extra = f" · {F.n((w / W_PER_BTUH) / 12000, 2)} {T['ton']}" if label == T["cool_t"] else ""
        out.append(f"<div class='kpi'><span>{_t(label)}</span><b>{F.n(w / 1000, 2)} kW</b>"
                   f"<span>{F.n(w / W_PER_BTUH)} Btu/h{extra}</span></div>")
    out.append("</div>")
    out.append(f"<p class='small'>{T['method']}: {_t(mj.get('method', ''))}"
               f"{' – ' + _t(design.get('label')) if design.get('label') else ''}. {_t(design.get('method_note', ''))}</p>")
    out.append(f"<h3>{T['ratios']}</h3><table>"
               f"<tr><th>{T['area']}</th><td class='n'>{F.n(sanity['conditioned_area_m2'], 1)} m² "
               f"({F.n(sanity['conditioned_area_ft2'])} ft²)</td></tr>"
               f"<tr><th>{T['heating']}</th><td class='n'>{F.n(sanity['heating_w_per_m2'], 1)} W/m² "
               f"({F.n(sanity['heating_btuh_per_ft2'], 1)} Btu/h·ft²)</td></tr>"
               f"<tr><th>{T['cool_s']}</th><td class='n'>{F.n(sanity['cooling_w_per_m2'], 1)} W/m²</td></tr>"
               f"<tr><th>ft²/{T['ton']}</th><td class='n'>{F.n(sanity['ft2_per_ton']) if sanity['ft2_per_ton'] else '–'}</td></tr>"
               f"<tr><th>SHR</th><td class='n'>{F.n(sanity['sensible_heat_ratio'], 2) if sanity['sensible_heat_ratio'] else '–'}</td></tr></table>")

    # design conditions
    dsrc = design.get("sources", {})
    out.append(f"<h2>{T['design']}</h2><table><tr><th></th><th>{T['heating']}</th><th>{T['cool_s']}</th><th>{T['source']}</th></tr>")
    out.append(f"<tr><th>{T['outdoor']}</th><td>{F.temp(design['heating_c'])}</td><td>{F.temp(design['cooling_c'])} DB / "
               f"{F.temp(design['cooling_wb_c'])} WB</td><td class='small'>{_t(dsrc.get('heating_outdoor', ''))}<br>"
               f"{_t(dsrc.get('cooling_outdoor', ''))}<br>{_t(dsrc.get('cooling_wetbulb', ''))}</td></tr>")
    out.append(f"<tr><th>{T['indoor']}</th><td>{F.temp(design['indoor_heating_c'])}</td><td>{F.temp(design['indoor_cooling_c'])}, "
               f"{F.n(design['indoor_rh'] * 100)} % {T['rh']}</td><td></td></tr>")
    out.append(f"<tr><th>{T['daily_range']}</th><td></td><td>{F.n(design['daily_range_c'], 1)} K "
               f"({_t(T['vals'].get(design['daily_range_class'], design['daily_range_class']))})</td><td></td></tr>"
               f"<tr><th>{T['dhum']}</th><td></td><td>{F.n(design['humidity_difference_gr'], 1)} gr/lb</td><td></td></tr></table>")
    w = design.get("weather", {})
    if w.get("source_url") or w.get("station"):
        dist = design.get("station_distance_km")
        ashrae = all("ASHRAE" in str(dsrc.get(k, "")) for k in ("heating_outdoor", "cooling_outdoor"))
        out.append(f"<p class='small'>{T['weather']}: {_t(w.get('station', ''))}"
                   f"{f' ({F.n(dist, 1)} km)' if dist is not None else ''} — "
                   f"{_t(T['weather_note'] if ashrae else T['station_only'])}</p>")

    # rooms
    out.append(f"<h2>{T['rooms']}</h2><table><tr><th>{T['room']}</th><th class='n'>{T['area']}</th>"
               f"<th class='n'>{T['heating']}</th><th class='n'>{T['cool_s']}</th>"
               f"<th class='n'>W/m² (H / C)</th><th class='n'>{T['cfm_h']}</th><th class='n'>{T['cfm_c']}</th></tr>")
    for r in rooms:
        out.append(f"<tr><td>{_t(r['name'])}</td><td class='n'>{F.area(r['floor_area_m2'])}</td>"
                   f"<td class='n'>{F.load(r['heating_w'])}</td><td class='n'>{F.load(r['cooling_sensible_w'])}</td>"
                   f"<td class='n'>{F.n(r['heating_w_per_m2'])} / {F.n(r['cooling_w_per_m2'])}</td>"
                   f"<td class='n'>{F.flow(r['heating_cfm'])}</td><td class='n'>{F.flow(r['cooling_cfm'])}</td></tr>")
    out.append(f"<tr><th>{T['whole']}</th><th></th><th class='n'>{F.load(h)}</th><th class='n'>{F.load(cs)}</th>"
               f"<th colspan='3' class='n'>{T['cool_l']} : {F.load(cl)}</th></tr></table>" if lang == "fr" else
               f"<tr><th>{T['whole']}</th><th></th><th class='n'>{F.load(h)}</th><th class='n'>{F.load(cs)}</th>"
               f"<th colspan='3' class='n'>{T['cool_l']}: {F.load(cl)}</th></tr></table>")
    af = b.raw.get("airflow", {})
    dth, dtc = float(af.get("heating_supply_dt_f", 50)), float(af.get("cooling_supply_dt_f", 20))
    dt_txt = (lambda df: f"{F.n(df)} °F") if ip else (lambda df: f"{F.n(df / 1.8, 1)} K")
    out.append(f"<p class='small'>{_t(T['airflow_note'].format(dth=dt_txt(dth), dtc=dt_txt(dtc)))}</p>")

    # components (whole-house block load, as reported)
    from .results import EXCLUDED_FROM_CROSSCHECK, ground_ids, mj_by_category
    gids = ground_ids(geo)
    agg_h = mj_by_category(tot, "heating", gids) if tot.get("components") else {}
    agg_c = mj_by_category(tot, "cooling", gids) if tot.get("components") else {}
    if not agg_h:
        for rr in mj.get("rooms", {}).values():
            for k, v in mj_by_category(rr, "heating", gids).items():
                agg_h[k] = agg_h.get(k, 0) + v
            for k, v in mj_by_category(rr, "cooling", gids).items():
                agg_c[k] = agg_c.get(k, 0) + v
    out.append(f"<h2>{T['components']}</h2><table><tr><th>{T['category']}</th><th class='n'>{T['heating']}</th>"
               f"<th class='n'>{T['cool_s']}</th></tr>")
    for k in sorted(set(agg_h) | set(agg_c), key=lambda k: -agg_h.get(k, 0)):
        if abs(agg_h.get(k, 0)) < 0.5 and abs(agg_c.get(k, 0)) < 0.5:
            continue
        out.append(f"<tr><td>{_t(cat(k))}</td><td class='n'>{F.load(agg_h.get(k, 0))}</td>"
                   f"<td class='n'>{F.load(agg_c.get(k, 0))}</td></tr>")
    out.append(f"</table><p class='small'>{_t(T['comp_note'])}</p>")

    # cross-check
    out.append(f"<h2>{T['cross']}</h2>")
    if comp.get("available"):
        tt = comp["totals"]
        dh, dc = comp.get("delta_heating"), comp.get("delta_cooling")
        from .results import COOL_FLAG, HEAT_FLAG
        basis = T["basis"].format(h=int(HEAT_FLAG * 100), c=int(COOL_FLAG * 100))
        out.append(f"<p>{_t(basis)}</p><table><tr><th></th><th class='n'>Manual J ({T['like']})</th>"
                   f"<th class='n'>EnergyPlus ({T['like']})</th><th class='n'>{T['delta']}</th></tr>"
                   f"<tr><th>{T['heating']}</th><td class='n'>{F.n(tt['mj_h'])} W</td><td class='n'>{F.n(tt['ep_h'])} W</td>"
                   f"<td class='n'>{F.pct(dh)}</td></tr>"
                   f"<tr><th>{T['cool_s']}</th><td class='n'>{F.n(tt['mj_c'])} W</td><td class='n'>{F.n(tt['ep_c'])} W</td>"
                   f"<td class='n'>{F.pct(dc)}</td></tr></table>")
        if comp.get("ground_note"):
            gnote = T["ground"].format(mj=F.n(tt.get("mj_ground_h", 0)), ep=F.n(tt.get("ep_ground_h", 0)))
            out.append(f"<div class='box info'>{_t(gnote)}</div>")
        out.append(f"<h3>{T['rooms_h']} (W)</h3><table><tr><th>{T['room']}</th><th class='n'>MJ {T['heating']}</th>"
                   f"<th class='n'>E+ {T['heating']}</th><th class='n'>Δ</th><th class='n'>MJ {T['cool_s']}</th>"
                   f"<th class='n'>E+ {T['cool_s']}</th><th class='n'>Δ</th></tr>")
        for r in comp["rooms"]:
            out.append(f"<tr><td>{_t(rname.get(r['room'], r['room']))}</td><td class='n'>{F.n(r['mj_heating_like_w'])}</td>"
                       f"<td class='n'>{F.n(r['ep_heating_w'])}</td><td class='n'>{F.pct(r['delta_heating'])}</td>"
                       f"<td class='n'>{F.n(r['mj_cooling_like_w'])}</td><td class='n'>{F.n(r['ep_cooling_w'])}</td>"
                       f"<td class='n'>{F.pct(r['delta_cooling'])}</td></tr>")
        out.append("</table>")
        for which, lab in (("heating", T["heating"]), ("cooling", T["cool_s"])):
            out.append(f"<h3>{T['cat_h']} – {_t(lab)} (W)</h3><table><tr><th>{T['category']}</th>"
                       "<th class='n'>Manual J</th><th class='n'>EnergyPlus</th><th></th></tr>")
            for k, v in comp["categories"][which].items():
                if abs(v["mj_w"]) < 0.5 and abs(v["ep_w"]) < 0.5:
                    continue
                ex = T["excluded"] if k in EXCLUDED_FROM_CROSSCHECK else ""
                out.append(f"<tr><td>{_t(cat(k))}</td><td class='n'>{F.n(v['mj_w'])}</td><td class='n'>{F.n(v['ep_w'])}</td>"
                           f"<td class='small'>{ex}</td></tr>")
            out.append("</table>")
        if ep_meta.get("notes"):
            out.append(f"<p class='small'>{T['ep_notes']}:</p><ul class='small'>" +
                       "".join(f"<li>{_t(n)}</li>" for n in ep_meta["notes"]) + "</ul>")
    else:
        out.append(f"<div class='box'>{T['not_run']}</div>")

    # inputs
    out.append(f"<h2>{T['inputs']}</h2><h3>{T['assemblies']}</h3><table><tr><th>{T['name']}</th><th class='n'>U (W/m²K)</th>"
               f"<th class='n'>R (IP)</th><th class='n'>RSI</th><th>{T['desc']}</th><th>{T['source']}</th></tr>")
    for name, a in b.assemblies.items():
        u = a.get("u_si")
        out.append(f"<tr><td>{_t(name)}</td><td class='n'>{F.n(u, 3) if u else ''}</td>"
                   f"<td class='n'>{F.n(5.678263 / u, 1) if u else ''}</td><td class='n'>{F.n(1 / u, 2) if u else ''}</td>"
                   f"<td>{_t(a.get('desc', ''))}</td><td class='small'>{_t(a.get('src', '—'))}</td></tr>")
    out.append(f"</table><h3>{T['windows']}</h3><table><tr><th>{T['product']}</th><th class='n'>U (W/m²K)</th>"
               f"<th class='n'>U (IP)</th><th class='n'>SHGC</th><th>{T['source']}</th></tr>")
    for name, f in b.fenestration.items():
        out.append(f"<tr><td>{_t(name)}</td><td class='n'>{F.n(f['u_si'], 2)}</td><td class='n'>{F.n(f['u_si'] / 5.678263, 3)}</td>"
                   f"<td class='n'>{F.n(float(f.get('shgc', 0)), 2)}</td><td class='small'>{_t(f.get('src', '—'))}</td></tr>")
    out.append("</table>")
    rows = []
    for key in ("airtightness", "ventilation", "hvac", "internal_gains"):
        v = b.raw.get(key)
        if isinstance(v, dict) and v:
            rows.append(f"<tr><th>{_t(T['rows'][key])}</th><td>{_kv(v, T, F)}</td>"
                        f"<td class='small'>{_t(v.get('src', '—'))}</td></tr>")
    out.append(f"<h3>{T['systems']}</h3><table>" + "".join(rows) + "</table>")
    gains = design["internal_gains"]
    out.append(f"<h3>{T['gains']}</h3><table><tr><th>{T['room']}</th><th class='n'>{T['occ']}</th>"
               f"<th class='n'>{T['appl']} (Btu/h)</th></tr>" +
               "".join(f"<tr><td>{_t(rname.get(k, k))}</td><td class='n'>{F.n(v['occupants'], 1)}</td><td class='n'>{F.n(v['sensible_btuh'])}</td></tr>"
                       for k, v in gains["per_room"].items() if v["occupants"] or v["sensible_btuh"]) + "</table>")

    # QA
    info = qa.get("info", {})
    out.append(f"<h2>{T['qa']}</h2>")
    if info.get("reconciliation"):
        out.append(f"<table><tr><th>{T['item']}</th><th class='n'>{T['stated']}</th><th class='n'>{T['modelled']}</th>"
                   f"<th class='n'>Δ</th><th>{T['resolution']}</th></tr>" +
                   "".join(f"<tr><td>{_t(T['items'].get(r['item'], r['item']))}</td><td class='n'>{F.n(r['stated'], 1)}</td><td class='n'>{F.n(r['modelled'], 1)}</td>"
                           f"<td class='n'>{F.pct(r['delta_pct'] / 100)}</td><td class='small'>{_t(r.get('resolution') or '')}</td></tr>"
                           for r in info["reconciliation"]) + "</table>")
    if info.get("dimension_chains"):
        def chain_row(c):
            total = "" if c["total"] is None else F.n(c["total"], 3)
            flag = " ⚠" if c.get("drawing_inconsistent") else ""
            return (f"<tr><td>{_t(c['label'])}{flag}</td><td class='n'>{F.n(c['sum_parts'], 3)}</td>"
                    f"<td class='n'>{total}</td><td class='n'>{F.n(c['model_span'], 3) if 'model_span' in c else ''}</td>"
                    f"<td class='small'>{_t(c.get('resolution') or '')}</td></tr>")
        out.append(f"<table><tr><th>{T['chain']}</th><th class='n'>{T['sum_parts']}</th><th class='n'>{T['total']}</th>"
                   f"<th class='n'>{T['span']}</th><th>{T['resolution']}</th></tr>" +
                   "".join(chain_row(c) for c in info["dimension_chains"]) + "</table>")
    gz = info.get("glazing_by_orientation", {})
    units = info.get("modelled", {}).get("units", "")
    out.append(f"<p class='small'>{T['glazing']} ({_t(units)}): " + ", ".join(f"{T['orient'].get(k, k)} {F.n(v, 1)}" for k, v in gz.items()) +
               f"; {T['wfr']} {F.n(info.get('window_to_floor_pct'), 1)} %.</p>")

    # assumptions
    out.append(f"<h2>{T['assump']}</h2><ul>")
    for a in b.raw.get("assumptions", []):
        if isinstance(a, dict):
            out.append(f"<li><b>{_t(a.get('item', ''))}</b>: {_t(a.get('value', ''))} — {_t(a.get('basis', ''))}</li>")
        else:
            out.append(f"<li>{_t(a)}</li>")
    for d in design.get("defaults_applied", []):
        out.append(f"<li class='muted'>{_t(d)}</li>")
    out.append("</ul>")

    out.append(f"<h2>{T['files']}</h2><table>" + "".join(f"<tr><th>{_t(k)}</th><td class='small'>{_t(v)}</td></tr>"
                                                          for k, v in meta.items()) + "</table></body></html>")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text("".join(out), encoding="utf-8")
    return str(out_html)


def _browser() -> str | None:
    cands = [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")]
    cands += [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in cands if c and os.path.exists(c)), None)


def screenshot(html_path: Path, png_path: Path, query: str = "", size=(1400, 900), wait_ms: int = 12000) -> str | None:
    """Render a page (e.g. the 3D viewer with ?view=top&level=L1) to PNG with a headless Chromium browser.
    Needs internet access for three.js (CDN)."""
    exe = _browser()
    if not exe:
        return None
    if png_path.exists():
        png_path.unlink()
    url = html_path.resolve().as_uri() + (f"?{query}" if query else "")
    subprocess.run([exe, "--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                    "--hide-scrollbars", f"--window-size={size[0]},{size[1]}", f"--virtual-time-budget={wait_ms}",
                    f"--screenshot={png_path.resolve()}", url], capture_output=True, timeout=180)
    last = -1
    for _ in range(60):
        if png_path.exists():
            s = png_path.stat().st_size
            if s > 0 and s == last:
                return str(png_path)
            last = s
        time.sleep(0.5)
    return None


def to_pdf(html_path: Path, pdf_path: Path) -> str | None:
    """Print the HTML report to PDF with a local Chromium browser, if one is installed."""
    cands = [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")]
    cands += [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    exe = next((c for c in cands if c and os.path.exists(c)), None)
    if not exe:
        return None
    if pdf_path.exists():
        pdf_path.unlink()  # never report a stale PDF from an earlier run
    subprocess.run([exe, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path.resolve()}", html_path.resolve().as_uri()], capture_output=True, timeout=180)
    # the Windows Edge launcher can return before the file is written: wait for a stable file
    last = -1
    for _ in range(120):
        if pdf_path.exists():
            size = pdf_path.stat().st_size
            if size > 0 and size == last:
                return str(pdf_path)
            last = size
        time.sleep(0.5)
    return None
