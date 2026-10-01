"""Regression tests for issues found by the code review and the end-to-end test."""

import math

import pytest
from conftest import box_building

from hvacload import geometry, model, qa
from hvacload.pdfkit import parse_length


def build(raw, **kw):
    b = model.load(raw, **kw)
    return b, geometry.build(b)


def cat_area(g, zone, cat):
    return sum(s.area for s in g["surfaces"] if s.zone == zone and s.category == cat)


def test_partial_basement_rest_of_house_on_crawlspace():
    raw = box_building(
        levels=[{"id": "B", "elevation": -2.0, "ceiling_height": 2.2, "floor_to_floor": 2.6},
                {"id": "L1", "elevation": 0.6, "ceiling_height": 2.4}],
        foundation={"type": "crawlspace_vented", "depth_below_grade": 0.3},
        rooms=[{"id": "bs", "level": "B", "type": "family", "polygon": [[0, 0], [6, 0], [6, 8], [0, 8]]},
               {"id": "liv", "level": "L1", "type": "living", "polygon": [[0, 0], [6, 0], [6, 8], [0, 8]]},
               {"id": "bed", "level": "L1", "type": "bedroom", "polygon": [[6, 0], [10, 0], [10, 8], [6, 8]]}])
    raw["assemblies"].update({"fw": {"rsi": 2.0}, "fl": {"rsi": 3.0}, "cw": {"rsi": 0.5}, "dirt": {"uninsulated": True}})
    raw["surface_assemblies"].update({"wall_basement": "fw", "floor_crawlspace": "fl", "wall_crawlspace": "cw",
                                      "slab_crawlspace": "dirt"})
    _, g = build(raw)
    assert cat_area(g, "bed", "floor_crawlspace") == pytest.approx(32.0)   # not "exposed" to outdoor air
    assert cat_area(g, "bed", "floor_exposed") == 0
    assert g["zones"]["crawlspace"]["volume"] > 0
    crawl_top = max(v[2] for s in g["surfaces"] if s.category == "wall_crawlspace" for v in s.vertices)
    assert crawl_top == pytest.approx(0.6)                                # up to the floor it supports
    # no crawl wall along the basement: only the 3 outer sides (4 + 8 + 4 m) remain
    assert g["zones"]["crawlspace"]["perimeter"] == pytest.approx(16.0)


def test_edge_index_refers_to_polygon_as_written():
    raw = box_building(rooms=[{"id": "a", "level": "L1", "type": "living",
                               "polygon": [[0, 0], [0, 8], [10, 8], [10, 0]]}])  # clockwise; edge 0 = west wall
    raw["openings"] = [{"id": "w", "room": "a", "edge": 0, "width": 1, "height": 1, "product": "win"}]
    _, g = build(raw)
    assert round(next(s for s in g["surfaces"] if s.id == "w").azimuth) == 270
    raw["rooms"][0]["polygon"] = [[0, 0], [5, 0], [10, 0], [10, 8], [0, 8]]     # collinear point kept in numbering
    raw["openings"][0]["edge"] = 2                                               # (10,0)->(10,8): east
    _, g = build(raw)
    assert round(next(s for s in g["surfaces"] if s.id == "w").azimuth) == 90


def test_walls_step_where_only_part_of_the_room_has_a_floor_above():
    raw = box_building(
        levels=[{"id": "L1", "elevation": 0.3, "ceiling_height": 2.4, "floor_to_floor": 2.8},
                {"id": "L2", "elevation": 3.1, "ceiling_height": 2.4}],
        rooms=[{"id": "big", "level": "L1", "type": "living", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]]},
               {"id": "up", "level": "L2", "type": "bedroom", "polygon": [[0, 0], [3, 0], [3, 8], [0, 8]]}])
    _, g = build(raw)
    # walls under the upper room run to 3.1 m, the rest to the 2.7 m ceiling
    expected = (3 * 2.8 + 7 * 2.4) * 2 + 8 * 2.8 + 8 * 2.4
    assert cat_area(g, "big", "wall_exterior") == pytest.approx(expected, rel=1e-6)


def test_garage_side_door_is_moved_to_the_house():
    raw = box_building(rooms=[
        {"id": "k", "level": "L1", "type": "kitchen", "polygon": [[0, 0], [6, 0], [6, 8], [0, 8]]},
        {"id": "gar", "level": "L1", "type": "garage", "floor_elevation": 0.0, "polygon": [[6, 0], [12, 0], [12, 8], [6, 8]]}])
    raw["openings"] = [{"id": "d", "room": "gar", "kind": "door", "at": [6, 4], "width": 0.9, "height": 2.0, "product": "door"}]
    _, g = build(raw)
    d = next(s for s in g["surfaces"] if s.id == "d")
    assert d.room == "k" and d.category == "door"
    assert next(s for s in g["surfaces"] if s.id == d.parent).room == "k"


def test_reserved_room_ids_rejected():
    raw = box_building(rooms=[{"id": "attic", "level": "L1", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]]}])
    with pytest.raises(model.ModelError):
        model.load(raw)


def test_fractional_inches_and_parse_errors_become_qa_errors(box):
    assert parse_length("10'-6 1/2\"", "ft") == pytest.approx(10 + 6.5 / 12)
    assert parse_length("10'-6½\"", "ft") == pytest.approx(10 + 6.5 / 12)
    box["source"] = {"dimension_chains": [{"label": "bad", "parts": ["ten feet"], "total": "10'"}]}
    b, g = build(box)
    rep = qa.check(b, g)
    assert any("bad" in e for e in rep["errors"])


def test_geometry_only_mode_needs_no_thermal_inputs(box):
    del box["surface_assemblies"]["slab"]
    box["openings"] = [{"id": "w", "room": "a", "at": [5, 0], "width": 2, "height": 1.5, "product": "not_defined_yet"}]
    with pytest.raises(model.ModelError):
        build(box)
    b, g = build(box, geometry_only=True)
    assert any(s.id == "w" for s in g["surfaces"])


def test_per_room_stated_areas_and_below_grade_window():
    raw = box_building(
        levels=[{"id": "B", "elevation": -2.0, "ceiling_height": 2.3, "floor_to_floor": 2.6},
                {"id": "L1", "elevation": 0.6, "ceiling_height": 2.4}],
        foundation={"type": "basement"},
        rooms=[{"id": "bs", "level": "B", "type": "family", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]]},
               {"id": "liv", "level": "L1", "type": "living", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]]}])
    raw["assemblies"]["fw"] = {"rsi": 2.0}
    raw["surface_assemblies"]["wall_basement"] = "fw"
    raw["openings"] = [{"id": "well", "room": "bs", "at": [5, 0], "width": 0.8, "height": 0.4, "sill": 1.5,
                        "product": "win"}]
    raw["source"] = {"stated_rooms": {"liv": 80.0, "bs": 70.0}, "stated_levels": {"L1": 80.0}}
    b, g = build(raw)
    rep = qa.check(b, g)
    assert any("stated_rooms bs" in w for w in rep["warnings"])
    assert not any("stated_rooms liv" in w for w in rep["warnings"])
    assert any("well" in w and "below grade" in w for w in rep["warnings"])


def test_spare_occupant_goes_to_living_room():
    from hvacload import design
    raw = box_building(rooms=[
        {"id": "fam", "level": "L1", "type": "family", "polygon": [[0, 0], [8, 0], [8, 8], [0, 8]]},
        {"id": "liv", "level": "L1", "type": "living", "polygon": [[8, 0], [12, 0], [12, 8], [8, 8]]},
        {"id": "bed", "level": "L1", "type": "bedroom", "polygon": [[12, 0], [16, 0], [16, 8], [12, 8]]}])
    b, g = build(raw)
    gains = design._gains(b, g, [])
    assert gains["per_room"]["liv"]["occupants"] == 1 and gains["per_room"]["fam"]["occupants"] == 0


def test_adjusted_sre_written_to_hpxml(tmp_path, box):
    from hvacload import design, hpxml
    box["ventilation"] = {"type": "hrv", "lps": 30, "asre": 0.75}
    box["design"] = {"heating_outdoor": {"value": -23, "unit": "C", "src": "t"},
                     "cooling_outdoor": {"value": 30, "unit": "C", "src": "t"},
                     "cooling_wetbulb": {"value": 21, "unit": "C", "src": "t"},
                     "daily_range": "medium", "weather": {"epw": __file__}}
    b, g = build(box)
    with pytest.raises(model.ModelError) as e:  # airtightness is required, with a clear message
        design.resolve(b, g)
    assert "airtightness" in str(e.value)
    box["airtightness"] = {"ach50": 2.5}
    b, g = build(box)
    d = design.resolve(b, g)
    hpxml.write(b, g, d, tmp_path / "in.xml")
    x = (tmp_path / "in.xml").read_text(encoding="utf-8")
    assert "AdjustedSensibleRecoveryEfficiency>0.75" in x and "<SensibleRecoveryEfficiency>" not in x


def test_roof_pitch_and_foundation_are_required(box):
    box["attic"] = {"type": "vented"}
    box["foundation"] = {}
    with pytest.raises(model.ModelError) as e:
        model.load(box)
    msg = str(e.value)
    assert "roof_pitch" in msg and "foundation.type" in msg
