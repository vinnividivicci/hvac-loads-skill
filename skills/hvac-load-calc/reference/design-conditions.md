# Design conditions and method choice

The design temperature alone can move a heating load by ±10–20%. Always pick it **explicitly**, record its **source**, and have the user confirm it.

## Never rely on the weather file header

OpenStudio 3.11 cannot parse the 2025-format `DESIGN CONDITIONS` header in current climate.onebuilding.org EPWs. OpenStudio-HPXML then silently computes its own values from the 8,760 hours; for Montréal that gives −18.8 °C instead of −23 °C. `hvacload.py` always writes the design temperatures into the model, so this cannot happen. Don't remove them.

## Choosing the method and conditions

| Situation | Heating outdoor | Indoor heating | Cooling | Label in report |
|---|---|---|---|---|
| **US project** (Manual J) | ASHRAE 99% DB (`--heating 99`) | 70 °F | ASHRAE 1% DB + MCWB (`--cooling 1`), 75 °F, 50% RH | "ACCA Manual J method, ASHRAE {edition} 99%/1%" |
| **Canada, no CSA F280 available** (default) | **NBC Table C-2 January 2.5%** for the municipality | **22 °C** | NBC July 2.5% dry / wet bulb | "Manual J method at NBC design conditions (**not** a CSA F280 calculation)" |
| **Engineer supplies their own data** | as given | as given | as given | "{method} at engineer-supplied conditions" + their source |
| **Canada, user supplies CSA F280** | per F280 and NBC | per F280 | per F280 | see the F280 policy below |

Commands:

```bash
uv run scripts/hvacload.py weather --lat 45.47 --lon -73.74 --country Canada        # nearest stations
uv run scripts/hvacload.py weather --url <zip-url> --project <p> --write \
   --heating-c -23 --heating-src "NBC 2020 Table C-2, Montréal, January 2.5%" \
   --cooling-c 30 --cooling-src "NBC 2020 Table C-2, Montréal, July 2.5% dry" \
   --wetbulb-c 23 --wetbulb-src "NBC 2020 Table C-2, Montréal, July 2.5% wet" \
   --indoor-heating-c 22 --indoor-src "NBC 9.33.3 / CSA F280 practice" \
   --label "Manual J method at NBC design conditions (not F280)"
```

- The EPW, DDY and STAT are still downloaded; the calculation uses them for ground temperatures, the annual mean and solar.
- The daily range and the cooling solar day (clear-sky optical depths) come from the ASHRAE design day in the DDY.

## Where the values come from

- **ASHRAE (US and elsewhere):** the DDY file of the nearest OneBuilding station, parsed by `weather`.
  - Pass the **site** `--lat/--lon` (and `--site-elevation-m`) together with `--url`, so the distance is recorded and elevation differences are flagged.
  - Report the station name, WMO number, distance and elevation difference. If the site is more than about 25 km or 100 m of elevation from the station, tell the user and consider a closer station.
  - `--write` replaces every station-derived value, including the climate zone, and warns if the station changed. Indoor setpoints are kept unless passed.
- **NBC Table C-2 (Canada):** `uv run scripts/hvacload.py nbc --place "Montréal"` returns the printed row with its page number, from the free NBC 2020 PDF.
  - The PDF is downloaded once from the NRC Publications Archive, <https://nrc-publications.canada.ca/eng/view/ft/?id=515340b5-f4e0-4798-be69-692e4ec423e8>, or use `--pdf` with the user's copy.
  - Check the row on the page (`pdf-render ~/.hvacload/codes/nbc2020.pdf --page N`), then cite "NBC 2020, Div. B, Appendix C, Table C-2, <entry>".
  - Ask the user to confirm it. Quebec's Code de construction, Chapitre I uses the same Appendix C values.
  - The PCIC Design Value Explorer can export Table C-2 values.
  - If the municipality isn't listed, Appendix C says to use the nearest listed location or values from Environment and Climate Change Canada. Say which you used.
- **Engineer's data:** many engineers use their firm's design-condition tables. Accept them and record the source they give.

Montréal example (NBC 2020): January 2.5% −23 °C, January 1% −26 °C, July 2.5% 30 °C dry / 23 °C wet, about 4,200 HDD (energy zone 6). ASHRAE 2025 at Montréal-Trudeau: 99.6% −22.3 °C, 99% −19.5 °C. **Show the user the spread** when the sources disagree.

## CSA F280 policy

CSA F280 is a paid, copyrighted standard. This skill contains **no F280 content** and does not implement it.

For every Canadian project, **ask**: "Do you have a copy of CSA F280 (current edition) that you want the calculation to follow? If not, I'll run the Manual J method at NBC design conditions and label it clearly as not an F280 calculation."

- **No**: use the default row above. The report states the method is not F280.
- **Yes**: the user decides whether to share their copy with you.
  1. If they do, use it only inside this project: the Manual J and EnergyPlus runs, plus `out/takeoff.csv` (areas, U-values, UA per surface), give you the quantities.
  2. Apply F280's procedures in a project-local script or spreadsheet that the user keeps. Cite clause numbers, don't reproduce the standard's text, and never copy F280 material into the skill or the repository.
  3. Label the results with the F280 edition and the clauses applied, and say that software verification (HRAI or other) has not been done.

## Wet bulb for latent loads

- The NBC July 2.5% **wet** bulb is a separate design value, not coincident with the dry bulb. Used with the NBC dry bulb, it overstates latent loads compared with ASHRAE's mean coincident wet bulb (MCWB). In Montréal/Laval it gives about 42 gr/lb against about 30 gr/lb.
- `weather --write` prints both in `comparison_c`. Show the user the spread.
- Default recommendation: the NBC dry bulb (if following NBC practice) and the **ASHRAE 1% MCWB** for latent. Say so in `src`. Use the NBC wet bulb only if the user asks for it.

## Indoor conditions and humidity

- Manual J setpoints are 70 °F heating and 75 °F / 50% RH cooling, or 45% RH in dry climates. Other setpoints are allowed but not Manual J-compliant; the report shows them.
- The humidity difference (grains) for latent loads is computed from the cooling design dry bulb, the MCWB and the site pressure. A negative value, as in a dry climate, means no latent infiltration load.

## Code context (tell the user; don't decide for them)

- **US:** IRC M1401.3 requires heating and cooling equipment to be sized per ACCA Manual S from loads per ACCA Manual J or another approved method. Jurisdictions may require an ACCA-approved software report.
- **Canada:** NBC 9.33.5.1 requires heating capacity per CSA F280. Quebec's Chapitre I adopts the NBC with modifications; confirm applicability with the user and the authority having jurisdiction.
- This skill's output is a professional's **design aid** in either case: it is not ACCA-approved or F280-verified.
