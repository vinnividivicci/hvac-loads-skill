# Engines: what runs, what to expect, how to debug

## Installing (no binaries in the skill)

```bash
uv run scripts/hvacload.py setup      # OpenStudio 3.11.0 (with EnergyPlus 25.2) + OpenStudio-HPXML v1.12.0, ~350 MB
uv run scripts/hvacload.py doctor     # paths + versions; exit 1 if something is missing
uv run scripts/hvacload.py selftest   # ACCA Bob Ross example must reproduce OpenStudio-HPXML's stored result
```

- Everything goes into `HVACLOAD_HOME` (default `~/.hvacload`); no admin rights are needed.
- Override paths with `HVACLOAD_OPENSTUDIO`, `HVACLOAD_ENERGYPLUS` or `HVACLOAD_OSHPXML`.
- Weather files are cached in `~/.hvacload/weather`.

## Primary method: ACCA Manual J via OpenStudio-HPXML

- `hvac_sizing.rb` is an open implementation of the Manual J 8 procedures, run with `--skip-simulation` in a few seconds.
- It gives room-by-room heating and sensible cooling, whole-house latent, and a component breakdown per surface id. Surface ids are the ones in `takeoff.csv` and the 3D view.
- Conventions to know:
  - Design temperatures are always written explicitly (see `design-conditions.md`).
  - Windows default to **light curtains, 50% coverage** (summer shading coefficient about 0.85) unless `interior_shading` is set.
  - **Duct loads** are included when `hvac.distribution` is `ducted`. The engine allocates them to rooms, and they can be large for attic or crawlspace ducts: 20–60% of the envelope load depending on climate.
  - Duct leakage "to outside" defaults to zero when the ducts are in conditioned space. Elsewhere it defaults to 4% of floor area (CFM25) per side. Both defaults are listed in `defaults_applied`.
  - **Mechanical ventilation** is a system-level load: it's in the whole-house total, not in room totals.
    - A rated `sre` (HVI / CSA C439) is converted by the engine to an *apparent* effectiveness that credits fan heat. For example, 0.70 becomes about 0.83.
    - `asre` (adjusted) is used as given.
    - Ask which one the product data gives: using a rated value as if adjusted, or the reverse, changes the ventilation load by roughly a factor of two.
    - The cross-check uses `1 - effectiveness` and excludes ventilation from the like-for-like comparison.
  - Latent loads are whole-house only.
  - Cooling room loads use the `standard` fenestration procedure (average + AED excursion). Set `design.fenestration_procedure: "peak"` for zoned or room-by-room equipment.
  - Equipment type doesn't change design loads; only the distribution matters. Equipment selection (Manual S) is not done.
- It is **not** on ACCA's approved-software list. Say so in every deliverable (the report does).

## Cross-check: EnergyPlus design days, one zone per room

This model is deliberately built differently, so the two methods fail differently:
- A dynamic heat balance per room with ideal loads and sizing factor 1.0.
- Infiltration from the blower-door result through an **effective leakage area** (EnergyPlus's built-in model with stack and wind coefficients), not Manual J tables. The heating design day uses a 6.7 m/s wind (the traditional 15 mph).
- The attic, crawlspace and garage are **free-floating zones**, with vent leakage of SLA 1/300 for the attic and 1/150 for the crawlspace, and 1 ACH for the garage.
- Ground contact uses steady-state equivalent U-values (ISO 13370-style formulas) against an EN 12831-style effective ground temperature on the heating day, and the annual mean on the cooling day.
- Windows use the same summer shading coefficients the primary engine applied. Internal gains use the same magnitudes, on the cooling day only.

**The comparison is like-for-like**: above-grade envelope conduction + infiltration (+ internal gains and solar for cooling), room by room.
- **Excluded** from the like-for-like total: ducts and mechanical ventilation (only the primary method models them).
- **Ground contact** (slabs, whole foundation walls) is shown side by side instead. The methods differ by design: Manual J applies its tables against the outdoor design temperature; the cross-check uses ISO 13370-style U-values against an EN 12831 effective ground temperature. Manual J is typically 1.5–3× higher on slabs.
- Infiltration is split between rooms by above-grade exterior wall area in both engines.

Flags are a rule of thumb, not a standard:
- whole-house or room heating differs by > 20%;
- sensible cooling differs by > 30%;
- room flags need an absolute difference > 150 W.

Test results on reference houses (a smoke-test house, a two-storey Quebec house with basement, and the example): whole-house like-for-like heating within ±5% and cooling within ±6%.

## Interpreting disagreement

| Pattern | Usual cause | What to do |
|---|---|---|
| Ground-contact line differs a lot (slab-on-grade, basements) | Different ground-coupling methods | Normal and expected. The primary method governs; mention it |
| Infiltration category differs 20–50% | Manual J infiltration method vs leakage-area physics and wind | Check the ACH50 and shielding class. If the whole-house total is still within 20%, accept |
| Rooms with large west/east glass: cooling differs 30–70% | Manual J's AED approach vs hour-by-hour solar | Check the window SHGC and shading inputs; consider `fenestration_procedure: peak` for zoned systems |
| Everything differs by the same factor | Geometry or units error (scale, ft vs m), or a wrong design temperature | Stop. Recheck the takeoff and the design block |
| Walls or ceilings category differs > 15% **in heating** | Wrong assembly mapping or a missing adjacency (garage wall treated as exterior) | Check `takeoff.csv` categories and U-values |
| Walls differ 30–70% **in cooling**, west/east rooms highest | Manual J 8 wall cooling factors don't depend on orientation; the heat balance sees late-afternoon sun on lightweight walls | Normal for cooling; mention it, don't hunt for a mapping error |
| Mild climate, ducts outside the envelope, duct heating load above 40% | Supply air (~120 °F) running through an attic near the design temperature | Correct Manual J behaviour. Confirm the duct location and insulation, and offer a what-if with ducts inside |

## Debugging failures

- **`run` returns `stage: manualj` with `Error:` lines.** These come from OpenStudio-HPXML's schema/schematron validation; the message names the element. Read the generated `runs/<stamp>/manualj/in.xml`, fix `building.json` (usually a missing assembly or an impossible value) and rerun. Don't edit the XML by hand.
- **EnergyPlus severe errors** appear in `summary` / `energyplus` notes and `runs/<stamp>/energyplus/eplusout.err`.
  - "non-planar", "surface area mismatch" or "subsurface outside base surface" mean an opening doesn't fit its wall (check `sill`/`height`) or two rooms' polygons don't meet exactly.
- **"ORIENTATION MISMATCH"** in the notes means EnergyPlus azimuths don't match the model's. Check `north_arrow_deg` and report it; don't trust the cross-check until it's fixed.
- Rerunning is cheap: about 5 s for Manual J and 5–20 s for EnergyPlus on a house.
