import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "hvac-load-calc"
sys.path.insert(0, str(SKILL / "scripts"))


def box_building(**over):
    """A 10 m x 8 m single-storey slab-on-grade house with an attic, north up."""
    b = {
        "schema": "hvacload.building/1", "units": "m",
        "project": {"name": "box", "north_arrow_deg": 0},
        "levels": [{"id": "L1", "elevation": 0.2, "ceiling_height": 2.5}],
        "foundation": {"type": "slab"}, "attic": {"type": "vented", "roof_pitch": 6},
        "rooms": [{"id": "a", "level": "L1", "type": "living", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]]}],
        "openings": [],
        "fenestration": {"win": {"u_si": 1.6, "shgc": 0.35}, "door": {"u_si": 1.0, "kind": "door"}},
        "assemblies": {"w": {"rsi": 3.0}, "c": {"rsi": 7.0}, "r": {"rsi": 0.4}, "s": {"perimeter_r_ip": 10},
                       "g": {"rsi": 0.5}},
        "surface_assemblies": {"wall_exterior": "w", "ceiling_attic": "c", "roof_attic": "r", "slab": "s",
                               "wall_attic_gable": "g", "wall_to_garage": "w", "wall_garage_exterior": "g",
                               "slab_garage": "s", "ceiling_garage": "g"},
    }
    b.update(copy.deepcopy(over))
    return b


@pytest.fixture
def box():
    return box_building()


@pytest.fixture
def example_path():
    return SKILL / "examples" / "two-room" / "building.json"


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))
