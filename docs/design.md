# Design notes

## Principles

1. **One geometry, many consumers.** `building.json` holds rooms as plan polygons, heights and openings. `geometry.build` turns it into typed 3D surfaces. The HPXML writer, the EnergyPlus writer, the takeoff CSV and the 3D viewer all read that same list, so what you see is what was calculated.
2. **Traceability over automation.** Every input carries a `src`. Defaults are listed in the report. The user confirms the geometry before any load runs.
3. **Two methods that fail differently.** Manual J (OpenStudio-HPXML) is primary. The EnergyPlus cross-check uses different physics for infiltration, buffer zones and ground coupling. Disagreement is reported on a like-for-like basis rather than averaged away. Both read the same building model, so input and takeoff errors are caught by the QA gates, not by the cross-check.
4. **Minimal skill.** No binaries, standards text or finished models ship in the skill. Engines, weather files and the NBC PDF are downloaded at run time; a uv inline-script CLI carries the Python dependencies.
5. **Permissive licenses only.** Ladybug Tools and PyMuPDF were considered but are AGPL-3.0. They were replaced with our own geometry kernel (shapely), pdfplumber and pypdfium2, and a three.js viewer.

## Module map (`skills/hvac-load-calc/scripts/hvacload/`)

| Module | Role |
|---|---|
| `tools.py` | Pinned engine download, discovery, `doctor` |
| `pdfkit.py` | Page classification (vector/raster), gridded renders and crops, vector lines, curves and words (incl. metric and vertical dimension text), line profiles for scans, calibration, overlay |
| `model.py` | Load and validate `building.json` into SI dataclasses; all errors reported together; geometry-only mode |
| `geometry.py` | Adjacency (exact collinear edge overlap), stepped walls, floors and ceilings across levels, attics per ceiling height, crawlspace, garage, openings |
| `weather.py` | Nearest OneBuilding station, download, DDY/STAT parsing (ASHRAE design days) |
| `codes.py` | NBC 2020 Table C-2 lookup in the free NRC PDF |
| `design.py` | Resolve design conditions, humidity difference, internal-gain allocation; list the defaults applied |
| `assembly.py` | Effective R of layered assemblies (parallel path) |
| `hpxml.py` | HPXML v5 writer (ids = surface ids), OpenStudio-HPXML run (`--skip-simulation`), parser, window-shading read-back |
| `eplus.py` | IDF writer (one zone per room, ideal loads, ELA infiltration, ISO 13370-style ground U), run, SQL parser |
| `results.py` | Like-for-like comparison, room table, sanity ratios, takeoff CSV |
| `qa.py` | Gaps, area reconciliation (whole house, levels, rooms), dimension chains, provenance, glazing, below-grade openings |
| `viewer.py` | Self-contained three.js HTML (EN/FR; colour by type, boundary, U, room load; top view, labels, grade plane) |
| `report.py` | EN/FR HTML report; PDF and PNG previews via a local headless Chromium |
| `pipeline.py` | `init`, `clone`, `weather --write`, `check`, `run`, `selftest` |
| `psychro.py`, `units.py` | Psychrometrics and unit conversions |

## Decisions and their reasons

- **Design temperatures are always explicit.** OpenStudio 3.11 can't parse 2025-format EPW design headers, and OpenStudio-HPXML would silently fall back to temperatures computed from the weather file. For Montréal that fallback is −18.8 °C instead of NBC −23 °C.
- **EnergyPlus geometry uses `Relative` coordinates.** With `World`, EnergyPlus ignores the Building North Axis. The run compares EnergyPlus surface azimuths with ours and flags any mismatch; this check caught the bug.
- **The cross-check is like-for-like.** The comparison changes were each prompted by a real mismatch found on the test houses:
  - Ducts and ventilation are excluded, because only the primary method books them.
  - Ground contact is compared separately, identified by surface id because OpenStudio-HPXML books a conditioned slab as "Floors".
  - The above-grade part of foundation walls is moved to ground contact on the EnergyPlus side.
  - Infiltration is split between rooms by above-grade wall area in both methods.
  - Windows use the primary engine's defaulted summer shading coefficients.
  - Room totals, not itemised components, are compared, so the Manual J "peak" fenestration procedure is handled.
- **Garage walls are owned by the conditioned side and mirrored into the garage zone**, so interzone pairs always match when the garage slab sits lower (`floor_elevation`).
- **Roofs.** Rectilinear attic footprints are split into rectangles with hip roofs of uniform pitch. That keeps the roof area exact (footprint / cos(pitch)); explicit `roof_sections` allow gables and sheds. Ceilings at different heights get separate attic zones, each with its own roof.
- **Wall heights follow what's above.** The part of a wall under a room on the next level runs to that floor, including the band joist; the rest stops at the room's ceiling. The result is a stepped polygon whose first four vertices stay top-left, bottom-left, bottom-right, top-right.
- **Floors and ceilings look through every level**, nearest first, so partial basements and split levels resolve correctly. An uncovered floor within 1.5 m of grade sits on the foundation; above that it's an exposed floor, with a warning.
- **Two-stage QA gate.** `check --geometry-only` validates geometry before any thermal input exists, so the user confirms the takeoff before the envelope interview. The full `check` then requires every assembly and product.
- **Duct-leakage default is location-aware.** It's zero for ducts in conditioned space, and 4% of floor area (CFM25) per side elsewhere. Defaults are listed in the report. A default that booked leakage for ducts inside the house inflated heating by 33–45% in testing.
- **HRV efficiency semantics are explicit.** A rated SRE (HVI / CSA C439) is converted by OpenStudio-HPXML to an apparent effectiveness (fan heat credited); an adjusted value (`asre`) is used as is.
- **No silent defaults** for foundation type, roof pitch or airtightness: they must come from the plans or the user.

## Validation

- `selftest`: the OpenStudio-HPXML ACCA "Bob Ross" case reproduces heating and sensible cooling exactly.
- **Reference houses:** a crawlspace ranch; a two-storey house with basement, bonus room, lower garage slab and a 30° north rotation; and the bundled example. The like-for-like cross-check agrees within ±5% on heating and ±6% on cooling.
- **End-to-end, raster:** a fresh Claude session followed `SKILL.md` on the scanned BPC-022 sample house published by Permit Sonoma (not included here).
  - Glazing area reconciled exactly (158 ft²); the conditioned area came out −2.1%, explained by the recessed entry porch.
  - The cross-check agreed within 7%.
- **End-to-end, vector:** the synthetic French plan set in `tests/fixtures/laval/`, generated by a script, with three levels including a heated basement. The run used the Canadian path: CSA F280 declined, NBC values from `nbc`.
  - The takeoff matched the ground-truth model **exactly**: 0.000 m² difference on every surface category and orientation, the same north rotation, and all 13 room areas.
  - It caught the reduced sheet (printed 1:50, actual 1:75) and a planted dimension-chain error.
  - The heating cross-check agreed within +3.5%.
- **Fixes and tests:** findings from a code review and from both end-to-end runs were fixed. Each correctness fix has a regression test in `tests/test_review_fixes.py`.

## Background: what the sources say (surveyed 2026-09-30)

- **OpenStudio-HPXML** implements ACCA Manual J (and S) in `hvac_sizing.rb` and reports room-by-room loads since v1.8.0. Design loads are produced without running EnergyPlus (`--skip-simulation`). Sources: [hvac_sizing.rb](https://github.com/NatLabRockies/OpenStudio-HPXML/blob/master/HPXMLtoOpenStudio/resources/hvac_sizing.rb), [inputs](https://openstudio-hpxml.readthedocs.io/en/latest/workflow_inputs.html), [outputs](https://openstudio-hpxml.readthedocs.io/en/latest/workflow_outputs.html).
- **EnergyPlus vs Manual J on the same house:**
  - In a DOE/NLR 2024 comparison, EnergyPlus net peak heating was about 80% of the Manual J-equivalent load, and gross about 91% ([DOE/GO-102024-6351](https://docs.nlr.gov/docs/fy25osti/90544.pdf)).
  - A room-by-room design-day heat balance is the idea behind ASHRAE RP-1199's Residential Heat Balance method ([Barnaby, Spitler & Xiao 2005](https://static1.squarespace.com/static/61718e5c0ba09e66de8b077e/t/662bb0b52375c20f90fe6fc2/1714139318142/Barnaby_Spitler_Xiao_2005.pdf)).
- **F280 software spread:** five commercial F280 packages overestimated an Ottawa research house's heat loss by 15–55%, against a manual calculation within 4% of measured ([eSim 2022](https://publications.ibpsa.org/proceedings/esim/2022/papers/esim2022_227.pdf)).
- **Code context:**
  - **Canada:** NBC 2020 9.33.5.1 requires heating capacity per CSA F280 ([NBC 2020, NRC](https://nrc-publications.canada.ca/eng/view/object/?id=515340b5-f4e0-4798-be69-692e4ec423e8)).
  - **US:** IRC M1401.3 requires sizing per Manual S, from Manual J or other approved methods ([IRC 2024](https://up.codes/viewer/general-services-administration/irc-2024/chapter/14/heating-and-cooling-equipment-and-appliances)).
  - **Approved software:** no open-source tool is on ACCA's approved Manual J software list ([ACCA](https://www.acca.org/standards/approved-software)). This skill is a design aid for professionals, not a compliance report.
- **Cross-check expectations:** no standard sets an acceptable spread between methods. The 20% (heating) and 30% (cooling) flag thresholds used here are a rule of thumb, informed by the studies above.
- **Weather and design data:** [climate.onebuilding.org](https://climate.onebuilding.org) (EPW/DDY/STAT with ASHRAE design conditions) and NBC Appendix C (free from NRC). Both are downloaded at run time and never redistributed.
