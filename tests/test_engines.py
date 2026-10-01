"""Integration tests: need the engines (uv run skills/hvac-load-calc/scripts/hvacload.py setup)."""

import json
import shutil
from pathlib import Path

import pytest

from hvacload import pipeline, tools

pytestmark = pytest.mark.engines
needs_engines = pytest.mark.skipif(not tools.doctor()["ready"], reason="engines not installed")


@needs_engines
def test_selftest_reproduces_oshpxml_acca_result():
    res = pipeline.selftest()
    assert res["ok"], res


@needs_engines
def test_example_runs_and_methods_agree(tmp_path, example_path):
    proj = tmp_path / "ex"
    proj.mkdir()
    shutil.copy(example_path, proj / "building.json")
    res = pipeline.run(proj)
    assert res["ok"], res
    assert 2500 < res["heating_w"] < 4500  # 60 m2, Montreal NBC conditions
    cc = res["crosscheck"]
    assert cc["available"]
    assert abs(cc["delta_heating_pct"]) < 20
    assert abs(cc["delta_cooling_pct"]) < 30
    out = proj / "out"
    for f in ("report_en.html", "model3d.html", "takeoff.csv", "results.json"):
        assert (out / f).exists(), f
    rooms = json.loads((out / "results.json").read_text())["summary"]["rooms"]
    assert set(rooms) == {"living", "bed"}
