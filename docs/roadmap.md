# Roadmap

The skill aims to give a building professional an auditable, open-source path from house plans to room-by-room design heating and cooling loads, with a 3D model of what was calculated. Accuracy and traceability come before automation.

## Available now

- **Plan input:** vector and scanned PDFs. Page classification, gridded crops, vector line, curve and dimension-text extraction, line finding on scans, two-axis scale calibration and model-over-plan overlays.
- **Geometry:**
  - rooms on multiple levels;
  - basements, crawlspaces and slabs;
  - attics, including several ceiling heights;
  - cathedral and flat roofs;
  - attached garages with their own slab height;
  - windows, doors and skylights;
  - automatic adjacency.
- **QA gates:** dimension chains, stated-area reconciliation (whole house, levels, rooms), provenance for every input, a geometry-only check, and user confirmation before any load runs.
- **Inputs:**
  - a guided interview;
  - effective R of framed assemblies;
  - design weather from the nearest ASHRAE station;
  - NBC Table C-2 values for Canadian municipalities;
  - code-minimum references for the NBC, Quebec and IECC.
- **Calculation:** ACCA Manual J procedures room by room (OpenStudio-HPXML), with an independent EnergyPlus design-day cross-check.
- **Outputs:**
  - English or French report, in HTML and PDF;
  - 3D viewer and PNG previews;
  - surface takeoff CSV;
  - JSON results;
  - what-if copies of a project.

## Next

- Heat-pump and equipment selection (Manual S style), using manufacturer performance data: capacity at the design temperature, balance point, backup heat.
- Residential duct sizing from room airflows (Manual D style), with a register schedule.
- Exterior shading: overhangs, side fins, neighbouring buildings.
- Revision comparison: rerun after plan or envelope changes and list room-by-room differences.
- Room-level latent loads, and load ranges from uncertain inputs (airtightness, windows).
- Import from IFC and DXF; plan overlays with loads on the original sheets.
- Applying CSA F280 for users who supply their own copy of the standard, kept project-local and not shipped.

## Stretch goals

- **Commercial loads and air-system design:**
  - commercial load procedures;
  - ventilation per the applicable standard;
  - air-handler configuration with psychrometrics;
  - duct layout with fitting losses and fan static pressure.
- **Professional deliverables:** branded templates, a signature and seal block for the responsible professional, digitally signable archival PDFs, drawing sheets and an issue log.

## Out of scope

- Real-time multi-user editing and accounts.
- Any claim of ACCA approval or CSA F280 verification. The skill is a design aid; the professional using it stays responsible.
