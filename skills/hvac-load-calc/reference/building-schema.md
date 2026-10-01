# building.json reference

One file per project describes the whole building. The scripts turn it into typed surfaces. Those same surfaces feed Manual J (OpenStudio-HPXML), EnergyPlus, the takeoff CSV and the 3D view. Keep every value traceable: give objects a `src` string that says where the value came from, for example `"p1 plan, dims 12'-0\" x 13'-0\""`, `"user answer 2026-09-30"` or `"NBC 9.36.2.6 Table A, zone 6"`.

## Coordinates and units

- `units`: `ft` | `in` | `m` | `mm`. This applies to every length in the file: polygons, heights, elevations, opening sizes and `at` points.
- Plan coordinates: **x points to the right of the sheet, y to the top of the sheet**, as drawn. Choose an origin at a building corner, usually the lower-left exterior corner.
- `project.north_arrow_deg` is the clockwise angle of the drawing's north arrow from the top of the sheet. Use 0 if the arrow points straight up, 90 if it points right, and −30 (or 330) if it points up-left.
- z = 0 is finished grade. `level.elevation` is the height of the finished floor above grade. It is negative for basements.
- Thermal values are **overall, air films included**:
  - `u_si` (W/m²K), `u_ip` (Btu/h·ft²·°F), `rsi` (m²K/W) or `r_ip` (h·ft²·°F/Btu);
  - for framed assemblies, use the *effective* value (framing included).

## Top level

```jsonc
{
  "schema": "hvacload.building/1",
  "units": "ft",
  "project": {"name": "...", "address": "...", "jurisdiction": "CA-QC", "north_arrow_deg": 0,
              "units_system": "SI"},            // report units: SI (default for CA-*) or IP
  "source": {...}, "levels": [...], "rooms": [...], "openings": [...],
  "foundation": {...}, "attic": {...},
  "assemblies": {...}, "surface_assemblies": {...}, "fenestration": {...},
  "airtightness": {...}, "ventilation": {...}, "hvac": {...}, "internal_gains": {...},
  "design": {...},                               // written by `hvacload.py weather --write`, then edited
  "bedrooms": 3,                                 // optional; default = count of rooms with type bedroom
  "site": {"shielding_class": 4},                // optional, 1 = exposed … 5 = heavily shielded
  "airflow": {"heating_supply_dt_f": 50, "cooling_supply_dt_f": 20},   // optional, for room airflow
  "assumptions": [{"item": "...", "value": "...", "basis": "..."}]
}
```

## source (for QA)

```jsonc
"source": {
  "pdf": "plans/house.pdf", "kind": "raster",         // from pdf-info: vector | raster | mixed
  "stated": {"conditioned_area": 1136, "garage_area": 280, "glazing_area": 158},   // plan units², from the plans
  "dimension_chains": [
    {"label": "north overall", "page": 1, "parts": ["8'-0\"", "12'-0\"", "28'-0\""], "total": "48'-0\"",
     "axis": "x", "level": "L1"}                     // axis+level: the model extent must equal the total
  ],
  "calibrations": [{"page": 1, "level": "L1", "origin_pt": [158.4, 420.0], "units_per_pt": 0.158}],
  "stated_notes": {"conditioned_area": "stated area includes the 6'x4' recessed porch"},   // explains a reconciliation gap
  "stated_rooms": {"salon": 26.9, "cuisine": 23.0},    // printed room areas (plan units²), each checked within 2 %
  "stated_levels": {"L1": 83.2},                        // printed conditioned area per level
  "geometry_confirmed": "2026-09-30"          // set only after the user confirms the geometry (step 5)
}
```

- Add `"resolution": "used the 48'-0\" overall"` to any chain whose parts don't add up, once you and the user have decided. The report then shows the resolution instead of an open warning.
- Chains without `level` are checked against the lowest above-grade level.

- Chain parts and totals may be numbers (plan units) or strings such as `12'-6"` or `3.6m`.
- `calibrations` drive `hvacload.py overlay`, which draws the model on the page.

## levels

```jsonc
{"id": "L1", "name": "Main floor", "elevation": 2.0, "ceiling_height": 8.0, "floor_to_floor": 9.0}
```

- `floor_to_floor` defaults to the next level's elevation minus this one. On the top level it defaults to the ceiling height.
- Exterior walls use `floor_to_floor` where a room has a room above (the band joist is included) and the room's ceiling height where it does not.

## rooms

```jsonc
{"id": "bed1", "name": "Bedroom #1", "level": "L1", "type": "bedroom",   // ids "attic", "atticN", "crawlspace" are reserved
 "polygon": [[0,0],[12,0],[12,13],[0,13]],
 "ceiling": "attic",          // attic | cathedral | flat_roof  (only where no room is above)
 "floor": "auto",             // auto | slab | crawlspace | exposed (override for this room)
 "ceiling_height": 8.0,       // optional override of the level value
 "floor_elevation": 0.0,      // optional: this room's floor height ABOVE GRADE (plan units), e.g. a garage slab
 "occupants": 1, "internal_sensible_btuh": 0,     // optional overrides of the default allocation
 "assemblies": {"wall_exterior": "wall_2x6"},     // optional per-room assembly overrides
 "src": "p1 plan"}
```

- **Tile the footprint.** Rooms on a level must not overlap and should leave no gaps.
  - Draw exterior edges on the **outside face of the exterior walls**, which matches the plan's overall dimensions and the stated gross areas.
  - Draw shared edges on partition centrelines.
  - Coincident edges are detected automatically, so walls between rooms are adiabatic and walls to a garage are interzone.
- `type` values:
  - conditioned: `bedroom`, `bath`, `kitchen`, `living`, `family`, `dining`, `hall`, `entry`, `closet`, `laundry`, `utility`, `office`, `stair`, `room`;
  - unconditioned: `garage`, `basement_unconditioned` (these default to `conditioned: false`).
- Open-plan spaces can be one room or several. The boundary between them is adiabatic either way.
- Stairs: model the stair footprint as a room on each level it occupies, or merge it into the hall.

## openings

```jsonc
{"id": "W3", "room": "living", "kind": "window", "at": [23.2, 0], "width": 3, "height": 4, "sill": 3,
 "product": "win_double_lowe", "label": "3040", "src": "p1 plan tag 3040; p2 south elevation"}
```

- `kind`: `window` | `glass_door` | `door` | `skylight`.
- `at` is a plan point near the opening's centre on the wall. It snaps to the nearest exterior or garage wall of that room within 1 m. Alternatively give `edge`: the index of the room polygon edge **as written** (edge i runs from vertex i to vertex i+1).
- A door between the house and the garage belongs to the house room. If you enter it on the garage, it is moved to the house side automatically.
- An opening can't straddle two rooms. Give it to the room that holds most of it; the report notes any shift.
- `sill` is measured from the room floor. It defaults to 3 ft for windows and 0 for doors.
- US window tags such as `4030` mean **width first**: 4'-0" wide × 3'-0" high.
- Skylights need a room with a `cathedral` or `flat_roof` ceiling.

## foundation and attic

```jsonc
"foundation": {"type": "crawlspace_vented", "depth_below_grade": 0.5},   // slab | crawlspace_vented | crawlspace_unvented | exposed | basement
"attic": {"type": "vented", "roof_pitch": 4, "roof_color": "medium", "roof_type": "asphalt or fiberglass shingles",
          "roof_sections": [{"polygon": [[0,0],[48,0],[48,24],[0,24]], "type": "gable", "ridge": "x"}]}
```

- The foundation applies under any floor that has no room below it and is within 1.5 m of grade, e.g. a main floor partly over a basement and partly on a crawlspace. Higher uncovered floors are exposed floors (cantilevers), and `check` warns about them.
- `foundation.type` is required: there is no default. Read it from the foundation plan. Use `basement` when the lowest level is a full basement; its floors are slabs either way.
- **Basements are levels**, not a foundation type. Put their rooms on a level with a negative elevation.
  - Their exterior walls become foundation walls, with the below-grade depth taken from the elevation.
  - Their floors are slabs.
- A crawlspace runs from `-depth_below_grade` up to the lowest level's elevation.
- `roof_pitch` is the rise per 12 run.
- `roof_sections` is optional:
  - if it is omitted, the attic footprint is split into rectangles, each with a hip roof;
  - `type` can be `hip`, `gable`, `shed` or `flat`;
  - `ridge` is `x` or `y` (for a shed, the slope rises toward +y or +x).
- Sections are rectangles; valleys aren't modelled. For L-shaped houses, hips give the cleanest closed attic. With gables, a gable end shared with another section is left open. This only affects the unconditioned attic zone and the picture; ceiling loads are unaffected.
- Ceilings under the attic at different heights (e.g. a one-storey wing beside a two-storey block) get separate attic zones (`attic`, `attic2`, …), each with its own roof. Upper-storey walls above a lower roof are treated as exterior walls (slightly conservative).
- `roof_pitch` is required: there is no default.

## Assemblies

```jsonc
"assemblies": {
  "wall_2x4_r13": {"r_ip": 11.3, "wall_type": "WoodStud", "desc": "2x4@16 R-13 batt, 5/8 ply siding",
                   "src": "p4 section; effective R by parallel path 25% framing"},
  "slab_garage": {"perimeter_r_ip": 0, "perimeter_depth_ft": 0, "under_r_ip": 0, "under_width_ft": 0,
                  "under_full": false, "thickness_in": 4, "src": "p4 detail 2"}
},
"surface_assemblies": {"wall_exterior": "wall_2x4_r13", "ceiling_attic": "ceil_r30", ...}
```

Every surface category that appears in the model must map to an assembly. `hvacload.py check` tells you which ones are missing.

Optional assembly fields:

| Field | Applies to | Meaning |
|---|---|---|
| `wall_type` | walls | HPXML WallType (thermal mass), default `WoodStud` |
| `siding`, `color` | walls | exterior finish and colour for solar absorptance, default `medium` |
| `floor_type` | floors and ceilings | HPXML FloorType, default `WoodFrame` |
| `foundation_type`, `thickness_in` | foundation walls | e.g. `solid concrete` (default), `concrete block`; wall thickness in inches (default 8) |
| `perimeter_r_ip`, `perimeter_depth_ft`, `under_r_ip`, `under_width_ft`, `under_full`, `thickness_in`, `carpet_fraction`, `carpet_r_ip` | slabs | insulation layout, thickness and carpet |
| `desc`, `src` | all | description and source, printed in the report |

- Rim joists are not a separate category. The band joist is part of the exterior wall above grade and part of the foundation wall on a basement. Record this as an assumption when it matters.

| Category | Surface |
|---|---|
| `wall_exterior` | above-grade wall, conditioned room to outside |
| `wall_basement` | wall of a below-grade level (foundation wall; the below-grade depth is automatic) |
| `wall_to_garage` | wall or door between a conditioned room and the garage |
| `wall_to_basement_unconditioned` | wall to an unconditioned basement room |
| `wall_garage_exterior` | garage wall to outside |
| `wall_attic_gable` | gable-end wall of the attic |
| `wall_crawlspace` | crawlspace perimeter wall |
| `ceiling_attic` | ceiling below the attic |
| `ceiling_garage` | garage ceiling below the attic |
| `ceiling_to_garage` | conditioned ceiling with a garage above (rare) |
| `roof_attic` | attic roof deck |
| `roof_cathedral` | cathedral or vaulted ceiling (sloped area uses the attic pitch) |
| `roof_flat` | flat roof over a room |
| `roof_garage` | roof directly over the garage (no ceiling) |
| `floor_crawlspace` | floor over a crawlspace |
| `floor_exposed` | floor over outside (cantilever, over a porch) |
| `floor_over_garage` | conditioned floor over the garage |
| `floor_over_basement_unconditioned` | floor over an unconditioned basement |
| `slab` | slab on grade, or basement floor, under a conditioned room |
| `slab_garage` | garage slab |
| `slab_crawlspace` | crawlspace floor (dirt: use `"thickness_in": 0`) |

Notes:
- Slab assemblies use the insulation fields shown above. Ground heat flow is computed by each engine; you do not enter a soil R-value.
- `wall_type` is optional and matches the HPXML WallType, for example `WoodStud`, `SteelFrame`, `ConcreteMasonryUnit` or `StructuralInsulatedPanel`.

## fenestration

```jsonc
"fenestration": {
  "win_double_lowe": {"u_ip": 0.30, "shgc": 0.25, "interior_shading": "light curtains", "src": "..."},
  "door_entry":      {"u_ip": 0.35, "kind": "door", "src": "..."}
}
```

Use whole-unit NFRC or CSA values. An opaque door has `kind: door` and no SHGC. If `interior_shading` is omitted, the primary engine assumes light curtains covering 50%; the cross-check uses the same assumption.

## airtightness, ventilation, hvac, internal_gains

```jsonc
"airtightness": {"ach50": 3.0, "src": "blower door report"},     // or {"cfm50": 900} or {"leakiness": "average"}
"ventilation": {"type": "hrv", "lps": 30, "sre": 0.7, "src": "..."},   // none | exhaust | supply | balanced | hrv | erv (+ tre); cfm or lps
                                                      // sre = rated SRE (HVI / CSA C439); if you only have an adjusted
                                                      // or apparent effectiveness, give "asre" instead
"hvac": {"distribution": "ducted",                                // ducted | ductless | hydronic
         "ducts": {"location": "attic", "supply_r_ip": 6, "return_r_ip": 6,
                   "leakage_cfm25": {"supply": 0.04, "return": 0.04, "fraction_of_cfa": true}},
         "src": "..."},
"internal_gains": {"occupants": 4, "appliance_sensible_btuh": 2400, "appliance_latent_btuh": 0}
```

- Duct location can be `attic`, `crawlspace`, `garage`, `conditioned`, `basement` or `basement_unconditioned`.
- Duct losses can be **large**: attic ducts often add 20–40% to the heating load. Ask where the ducts run.
- If internal gains are omitted, the Manual J defaults apply: bedrooms + 1 occupants at 230 sensible and 200 latent Btu/h each, plus 2,400 Btu/h of appliances in the kitchen. The report lists each default it applied.

## crosscheck_notes

```jsonc
"crosscheck_notes": {"salon": "west glazing: the cross-check peaks at 16:20 with sun on west walls; Manual J uses one wall factor for all orientations",
                     "whole": "cooling differs mostly in walls/windows (solar timing); the primary method governs"}
```

This records your explanation of each cross-check flag, keyed by room id or `whole`. The report then shows the flag as explained, with the text.

## design

`hvacload.py weather --url ... --project P --write` fills this block from the ASHRAE design days of the nearest station. Override values with `--heating-c/--cooling-c/--wetbulb-c` plus `--*-src`, for NBC values or the engineer's own data. See `design-conditions.md`.

```jsonc
"design": {
  "label": "Manual J method at NBC design conditions (not F280)",
  "heating_outdoor": {"value": -23, "unit": "C", "src": "NBC 2020 Table C-2, Montréal, January 2.5%"},
  "cooling_outdoor": {"value": 30, "unit": "C", "src": "..."},
  "cooling_wetbulb": {"value": 23, "unit": "C", "src": "..."},
  "daily_range": {"value": 10.1, "unit": "C", "src": "..."},
  "indoor_heating": {"value": 22, "unit": "C", "src": "..."},    // default 70 F (Manual J)
  "indoor_cooling": {"value": 75, "unit": "F", "src": "..."},    // default 75 F
  "indoor_rh": 0.5,
  "weather": {"epw": "...", "ddy": "...", "station": "...", "source_url": "..."},
  "climate_zone_iecc": "6A", "lat": 45.47, "lon": -73.75, "elevation_m": 36,
  "cooling_day": {"month": 7, "day": 21, "taub": 0.42, "taud": 2.33, "wind_ms": 5.5},
  "heating_wind_ms": 6.7,                 // EnergyPlus cross-check only (traditional 15 mph)
  "fenestration_procedure": "standard"     // or "peak" for room-by-room zoned systems (Manual J)
}
```
