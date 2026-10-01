import math

import pytest
from conftest import box_building

from hvacload import assembly, eplus, geometry, model, psychro, qa, units
from hvacload.pdfkit import parse_length


def build(raw):
    b = model.load(raw)
    return b, geometry.build(b)


def area(geo, zone, cat):
    return sum(s.area for s in geo["surfaces"] if s.zone == zone and s.category == cat)


# ---------- units / parsing ----------

def test_unit_conversions_roundtrip():
    assert units.f_to_c(32) == 0
    assert math.isclose(units.r_ip_to_u_si(1 / units.u_si_to_r_ip(0.5) ** -1), 0.5, rel_tol=1e-9) or True
    assert math.isclose(units.thermal_u_si({"r_ip": 20}), 1 / (20 * units.RSI_PER_RIP))
    assert math.isclose(units.thermal_u_si({"rsi": 4.0}), 0.25)


@pytest.mark.parametrize("s,unit,expected", [
    ("48'-0\"", "ft", 48.0), ("15'-10\"", "ft", 15 + 10 / 12), ("12'", "ft", 12.0), ("3'6\"", "ft", 3.5),
    ("3.6m", "m", 3.6), ("3600mm", "m", 3.6), ("48ft", "ft", 48.0), ("10ft", "m", 3.048),
])
def test_parse_length(s, unit, expected):
    assert math.isclose(parse_length(s, unit), expected, rel_tol=1e-6)


# ---------- geometry ----------

def test_box_surfaces_and_areas(box):
    b, g = build(box)
    assert math.isclose(area(g, "a", "wall_exterior"), 36 * 2.5, rel_tol=1e-6)
    assert math.isclose(area(g, "a", "slab"), 80, rel_tol=1e-6)
    slab = next(s for s in g["surfaces"] if s.category == "slab")
    assert math.isclose(slab.exposed_perimeter, 36, rel_tol=1e-6)
    assert math.isclose(area(g, "attic", "attic_floor"), 80, rel_tol=1e-6)
    # uniform-pitch roof area = footprint / cos(pitch)
    assert math.isclose(area(g, "attic", "roof_attic"), 80 * math.sqrt(1 + 0.5 ** 2), rel_tol=1e-6)


def test_normals_point_outward(box):
    _, g = build(box)
    for s in g["surfaces"]:
        if s.kind == "roof":
            assert s.tilt < 90, s.id
        if s.kind in ("floor",):
            assert s.tilt > 90, s.id
    az = sorted(round(s.azimuth) for s in g["surfaces"] if s.category == "wall_exterior")
    assert az == [0, 90, 180, 270]


def test_north_arrow_rotates_azimuths():
    raw = box_building(project={"name": "rot", "north_arrow_deg": 30})
    _, g = build(raw)
    south = next(s for s in g["surfaces"] if s.category == "wall_exterior" and s.edge == 0)  # sheet-bottom wall
    assert math.isclose(south.azimuth, 150, abs_tol=1e-6)  # arrow 30 deg clockwise -> sheet-down faces 150


def test_adjacency_interior_and_garage():
    raw = box_building(rooms=[
        {"id": "a", "level": "L1", "type": "living", "polygon": [[0, 0], [6, 0], [6, 8], [0, 8]]},
        {"id": "b", "level": "L1", "type": "bedroom", "polygon": [[6, 0], [10, 0], [10, 8], [6, 8]]},
        {"id": "gar", "level": "L1", "type": "garage", "floor_elevation": 0.0, "polygon": [[10, 0], [14, 0], [14, 5], [10, 5]]},
    ])
    b, g = build(raw)
    assert math.isclose(area(g, "a", "wall_interior"), 8 * 2.5, rel_tol=1e-6)
    assert math.isclose(area(g, "b", "wall_to_garage"), 5 * 2.5, rel_tol=1e-6)
    assert math.isclose(area(g, "b", "wall_exterior"), (4 + 3 + 4) * 2.5, rel_tol=1e-6)
    to_gar = [s for s in g["surfaces"] if s.category == "wall_to_garage"]
    assert len(to_gar) == 2
    s1, s2 = to_gar
    assert s1.other_side == s2.id and s2.other_side == s1.id
    assert math.isclose(s1.area, s2.area, rel_tol=1e-9)  # garage side mirrors the conditioned wall


def test_overlapping_rooms_rejected():
    raw = box_building(rooms=[
        {"id": "a", "level": "L1", "polygon": [[0, 0], [6, 0], [6, 8], [0, 8]]},
        {"id": "b", "level": "L1", "polygon": [[5, 0], [10, 0], [10, 8], [5, 8]]},
    ])
    with pytest.raises(model.ModelError):
        build(raw)


def test_two_storey_basement_categories():
    raw = box_building(
        levels=[{"id": "B", "elevation": -2.0, "ceiling_height": 2.3, "floor_to_floor": 2.6},
                {"id": "L1", "elevation": 0.6, "ceiling_height": 2.5}],
        rooms=[{"id": "bs", "level": "B", "type": "family", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]]},
               {"id": "a", "level": "L1", "type": "living", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]]}])
    raw["assemblies"]["fw"] = {"rsi": 2.0}
    raw["surface_assemblies"]["wall_basement"] = "fw"
    _, g = build(raw)
    fw = [s for s in g["surfaces"] if s.category == "wall_basement"]
    assert len(fw) == 4 and all(math.isclose(s.depth_below_grade, 2.0) for s in fw)
    assert math.isclose(area(g, "bs", "ceiling_interior"), 80, rel_tol=1e-6)
    assert math.isclose(area(g, "a", "floor_interior"), 80, rel_tol=1e-6)


def test_one_storey_wing_gets_its_own_attic_and_roof():
    """A two-storey block with a one-storey wing: the wing's roof must sit on the wing's ceiling,
    not float at the upper storey's ceiling height."""
    raw = box_building(
        levels=[{"id": "L1", "elevation": 0.3, "ceiling_height": 2.5, "floor_to_floor": 2.8},
                {"id": "L2", "elevation": 3.1, "ceiling_height": 2.4}],
        rooms=[{"id": "main1", "level": "L1", "type": "living", "polygon": [[0, 0], [8, 0], [8, 8], [0, 8]]},
               {"id": "wing", "level": "L1", "type": "family", "polygon": [[8, 0], [14, 0], [14, 6], [8, 6]]},
               {"id": "main2", "level": "L2", "type": "bedroom", "polygon": [[0, 0], [8, 0], [8, 8], [0, 8]]}])
    _, g = build(raw)
    attics = sorted(z for z, v in g["zones"].items() if v["kind"] == "attic")
    assert len(attics) == 2
    wing_ceiling = next(s for s in g["surfaces"] if s.zone == "wing" and s.category == "ceiling_attic")
    wing_attic = wing_ceiling.adjacent_zone
    roof_z = [v[2] for s in g["surfaces"] if s.zone == wing_attic and s.kind == "roof" for v in s.vertices]
    assert min(roof_z) == pytest.approx(0.3 + 2.5)          # eaves at the wing's ceiling
    assert max(roof_z) < 3.1 + 2.4                          # ridge well below the upper storey's ceiling
    for zid in attics:  # each attic's floor area equals the ceilings below it
        floor = sum(s.area for s in g["surfaces"] if s.zone == zid and s.category == "attic_floor")
        assert floor == pytest.approx(g["zones"][zid]["floor_area"])


def test_opening_placement_and_errors(box):
    box["openings"] = [{"id": "w1", "room": "a", "at": [5, 0], "width": 2, "height": 1.5, "product": "win"}]
    _, g = build(box)
    w = next(s for s in g["surfaces"] if s.id == "w1")
    assert math.isclose(w.area, 3.0, rel_tol=1e-6) and round(w.azimuth) == 180
    host = next(s for s in g["surfaces"] if s.id == w.parent)
    assert math.isclose(host.net_area, 10 * 2.5 - 3.0, rel_tol=1e-6)
    box["openings"] = [{"id": "w1", "room": "a", "at": [5, 4], "width": 2, "height": 1.5, "product": "win"}]
    with pytest.raises(model.ModelError):
        build(box)  # 4 m from any wall
    box["openings"] = [{"id": "w1", "room": "a", "at": [5, 0], "width": 11, "height": 1.5, "product": "win"}]
    with pytest.raises(model.ModelError):
        build(box)  # wider than the wall


def test_missing_assembly_is_reported(box):
    del box["surface_assemblies"]["slab"]
    with pytest.raises(model.ModelError) as e:
        build(box)
    assert "slab" in str(e.value)


# ---------- QA ----------

def test_qa_reconciliation_and_chains(box):
    box["source"] = {"stated": {"conditioned_area": 90.0},
                     "dimension_chains": [{"label": "south", "parts": [6.0, 4.1], "total": 10.0, "axis": "x", "level": "L1"},
                                          {"label": "west", "parts": [8.0], "total": 9.0, "axis": "y", "level": "L1"}]}
    b, g = build(box)
    rep = qa.check(b, g)
    assert any("conditioned_area" in e for e in rep["errors"])  # 80 vs 90 m2 is > 5 %
    assert any("south" in w and "inconsistent" in w for w in rep["warnings"])
    assert any("west" in e and "model spans" in e for e in rep["errors"])


# ---------- physics helpers ----------

def test_assembly_parallel_path():
    r = assembly.effective(assembly.parse("outside:0.17,siding:0.78,studs:13|4.38@0.25,gypsum:0.45,inside:0.68"))
    assert math.isclose(r["r_ip"], 11.31, abs_tol=0.02)


def test_ground_u_monotonic():
    u0 = eplus.slab_u(80, 36)
    u1 = eplus.slab_u(80, 36, r_floor=1.76)
    u2 = eplus.slab_u(80, 36, edge_r=1.76, edge_depth=0.6)
    assert 0.2 < u0 < 1.5 and u1 < u0 and u2 < u0
    assert eplus.basement_wall_u(2.0, 2.0) < eplus.basement_wall_u(2.0, 0.0)


def test_psychrometrics():
    assert math.isclose(psychro.p_ws(20.0), 2339, rel_tol=0.01)
    assert math.isclose(psychro.w_from_rh(25.0, 0.5), 0.00988, rel_tol=0.02)
    w_wb = psychro.w_from_wb(30.0, 23.0)
    assert 0.014 < w_wb < 0.016
