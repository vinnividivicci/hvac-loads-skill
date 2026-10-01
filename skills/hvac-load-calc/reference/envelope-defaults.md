# Envelope values: where they come from

## Priority

1. **The plans or specifications**, e.g. "R-13", "R-30", "RSI 4.93", window schedule U/SHGC.
2. **The user**, for product data, energy-model reports or blower-door results.
3. **Code minimum for the jurisdiction and permit date.** Look it up at run time (see below) and cite the edition and clause.
4. **Typical values** for the construction era, flagged as assumptions.

Always convert nominal insulation to an **effective, whole-assembly value** that includes framing and air films:

```bash
uv run scripts/hvacload.py assembly --layers "outside:0.17,siding:0.78,studs:13|4.38@0.25,gypsum:0.45,inside:0.68"
# -> r_ip 11.3 (2x4@16 R-13 batt, 25 % framing)
```

Canadian codes already state **effective** RSI minimums. US IECC R-value tables give **nominal** values; the U-factor tables are whole-assembly.

- **Air films.** `building.json` wants overall values *including* air films. Check whether a code's tabulated value includes them (NBC: the calculation method in A-9.36.2.4). If it doesn't, add inside 0.12 m²K/W (R-0.68) for walls, 0.11 for ceilings (heat up) and 0.16 for floors (heat down), plus outside 0.03 (R-0.17). A film-exclusive value used as-is overstates the load slightly.
- **Quebec floors over a crawlspace or unheated space:** use the *effective* 5.02 (Table 9.36.2.6.-B) for modelling. The 5.20 in Table -A is a prescriptive *total* for exposed floors.

## Verified code values

These are **starting points**. Check the edition in force for the permit and cite it.

### NBC 2020 / 2025, Section 9.36 (prescriptive; zones by HDD)

Zones: 4 < 3000 HDD; 5 = 3000–3999; 6 = 4000–4999; 7A = 5000–5999; 7B = 6000–6999; 8 ≥ 7000. Montréal (about 4,200 HDD) is zone 6; Québec City (5,080 HDD) is 7A.

| Minimum effective RSI (m²K/W) | Z4 | Z5 | Z6 | Z7A | Z7B | Z8 |
|---|---|---|---|---|---|---|
| Attic ceilings | 6.91 | 8.67 | 8.67 | 10.43 | 10.43 | 10.43 |
| Cathedral / flat roofs | 4.67 | 4.67 | 4.67 | 5.02 | 5.02 | 5.02 |
| Above-grade walls, no HRV (Table 9.36.2.6.-A) | 2.78 | 3.08 | 3.08 | 3.08 | 3.85 | 3.85 |
| Above-grade walls, with HRV (Table 9.36.2.6.-B) | 2.78 | 2.97 | 2.97 | 2.97 | 3.08 | 3.08 |
| Floors over unheated space | 4.67 | 4.67 | 4.67 | 5.02 | 5.02 | 5.02 |
| Foundation walls (9.36.2.8.-A) | 1.99 | 2.98 | 2.98 | 3.46 | 3.46 | 3.97 |
| Windows / doors, maximum U (W/m²K) | 1.84 | 1.84 | 1.61 | 1.61 | 1.44 | 1.44 |

Airtightness: the 9.36.5 performance path uses 3.2 ACH50 as the proposed-house default (2.5 with specified air-barrier details). Source: NBC 2020 (NRC, free PDF), as summarised in the project research notes.

### Quebec: Code de construction, Chapitre I (CNB 2020 modifié), Section 9.36 as modified

This applies to houses of at most 600 m² and 3 storeys. The previous edition may apply to work started before 2027-10-17; check the permit date.

| Item | < 6000 HDD | ≥ 6000 HDD |
|---|---|---|
| Attic or cathedral ceiling, **total** RSI (Table 9.36.2.6.-A, prescriptive) | 7.22 | 9.00 |
| Above-grade walls, total RSI (prescriptive) | 4.31 | 5.11 |
| Exposed floors | 5.20 | 5.20 |
| **Effective** RSI walls / floors / ceilings (Table 9.36.2.6.-B) | 3.70 / 5.02 / 7.22 | 3.96 / 5.02 / 9.00 |
| Windows and glazed doors | U ≤ 2.0 W/m²K, ER ≥ 21 | U ≤ 2.0, ER ≥ 25 |
| Opaque doors | U ≤ 0.9 | U ≤ 0.8 |
| Concrete foundation walls | RSI 2.99 | RSI 2.99 |
| Heated floors / slab with integral footing | RSI 1.76 | RSI 1.76 |

- There is **no ACH50 requirement** for small houses. Ask; typical anchors are 2.5–3.5 ACH50 for new code-built houses, and Novoclimat certification requires ≤ 1.5 ACH50 (detached).
- Sources: RBQ, Chapitre I – Bâtiment; RBQ small-buildings energy page; Novoclimat technical requirements (2024).
- Values were read from PDF layout: **verify against the code text before relying on them.**

### US IECC 2021, Table R402.1.2 (maximum assembly U-factors), zones 5–8 (as adopted in CT)

| Zone | Fenestration U | Ceiling | Frame wall | Floor | Basement wall |
|---|---|---|---|---|---|
| 5 / 4C | 0.30 | 0.024 | 0.045 | 0.033 | 0.050 |
| 6 | 0.30 | 0.024 | 0.045 | 0.033 | 0.050 |
| 7–8 | 0.30 | 0.024 | 0.045 | 0.028 | 0.050 |

- Prescriptive air leakage: ≤ 3.0 ACH50 in zones 3–8 (≤ 5.0 on other paths).
- 2024 IECC (per the NAHB summary): fenestration U 0.28 in zones 5–6 and 0.27 in zones 7–8, attic R-49, 2.5 ACH50 in zones 6–8.
- For **other zones, other states and California (Title 24, not IECC)**, look the values up (below).

## Looking up values at run time

Search the adopted code for the jurisdiction and permit date, and cite what you used:
- **US**: DOE energycodes.gov (public domain; state adoption status and compliance guides), the state's adopted IECC edition (UpCodes has viewable text), California Title 24 Part 6 prescriptive tables.
- **Canada**: NBC (NRC Publications Archive, free), provincial adoptions (Quebec: RBQ Chapitre I; Ontario SB-12; BC Step Code).
- Record the value, edition and clause in the assembly's `src`. If you can't confirm a value, say so and ask the user.

## Typical values (use only when nothing better exists; flag as assumptions)

| Layer | R (IP) | Layer | R (IP) |
|---|---|---|---|
| Inside air film, wall | 0.68 | Outside air film (15 mph) | 0.17 |
| Inside air film, ceiling (heat up) | 0.61 | 1/2" gypsum | 0.45 |
| 5/8" gypsum | 0.56 | 1/2" plywood / 7/16" OSB | 0.62 |
| 5/8" T1-11 plywood siding | 0.78 | Vinyl siding | 0.61 |
| Softwood framing, per inch | 1.25 | Concrete, per inch | about 0.08 |
| Carpet + pad | about 2.0 | Asphalt shingles + 1/2" ply deck | about 0.9 |
| Inside air film, floor (heat down) | 0.92 | Uninsulated steel overhead garage door | about 1 (U ≈ 1.0) |
| Insulated steel overhead door (1-3/8" foam) | about 6 | Single glazing, metal frame | U ≈ 1.1 |

Typical framing fractions (plates, headers and studs included): about 25% for walls at 16" o.c., about 22% at 24" o.c., about 10% for ceilings and floors at 16–24" o.c. Replace any of these with product data when available.

Windows by era, when unknown: single clear about U 1.0 / SHGC 0.75; double clear about U 0.5 / SHGC 0.6; double low-e about U 0.30–0.35 / SHGC 0.25–0.4; triple low-e about U 0.18–0.22 (1.0–1.25 W/m²K). **Ask**: glazing is often the largest room-by-room cooling term.
