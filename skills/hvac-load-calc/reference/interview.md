# Interview: what to ask, in what order

- Ask only for what the plans don't answer.
- Group questions into two or three short batches.
- Offer a default with its source for every question, so "use the default" is always a valid answer.
- Record every answer in `building.json` with `src: "user, <date>"`.
- Ask batch 1 before the takeoff, because orientation and location change what you look for. Ask batches 2–3 after the takeoff is confirmed.

## Batch 1: project framing (before the takeoff)

1. **Site address or municipality.** This drives the design conditions and code jurisdiction.
2. **Canada only**: "Do you have CSA F280 (current edition) that you want applied? If not, I'll use the Manual J method at NBC design conditions, labelled 'not F280'." Also: "Do you have your own design-condition data you prefer?" See `design-conditions.md`.
3. **North**, if the plans have no north arrow, or the site orientation differs from the drawing.
4. **Report language and units**: EN/FR, SI/IP. The default for Canada is SI in French or English as the user writes; for the US, IP in English.
5. **New construction or existing house**, and the permit date. This sets which code edition gives the default values.
6. **Plans vs site**: if the plans cite another jurisdiction or climate (a title block, energy notes such as "Title 24 Package D, CZ2", or a foundation unsuited to the site's frost depth), say so and ask: model **as drawn**, with the **site's code-minimum** envelope, or with the **actual specification**? Offer to run more than one.

## Batch 2: envelope and airtightness (after the takeoff), by typical load impact

| # | Question | Default if unknown (state it) |
|---|---|---|
| 1 | Airtightness: blower-door target or test result (ACH50)? | New code-built CA: 3.2 ACH50 (NBC 9.36 proposed-house default); new US: 3.0 (IECC zones 3–8) or 5.0; Novoclimat: 1.5; pre-1990 house: 7–10 |
| 2 | Windows: U-factor and SHGC (NFRC/CSA label or schedule)? Interior blinds or curtains? | Code maximum U for the zone; SHGC 0.30 double low-e; light curtains 50% (primary engine default) |
| 3 | Wall assembly: confirm the plan callout, or give studs, spacing and insulation (+ exterior insulation)? | Code minimum *effective* value for the zone |
| 4 | Ceiling / roof: attic insulation, vaulted areas? | Code minimum; ask about vaulted rooms explicitly |
| 5 | Foundation: basement wall insulation (interior/exterior, height), slab insulation, crawlspace vented or unvented? | Code minimum; uninsulated slab for garages |
| 6 | Where do ducts run (attic, crawlspace, garage, inside)? Insulation, and sealed/tested? Or ductless / hydronic / baseboard? | Ducts inside conditioned space if unknown and the plans show none, but flag it: attic ducts can add 20–40% |
| 7 | Mechanical ventilation: type (HRV/ERV/exhaust), design flow, and recovery efficiency: a **rated SRE** (HVI / CSA C439 listing) or an adjusted/apparent value? | New CA house: a principal ventilation system is required (NBC 9.32), often an HRV. Ask for the design flow and efficiency |

## Batch 3: use and comfort (short)

| # | Question | Default |
|---|---|---|
| 8 | Indoor design temperatures | 70 °F / 75 °F 50% RH (Manual J); 22 °C heating in Canada |
| 9 | Occupants and unusual gains (home office, gym, large aquarium, server)? | Bedrooms + 1 occupants; 2,400 Btu/h appliances in the kitchen |
| 10 | Is the attached garage heated? | Unheated |
| 11 | Exterior shading (deep overhangs, porches, trees, adjacent buildings)? | None modelled (conservative for cooling) |

## Handling "I don't know"

- Use the default, record it in `assumptions` with its basis, and list it on the report's review page.
- For airtightness and windows, the two largest unknowns, offer to run a **what-if**. For example, copy the project and run at 2.0 and 4.0 ACH50 so the engineer sees the sensitivity.

## What not to ask

- Don't ask for anything the plans show clearly: sizes, windows, insulation callouts. Confirm it instead ("The section shows R-13 walls and R-30 ceiling. OK to use?").
- Don't ask the user to calculate effective R-values; do it with `hvacload.py assembly` and show the result.
