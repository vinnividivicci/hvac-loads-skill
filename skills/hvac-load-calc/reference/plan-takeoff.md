# Plan takeoff: PDF to building.json

Most load-calc errors come from the takeoff, and the biggest single source is **scale**. The rule of this skill: **geometry comes from dimension strings; pixels and points only locate things.**

## 1. Classify the PDF

```bash
uv run scripts/hvacload.py init <project> --pdf <plans.pdf>     # copies, classifies, renders pages at 100 dpi
```

- **vector**: line work and text are real PDF objects. `pdf-vectors` returns every line and every word with coordinates, so dimension text can be read exactly.
- **raster** (scanned, or images placed in a document): everything is read visually.
  - **Tell the user now**: "These plans are rasterized; I'll read them visually, which is less reliable than a CAD/vector PDF. I'll ask you to confirm dimensions and windows, and the report will carry this warning."
  - If a vector version exists, ask for it.
- **mixed**: treat as raster for the image regions.

## 2. Find the sheets

Look at every page render. Identify:
- the floor plan per level;
- elevations (window heights, grade line, roof pitch);
- sections (ceiling heights, floor framing, insulation callouts, foundation depth);
- schedules (window and door sizes, areas);
- the area table or title block ("house area", "garage area", "glazing area");
- the north arrow.

## 3. Read at a legible resolution

```bash
uv run scripts/hvacload.py pdf-render plans.pdf --page 1 --dpi 200 --crop x0,y0,x1,y1 --grid 10 --out work/p1_plan.png
```

- The grid labels are **page points** (1/72 in, origin at top-left, y down).
- Read a feature's page coordinates straight off the grid. Crop tighter and use 300–400 dpi for small text such as window tags and dimension strings.
- Vector pages: `pdf-vectors plans.pdf --page 1 --out work/p1_vectors.json` gives the following:
  - **words** with `top`/`x0`, including vertical text in reading order;
  - **lines** grouped by stroke width (walls are usually the thickest);
  - **curves**: arcs and filled shapes. A north arrow is a short line inside a circle, or a small filled triangle; its bearing is atan2(dx, −dy) from base to tip.
  - Dimension strings, imperial or metric millimetres such as `3 200`, are in `dimension_words`.
- Rotated pages: grid labels and `--crop` coordinates follow the rendered (upright) view, not pdfplumber's unrotated coordinates.

## 4. Calibrate the scale, and never trust the printed scale note

A "1/4" = 1'-0"" note is only true if the sheet was printed at 100%. PDFs are often reduced, placed in documents or rescanned.
- Calibrate on the **longest overall dimension string**: find the page points of its two extension lines.
- Verify with a second overall dimension in the **other axis**. The two scales must agree within about 1%. If they don't, the page may be distorted (a skewed scan); tell the user.

```bash
# locate extension lines exactly (raster): a thin band across the dimension line, vertical lines -> x positions
uv run scripts/hvacload.py pdf-profile plans.pdf --page 1 --crop 150,160,470,172 --axis x
uv run scripts/hvacload.py pdf-measure --calib-points "158.4,166;462.6,166" --calib-length "48'-0\"" \
   --verify-points "468,268.8;468,496.7" --verify-length "36'-0\"" \
   --origin "158.4,420" --points "234,218.4;259.2,218.4"          # → plan coordinates of points
```

`pdf-measure` exits 1 if the two axes disagree by more than 1%. It also prints the implied drawing scale (e.g. `1:75`); if a printed scale note differs, tell the user the sheet was reduced.

- Record the calibration in `source.calibrations` (page, level, origin_pt, units_per_pt) so `overlay` works.

## 5. Build rooms from dimension chains

1. Write down every overall and partial dimension chain as `source.dimension_chains`. Add `axis` and `level` on the overall ones.
2. Set out the exterior outline from the chains. Use the outside face of the exterior walls unless the plans say otherwise (the notes often say "dimensions to face of stud or foundation").
3. Split the outline into rooms using the interior dimensions. Where a partition isn't dimensioned, measure it with the calibration and round to a sensible increment (1 in, or 10 mm).
4. **Tile the footprint:** no overlaps and no gaps. Put closets and halls in their own rooms or merge them into the adjacent room.
5. Check that the chain parts add up. **Drawings are often internally inconsistent.** Real example: 12' + 6' + 15'-10" + 14'-4" = 48'-2" against an overall 48'-0". When they don't add up, prefer the overall dimension, note the discrepancy in `assumptions`, and tell the user.
6. Record stated areas in `source.stated`, plus `stated_rooms` / `stated_levels` when the plans print them, and reconcile. The modelled conditioned area should be within 2% of the plan's stated area. If it isn't, find the error before going on. The sum of stated window areas is also a good check.

## 6. Openings

- Window and door **tags**:
  - US: `3040` = 3'-0" wide × 4'-0" high; `6068` = 6'-0" × 6'-8"; `T` = tempered.
  - Metric plans: a schedule, or `900x1200`.
- Use the schedule when there is one.
- Place each opening with `at` at its centre on the wall line (from the grid, via `pdf-measure`).
- Sill height comes from elevations or sections. The default is 3 ft; egress windows are often 2 ft.
- Classify each opening:
  - door to garage: `door` on the garage wall;
  - patio sliders and French doors: `glass_door`;
  - openings in unconditioned rooms (garage windows, overhead door): include them, because they set the garage temperature.
- Check glazing totals against any stated glazing area.

## 7. Heights, floors, roof

- **Ceiling heights** come from sections or notes; the typical US default is 8'-0". Check for vaulted areas: a ridge beam plus insulation along the rafters means `cathedral`.
- **Floor elevation above grade**: from sections and elevations. Crawlspace floors are typically 1.5–2.5 ft above grade; basements are negative.
- **Foundation type**: from the foundation plan and sections, for example girders and piers means a crawlspace, and "4" slab" means slab on grade.
- **Garage**: use `floor_elevation` for a slab below the house floor, and `ceiling: cathedral` if it is open to the rafters.
- **Roof pitch**: from the elevation pitch symbol, e.g. "12 / 4". Add `roof_sections` from the roof framing plan if you want an accurate 3D roof.

## 8. North arrow

`north_arrow_deg` is the clockwise angle of the arrow from the top of the sheet. If there is no arrow, **ask**; never assume. Orientation changes cooling loads a lot.

## 9. QA gates: do not skip

```bash
uv run scripts/hvacload.py check <project> --geometry-only   # before the envelope interview: errors must be zero
uv run scripts/hvacload.py overlay <project>                 # model drawn on the plan (cropped, 200 dpi): look at it
```

- Open the overlay PNG(s) and compare every room outline and opening dot with the drawing. Misalignment is a takeoff error.
- Open `work/model3d_preview.html` in a browser, or publish or screenshot it, and **show it to the user with the room table and area reconciliation. Get explicit confirmation before calculating.**
- For raster input, walk the user through the rooms with the largest loads (big glazing, exterior corners) and ask them to confirm those dimensions.
- For every drawing inconsistency (`check` warnings), propose a resolution and confirm it with the user. Record it as the chain's `resolution` or in `source.stated_notes`, and set `source.geometry_confirmed`.
- The 3D preview has a top view and room labels. A local HTML file opens directly in the user's browser (`start file.html` on Windows, `open` on macOS).

## Common takeoff mistakes

| Mistake | Consequence | Guard |
|---|---|---|
| Using the printed scale note on a reduced PDF | Every length wrong by the same factor | Two-axis calibration on dimension strings |
| Reading window tags height-first | Window area and orientation load wrong | US tags are width × height |
| Interior dimensions for exterior walls | Gross wall and floor areas low by 3–5% | Tile to the outside face; reconcile stated area |
| Forgetting the band joist and floor framing on multi-storey houses | Wall area low | Levels use floor_to_floor |
| Missing garage/house adjacency | Wall treated as exterior (overstates) or interior (understates) | Tile the garage as an unconditioned room |
| Assuming north is up | Solar loads on the wrong facades | Read the arrow or ask |
| Treating a vaulted room as a flat ceiling under the attic | Wrong roof U and area | Check sections for a ridge beam or rafter insulation |
