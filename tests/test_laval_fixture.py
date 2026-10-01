"""The synthetic Laval plan set: vector reading and the exact ground-truth model.

`fixtures/laval/make_plans.py` draws a French, metric, three-level plan set (drawn at 1:75 but labelled 1:50,
with one inconsistent dimension chain). `fixtures/laval/building_truth.json` is the exact model of that house.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from hvacload import geometry, model, pdfkit, qa

FIX = Path(__file__).parent / "fixtures" / "laval"


@pytest.fixture(scope="module")
def plans(tmp_path_factory):
    pytest.importorskip("matplotlib")
    out = tmp_path_factory.mktemp("laval") / "plans.pdf"
    subprocess.run([sys.executable, str(FIX / "make_plans.py"), str(out)], check=True, capture_output=True)
    return out


def test_pages_are_vector_with_a_misleading_scale_note(plans):
    info = pdfkit.info(str(plans))
    assert info["overall"] == "vector"
    assert "1:50" in info["pages"][0]["scale_notes_in_text_layer"]


def test_dimension_text_including_vertical_and_metric(plans):
    v = pdfkit.vectors(str(plans), 1)
    dims = sorted(w["text"] for w in v["dimension_words"])
    assert dims == ["10 400", "2 400", "3 150", "3 200", "3 200", "4 800", "4 800", "4 800", "5 600", "8 000"]
    assert v["n_curves"] >= 2  # north arrow (circle + arrow) and door swing


def test_true_drawing_scale_is_1_to_75(plans):
    v = pdfkit.vectors(str(plans), 1)
    walls = [ln for ln in v["lines"] if ln["w"] == max(ln2["w"] for ln2 in v["lines"] if ln2["len"] > 100)]
    width_pt = max(max(ln["x0"], ln["x1"]) for ln in walls) - min(min(ln["x0"], ln["x1"]) for ln in walls)
    ratio = (10.4 / width_pt) / (0.0254 / 72)
    assert ratio == pytest.approx(75, rel=0.01)


def test_ground_truth_model():
    b = model.load(FIX / "building_truth.json", geometry_only=True)
    g = geometry.build(b)
    rep = qa.check(b, g)
    assert rep["errors"] == []
    assert rep["info"]["modelled"]["conditioned_area"] == pytest.approx(249.6)
    assert rep["info"]["modelled"]["glazing_area"] == pytest.approx(21.6, abs=0.05)
    assert b.plan_north_deg == pytest.approx(345.0)
