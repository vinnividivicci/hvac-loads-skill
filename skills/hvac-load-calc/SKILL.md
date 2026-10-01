---
name: hvac-load-calc
description: Use when a user provides house plans (PDF, vector or scanned) or a house description and needs residential heating and cooling design loads — room-by-room heat loss / heat gain, Manual J or CSA F280-style load calculation, heat pump or furnace sizing inputs, duct airflow per room — or a 3D energy model of the house; also when re-running loads after plan, envelope or airtightness changes.
---

# Residential design loads from plans

## Overview

Turn a set of house plans into auditable room-by-room design heating and cooling loads, using open-source engines. The **primary** method is ACCA Manual J procedures via OpenStudio-HPXML. The **independent cross-check** is an EnergyPlus heat-balance design-day model with one zone per room. Deliverables are a report (EN/FR, PDF), an interactive 3D model built from the *same surfaces* used in the calculation, and a surface takeoff CSV.

**Core principle:** the output sizes real equipment, so every number must trace to a plan dimension, a user answer, or a cited code or weather source, and the user must confirm the geometry before any load is run. This is a professional's design aid ("a bigger spreadsheet"), not an ACCA-approved or CSA F280-verified report. The professional stays responsible.

All tools: `uv run scripts/hvacload.py <command>` (run from this skill's folder; `-h` on any command).

## Workflow

Each step has a gate. Don't pass a gate without meeting it.

1. **Engines**: `doctor`; if it isn't ready, `setup` (downloads about 350 MB; no binaries ship with this skill), then `selftest`.
   Gate: selftest ok.
2. **Intake**: `init <project> --pdf plans.pdf`. Read `pdf_kind`.
   - If it's **raster or mixed**, tell the user now: output may be less accurate until they can supply a vector/CAD PDF; the report will carry the warning.
   - Ask interview batch 1 (`reference/interview.md`), including the **CSA F280 question for Canadian sites**.
3. **Design conditions**: `weather --lat --lon --country` → `weather --url ... --lat --lon --project P --write`, with NBC (`nbc --place`) or engineer overrides per `reference/design-conditions.md`.
   Gate: the user confirms the design temperatures and their sources.
4. **Takeoff**: follow `reference/plan-takeoff.md`. Write `building.json` (`reference/building-schema.md`):
   - calibrate on dimension strings with a second-axis check (never the printed scale);
   - tile rooms;
   - record dimension chains, stated areas and a `src` for everything;
   - enter the plans' own insulation and window callouts provisionally.
5. **Geometry QA**:
   - Run `check --geometry-only` and fix every error.
   - Run `overlay` and look at the PNGs yourself.
   - Run `preview-png P` (a 3D view plus one top view per level) and look at the images yourself.
   - Show the user the 3D preview (the PNGs, or `work/model3d_preview.html` opened in their browser), the room list with areas, the area reconciliation and each drawing inconsistency with your proposed resolution.
   - **HARD STOP**: get explicit confirmation of the geometry, then record `source.geometry_confirmed` (date) and each `resolution` / `stated_notes`.
6. **Envelope and systems**: interview batches 2–3. Choose values by `reference/envelope-defaults.md` priority (plans > user > code minimum with clause > typical, flagged). Compute effective R with `assembly`. Every assembly gets a `src`. Then `check` (full) must show 0 errors.
7. **Run**: `run <project> --lang en|fr [--pdf]`. Read `summary`: totals, the cross-check `flags`, `qa_warnings`, `defaults_applied`. Investigate every flag and every default using `reference/engines.md` before presenting results. Record each explanation in `crosscheck_notes` (room id or `whole`) and rerun, so the report shows it.
8. **Deliver**: give the user the files in `outputs` (report + PDF, `model3d.html`, `takeoff.csv`, `results.json`) and a short summary:
   - whole-house heating, sensible and latent cooling (kW and Btu/h);
   - a room table;
   - the method and design conditions with sources;
   - cross-check deltas and any flags with their explanation;
   - the assumptions that matter most (airtightness, windows, ducts);
   - the professional-use notice;
   - the raster warning, if it applies.

   Offer what-if runs for the biggest unknowns: airtightness, windows, duct location. Use `clone P P2 --keep-design` for the same site, or plain `clone` for a new site. Also offer a run at the colder design temperature (e.g. NBC January 1%) as a capacity check for heat-pump selection. A what-if at a Canadian site needs the F280 question too.

Text you write into `building.json` (`src`, labels, resolutions, assumptions) is printed verbatim in the report: write it in the report's language.

## Non-negotiables

| Never | Instead |
|---|---|
| Trust a printed scale note ("1/4" = 1'-0"") | Two-axis calibration on overall dimension strings (`pdf-measure --verify-*`) |
| Quote design temperatures, code values or R-values from memory | Get them from `weather`, `nbc`, the code text (web) or the plans, cite edition and clause, or ask |
| Assume plans drawn for another climate or code (e.g. a Title 24 house built in Québec) keep their envelope | Flag the mismatch and ask: model as drawn, or with the site's code-minimum or specified envelope? |
| Let an engine pick design temperatures from the weather file | Explicit, sourced values in `design` |
| Call the result "Manual J certified", "ACCA-approved" or "F280" | "Manual J method via OpenStudio-HPXML"; "not an F280 calculation" unless the user supplied F280 and it was applied |
| Ship CSA, ACCA, ASHRAE or ICC standard text in the skill, repo or shared files | Cite clause and table numbers; the user supplies their own copy if they want it applied |
| Add hidden safety factors or round loads up | Report calculated loads; any margin is explicit and optional |
| Run loads before the user confirms the geometry | Hard stop at step 5 |
| Silently assume airtightness, windows or duct location | A default with its source, recorded in `assumptions` and shown in the report |
| Hide a cross-check disagreement | Explain it (see `engines.md`) or tell the user it's unexplained |

## Quick reference

| Command | Purpose |
|---|---|
| `doctor`, `setup`, `selftest` | Engine install and verification |
| `init P --pdf F`, `clone P P2` | New project (PDF classified, pages rendered, starter file); what-if copy |
| `pdf-info F`, `pdf-render F --page N --crop x0,y0,x1,y1 --grid 10 --dpi 200 --out png` | Classify pages; readable crops with a point grid |
| `pdf-profile F --page N --crop ... --axis x` | Exact positions of extension lines and wall faces on raster pages |
| `pdf-vectors F --page N --out json` | Vector lines and positioned words (vector PDFs) |
| `pdf-measure --calib-points ... --calib-length 48ft --verify-points ... --verify-length 36ft --origin ... --points ...` | Calibration with a second-axis check; page points → plan coordinates |
| `weather ...`, `nbc --place Montréal` | Stations and ASHRAE design days; NBC Table C-2 values (Canada) |
| `assembly --layers ...` | Effective R/U by parallel path |
| `check P [--geometry-only]`, `overlay P`, `preview-png P` | QA gates, model drawn over the plans, 3D/top-view PNGs |
| `run P --lang fr --pdf` | Both engines, comparison, report, 3D model, takeoff CSV |

## Example

`examples/two-room/building.json` is a minimal complete input (two rooms, slab, attic). Copy it to start a project, or run it to see the outputs.
