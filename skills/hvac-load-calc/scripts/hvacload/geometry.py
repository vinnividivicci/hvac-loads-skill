"""Turn a Building (rooms as plan polygons + heights) into typed 3D surfaces.

This surface list is the single source of truth: the HPXML writer, the EnergyPlus
writer, the takeoff table and the 3D viewer all read it.

Conventions
- Plan coordinates: x to the right of the sheet, y to the top of the sheet, metres.
- z = 0 is finished grade. Level.elevation is the finished floor height above grade.
- Vertices are counter-clockwise when viewed from outside the owning zone
  (EnergyPlus convention), so the right-hand-rule normal points outward.
- Azimuths are true compass bearings of the outward normal (0 = N, 90 = E).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import split, unary_union

from .model import Building, ModelError, Room, assembly_for

TOL = 0.02  # m, adjacency tolerance
MIN_AREA = 0.05  # m2, surfaces smaller than this are dropped
BELOW_GRADE_LEVEL = -0.3  # m, levels whose floor is lower than this are basements
NEAR_GRADE = 1.5  # m, uncovered floors up to this height sit on the foundation, higher ones are exposed


@dataclass
class Surface:
    id: str
    zone: str  # room id, "attic" or "crawlspace"
    room: str | None  # owning room (None for attic/crawlspace)
    level: str | None
    kind: str  # wall | floor | ceiling | roof | window | door | skylight
    category: str
    boundary: str  # outside | ground | adiabatic | zone | foundation (partly below grade)
    adjacent_zone: str | None
    vertices: list[tuple[float, float, float]]
    azimuth: float | None
    tilt: float
    assembly: str | None = None
    u_si: float | None = None
    parent: str | None = None
    other_side: str | None = None  # matching surface in the adjacent zone
    depth_below_grade: float = 0.0
    exposed_perimeter: float = 0.0
    edge: int | None = None
    product: str | None = None
    shgc: float | None = None
    area_factor: float = 1.0  # true/plan area ratio (sloped cathedral roofs drawn flat)
    label: str = ""
    children: list[str] = field(default_factory=list)
    profile: list = field(default_factory=list)  # walls: [(t0, t1, z_top)] along the base from vertices[1]

    @property
    def area(self) -> float:
        return polygon_area_3d(self.vertices) * self.area_factor

    @property
    def net_area(self) -> float:
        return self.area - sum(self._child_areas)

    _child_areas: list[float] = field(default_factory=list, repr=False)


def polygon_area_3d(v) -> float:
    nx = ny = nz = 0.0
    for (x1, y1, z1), (x2, y2, z2) in zip(v, v[1:] + v[:1]):
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    return 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)


def newell_normal(v):
    nx = ny = nz = 0.0
    for (x1, y1, z1), (x2, y2, z2) in zip(v, v[1:] + v[:1]):
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / n, ny / n, nz / n


def plan_to_compass(b: Building, nx: float, ny: float) -> float:
    theta = math.degrees(math.atan2(nx, ny))  # clockwise from sheet-up
    return (b.plan_north_deg + theta) % 360.0


def orient(b: Building, verts) -> tuple[float | None, float]:
    nx, ny, nz = newell_normal(verts)
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, nz))))
    az = None if math.hypot(nx, ny) < 1e-6 else plan_to_compass(b, nx, ny)
    return az, tilt


class _Ids:
    def __init__(self):
        self.n: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self.n[prefix] = self.n.get(prefix, 0) + 1
        return f"{prefix}{self.n[prefix]}"


def _intervals(seg: LineString, other: Polygon, tol=TOL):
    """Parameter intervals [t0, t1] (metres along seg) where seg coincides with an edge of `other`.

    Edges must be collinear (parallel and within `tol`); overlaps are exact, no buffering.
    """
    (x1, y1), (x2, y2) = seg.coords
    L = seg.length
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    out = []
    pts = list(other.exterior.coords)
    for (a0, b0), (a1, b1) in zip(pts, pts[1:]):
        d0 = abs((a0 - x1) * uy - (b0 - y1) * ux)  # perpendicular distances to seg's line
        d1 = abs((a1 - x1) * uy - (b1 - y1) * ux)
        if d0 > tol or d1 > tol:
            continue
        t0 = (a0 - x1) * ux + (b0 - y1) * uy
        t1 = (a1 - x1) * ux + (b1 - y1) * uy
        lo, hi = max(0.0, min(t0, t1)), min(L, max(t0, t1))
        if hi - lo > 2 * tol:
            out.append((lo, hi))
    return out


def _merge(iv):
    out = []
    for a, bb in sorted(iv):
        if out and a <= out[-1][1] + TOL:
            out[-1] = (out[-1][0], max(out[-1][1], bb))
        else:
            out.append((a, bb))
    return out


def _complement(iv, length):
    out, cur = [], 0.0
    for a, bb in _merge(iv):
        if a - cur > 2 * TOL:
            out.append((cur, a))
        cur = max(cur, bb)
    if length - cur > 2 * TOL:
        out.append((cur, length))
    return out


def _simple_parts(geom):
    """Split polygons with holes into simple polygons (EnergyPlus needs simple surfaces)."""
    if geom.is_empty:
        return []
    if isinstance(geom, MultiPolygon) or geom.geom_type == "GeometryCollection":
        out = []
        for g in geom.geoms:
            if g.geom_type in ("Polygon", "MultiPolygon"):
                out += _simple_parts(g)
        return out
    if geom.geom_type != "Polygon" or geom.area < MIN_AREA:
        return []
    if not geom.interiors:
        return [geom]
    hole = Polygon(geom.interiors[0])
    cx = hole.centroid.x
    minx, miny, maxx, maxy = geom.bounds
    cut = LineString([(cx, miny - 1), (cx, maxy + 1)])
    out = []
    for g in split(geom, cut).geoms:
        out += _simple_parts(g)
    return out


def _ring(poly: Polygon, z: float, up: bool):
    pts = list(poly.exterior.coords)[:-1]
    if not Polygon(pts).exterior.is_ccw:
        pts.reverse()
    if not up:
        pts.reverse()
    return [(x, y, z) for x, y in pts]


def _wall_verts(p1, p2, z0, z1):
    (x1, y1), (x2, y2) = p1, p2
    return [(x1, y1, z1), (x1, y1, z0), (x2, y2, z0), (x2, y2, z1)]


def _covered(seg: LineString, area) -> list[tuple[float, float]]:
    """Intervals (m along seg) where seg lies inside or on the boundary of `area` (a polygon union)."""
    if area is None or area.is_empty:
        return []
    inter = seg.intersection(area.buffer(TOL, join_style="mitre"))
    out = []
    L = seg.length
    for g in getattr(inter, "geoms", [inter]):
        if g.geom_type != "LineString" or g.length < 2 * TOL:
            continue
        t0, t1 = sorted(seg.project(Point(c)) for c in (g.coords[0], g.coords[-1]))
        # the buffer overshoots interior ends by TOL; trim them back (segment ends stay exact)
        t0 = t0 + TOL if t0 > TOL else 0.0
        t1 = t1 - TOL if t1 < L - TOL else L
        if t1 - t0 > TOL:
            out.append((t0, t1))
    return _merge(out)


def _profile(seg: LineString, above, z_covered: float, z_open: float) -> list[tuple[float, float, float]]:
    """Top height along a wall: z_covered under a room above, z_open elsewhere."""
    L = seg.length
    cov = _covered(seg, above)
    prof = [(a, c, z_covered) for a, c in cov] + [(a, c, z_open) for a, c in _complement(cov, L)]
    prof.sort()
    merged: list[tuple[float, float, float]] = []
    for a, c, z in prof:
        if merged and abs(merged[-1][2] - z) < 1e-6 and abs(merged[-1][1] - a) < 1e-6:
            merged[-1] = (merged[-1][0], c, z)
        else:
            merged.append((a, c, z))
    if merged:  # snap ends so the profile spans exactly [0, L]
        merged[0] = (0.0, merged[0][1], merged[0][2])
        merged[-1] = (merged[-1][0], L, merged[-1][2])
    return merged or [(0.0, L, z_open)]


def _stepped_wall(p1, p2, z0, prof):
    """Wall polygon with a stepped top. The first four vertices are top-left, bottom-left, bottom-right,
    top-right, so vertices[1] and vertices[2] are always the base."""
    (x1, y1), (x2, y2) = p1, p2
    L = math.dist(p1, p2)
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    pt = lambda t, z: (x1 + ux * t, y1 + uy * t, z)  # noqa: E731
    top = []
    for a, c, z in reversed(prof):
        for q in (pt(c, z), pt(a, z)):
            if not top or math.dist(top[-1], q) > 1e-6:
                top.append(q)
    return [top[-1], (x1, y1, z0), (x2, y2, z0)] + top[:-1]


def _overlap_len(a: LineString, b: LineString, tol=TOL) -> float:
    """Length over which two segments are collinear and overlapping."""
    (x1, y1), (x2, y2) = a.coords
    L = a.length
    if L < 1e-9:
        return 0.0
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    (a0, b0), (a1, b1) = b.coords
    d0 = abs((a0 - x1) * uy - (b0 - y1) * ux)
    d1 = abs((a1 - x1) * uy - (b1 - y1) * ux)
    if d0 > tol or d1 > tol:
        return 0.0
    t0 = (a0 - x1) * ux + (b0 - y1) * uy
    t1 = (a1 - x1) * ux + (b1 - y1) * uy
    return max(0.0, min(L, max(t0, t1)) - max(0.0, min(t0, t1)))


def build(b: Building) -> dict:
    """Return {'surfaces': [...], 'zones': {...}, 'warnings': [...]}."""
    ids = _Ids()
    warns: list[str] = list(b.warnings)
    errs: list[str] = []
    surfaces: list[Surface] = []
    polys = {r.id: Polygon(r.polygon) for r in b.rooms}
    by_level: dict[str, list[Room]] = {}
    for r in b.rooms:
        by_level.setdefault(r.level, []).append(r)
    levels = b.levels
    level_idx = {lv.id: i for i, lv in enumerate(levels)}

    geometry_only = getattr(b, "geometry_only", False)

    def asm(room, cat):
        try:
            name, spec = assembly_for(b, room, cat)
        except ModelError:
            if geometry_only:  # QA before the envelope interview: geometry without thermal values
                return None, None
            raise
        return name, spec.get("u_si")

    def add(**kw) -> Surface:
        s = Surface(**kw)
        s.azimuth, s.tilt = orient(b, s.vertices)
        surfaces.append(s)
        return s

    # overlap check
    for lid, rooms in by_level.items():
        for i, r1 in enumerate(rooms):
            if not polys[r1.id].is_valid:
                errs.append(f"room {r1.id}: polygon is self-intersecting")
            for r2 in rooms[i + 1:]:
                ov = polys[r1.id].intersection(polys[r2.id]).area
                if ov > MIN_AREA:
                    errs.append(f"rooms {r1.id} and {r2.id} overlap by {ov:.2f} m2 on level {lid}")
    if errs:
        raise ModelError(errs)

    def room_z0(r: Room) -> float:
        return r.floor_elevation if r.floor_elevation is not None else b.level(r.level).elevation

    def room_top(r: Room) -> float:
        return room_z0(r) + r.ceiling_height

    # ---------------- walls ----------------
    for r in b.rooms:
        lv = b.level(r.level)
        below = lv.elevation < BELOW_GRADE_LEVEL
        up = levels[lv.index + 1] if lv.index + 1 < len(levels) else None
        above_union = unary_union([polys[o.id] for o in by_level.get(up.id, [])]) if up else None
        z0 = room_z0(r)
        z_open = z0 + r.ceiling_height
        z_next = max(lv.elevation + lv.floor_to_floor, z_open)  # underside of the next floor (band joist)
        has_above = above_union is not None and polys[r.id].intersection(above_union).area > MIN_AREA
        height = (z_next if has_above else z_open) - z0  # basement walls stay rectangular
        pts = r.polygon
        for ei, (p1, p2) in enumerate(zip(pts, pts[1:] + pts[:1])):
            seg = LineString([p1, p2])
            L = seg.length
            dx, dy = (p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L
            shared = []
            for o in by_level[r.level]:
                if o.id == r.id:
                    continue
                for a, c in _intervals(seg, polys[o.id]):
                    m = (a + c) / 2
                    probe = Point(p1[0] + dx * m + dy * 0.05, p1[1] + dy * m - dx * 0.05)
                    if polys[o.id].contains(probe):
                        shared.append((a, c, o))
            pieces = [(a, c, o) for a, c, o in shared] + [(a, c, None) for a, c in
                                                            _complement([(a, c) for a, c, _ in shared], L)]
            for a, c, o in sorted(pieces, key=lambda t: t[0]):
                q1 = (p1[0] + dx * a, p1[1] + dy * a)
                q2 = (p1[0] + dx * c, p1[1] + dy * c)
                if below:
                    prof = [(0.0, c - a, z0 + height)]
                else:
                    prof = _profile(LineString([q1, q2]), above_union, z_next, z_open)
                verts = _stepped_wall(q1, q2, z0, prof)
                sid = ids(f"{r.id}_wall")
                common = dict(id=sid, zone=r.id, room=r.id, level=r.level, kind="wall", vertices=verts,
                              azimuth=None, tilt=90.0, edge=ei, profile=prof)
                if o is None:
                    if not r.conditioned:
                        cat = "wall_garage_exterior" if r.type == "garage" else "wall_basement"
                    else:
                        cat = "wall_basement" if below else "wall_exterior"
                    name, u = asm(r, cat)
                    s = add(category=cat, boundary="foundation" if cat == "wall_basement" else "outside",
                            adjacent_zone=None, assembly=name, u_si=u, **common)
                    if cat == "wall_basement":
                        s.depth_below_grade = min(height, max(0.0, -lv.elevation))
                elif r.conditioned == o.conditioned:
                    add(category="wall_interior", boundary="adiabatic", adjacent_zone=o.id, **common)
                elif not r.conditioned:
                    continue  # the conditioned room's wall is mirrored into this zone below
                else:
                    unc = o if not o.conditioned else r
                    cat = "wall_to_garage" if unc.type == "garage" else "wall_to_basement_unconditioned"
                    cond_room = r if r.conditioned else o
                    name, u = asm(cond_room, cat)
                    add(category=cat, boundary="zone", adjacent_zone=o.id, assembly=name, u_si=u, **common)

    # pair interzone walls
    zone_walls = [s for s in surfaces if s.kind == "wall" and s.boundary == "zone"]
    for s in zone_walls:
        if s.other_side:
            continue
        for t in zone_walls:
            if t is s or t.other_side or t.zone != s.adjacent_zone or t.adjacent_zone != s.zone:
                continue
            (a1, b1), (a2, b2) = (s.vertices[1][:2], s.vertices[2][:2]), (t.vertices[1][:2], t.vertices[2][:2])
            if math.dist(a1, b2) < 2 * TOL and math.dist(b1, a2) < 2 * TOL:
                s.other_side, t.other_side = t.id, s.id
                break
        if not s.other_side:
            # partial overlap: give the mirrored geometry to the other zone
            mirror = list(reversed(s.vertices))
            L = math.dist(s.vertices[1][:2], s.vertices[2][:2])
            t = add(id=ids(f"{s.adjacent_zone}_wall"), zone=s.adjacent_zone, room=s.adjacent_zone,
                    level=s.level, kind="wall", category=s.category, boundary="zone", adjacent_zone=s.zone,
                    vertices=mirror, azimuth=None, tilt=90.0, assembly=s.assembly, u_si=s.u_si,
                    profile=[(L - c, L - a, z) for a, c, z in reversed(s.profile)])
            s.other_side, t.other_side = t.id, s.id

    # ---------------- floors & ceilings ----------------
    attic_parts: list[tuple[Polygon, float, Room, Surface]] = []
    crawl_parts: list[tuple[Polygon, Surface, float]] = []
    fnd = b.foundation
    for r in b.rooms:
        lv = b.level(r.level)
        rp = polys[r.id]
        below_rooms = [o for j in range(lv.index - 1, -1, -1) for o in by_level.get(levels[j].id, [])]
        above_rooms = [o for j in range(lv.index + 1, len(levels)) for o in by_level.get(levels[j].id, [])]
        z_floor, z_ceil = room_z0(r), room_top(r)

        # floors (nearest level first, then further down: split levels, partial basements)
        rest = rp
        for o in below_rooms:
            inter = rest.intersection(polys[o.id])
            for part in _simple_parts(inter):
                rest = rest.difference(part)
                if r.conditioned == o.conditioned:
                    add(id=ids(f"{r.id}_floor"), zone=r.id, room=r.id, level=r.level, kind="floor",
                        category="floor_interior", boundary="adiabatic", adjacent_zone=o.id,
                        vertices=_ring(part, z_floor, up=False), azimuth=None, tilt=180.0)
                elif r.conditioned:
                    cat = "floor_over_garage" if o.type == "garage" else "floor_over_basement_unconditioned"
                    name, u = asm(r, cat)
                    add(id=ids(f"{r.id}_floor"), zone=r.id, room=r.id, level=r.level, kind="floor",
                        category=cat, boundary="zone", adjacent_zone=o.id,
                        vertices=_ring(part, z_floor, up=False), azimuth=None, tilt=180.0, assembly=name, u_si=u)
                # else: unconditioned space over a conditioned room -> mirror of ceiling_to_garage, added below
        for part in _simple_parts(rest):
            ftype = r.floor
            if ftype == "auto":
                if z_floor < BELOW_GRADE_LEVEL:
                    ftype = "slab"
                elif z_floor <= NEAR_GRADE:  # e.g. main floor partly over a basement, rest on the foundation
                    ftype = {"slab": "slab", "crawlspace_vented": "crawlspace", "crawlspace_unvented": "crawlspace",
                             "exposed": "exposed", "basement": "slab"}[fnd["type"]]
                else:
                    ftype = "exposed"
                    warns.append(f"room {r.id}: {part.area:.1f} m2 of floor has nothing below and is treated as "
                                 "exposed to outdoor air (cantilever / over a porch); set room.floor if not")
            if r.type == "garage":
                ftype = "slab"
            if ftype == "slab":
                cat = "slab_garage" if r.type == "garage" else "slab"
                name, u = asm(r, cat)
                add(id=ids(f"{r.id}_slab"), zone=r.id, room=r.id, level=r.level, kind="floor", category=cat,
                    boundary="ground", adjacent_zone=None, vertices=_ring(part, z_floor, up=False), azimuth=None,
                    tilt=180.0, assembly=name, u_si=u)
            elif ftype == "crawlspace":
                name, u = asm(r, "floor_crawlspace")
                fs = add(id=ids(f"{r.id}_floor"), zone=r.id, room=r.id, level=r.level, kind="floor",
                         category="floor_crawlspace", boundary="zone", adjacent_zone="crawlspace",
                         vertices=_ring(part, z_floor, up=False), azimuth=None, tilt=180.0, assembly=name, u_si=u)
                crawl_parts.append((part, fs, z_floor))
            else:
                name, u = asm(r, "floor_exposed")
                add(id=ids(f"{r.id}_floor"), zone=r.id, room=r.id, level=r.level, kind="floor",
                    category="floor_exposed", boundary="outside", adjacent_zone=None,
                    vertices=_ring(part, z_floor, up=False), azimuth=None, tilt=180.0, assembly=name, u_si=u)

        # ceilings
        rest = rp
        for o in above_rooms:
            inter = rest.intersection(polys[o.id])
            for part in _simple_parts(inter):
                rest = rest.difference(part)
                if r.conditioned == o.conditioned:
                    add(id=ids(f"{r.id}_ceiling"), zone=r.id, room=r.id, level=r.level, kind="ceiling",
                        category="ceiling_interior", boundary="adiabatic", adjacent_zone=o.id,
                        vertices=_ring(part, z_ceil, up=True), azimuth=None, tilt=0.0)
                elif r.conditioned and o.type == "garage":
                    name, u = asm(r, "ceiling_to_garage")
                    add(id=ids(f"{r.id}_ceiling"), zone=r.id, room=r.id, level=r.level, kind="ceiling",
                        category="ceiling_to_garage", boundary="zone", adjacent_zone=o.id,
                        vertices=_ring(part, z_ceil, up=True), azimuth=None, tilt=0.0, assembly=name, u_si=u)
                # else: unconditioned room under a conditioned one -> mirror of floor_over_*, added below
        pitch = float(b.attic.get("roof_pitch", 6.0)) / 12.0
        for part in _simple_parts(rest):
            if r.ceiling == "attic":
                cat = "ceiling_garage" if r.type == "garage" else "ceiling_attic"
                name, u = asm(r, cat)
                cs = add(id=ids(f"{r.id}_ceiling"), zone=r.id, room=r.id, level=r.level, kind="ceiling",
                         category=cat, boundary="zone", adjacent_zone="attic", vertices=_ring(part, z_ceil, up=True),
                         azimuth=None, tilt=0.0, assembly=name, u_si=u)
                attic_parts.append((part, z_ceil, r, cs))
            else:
                cat = "roof_garage" if r.type == "garage" else ("roof_cathedral" if r.ceiling == "cathedral" else "roof_flat")
                name, u = asm(r, cat)
                s = add(id=ids(f"{r.id}_roof"), zone=r.id, room=r.id, level=r.level, kind="roof", category=cat,
                        boundary="outside", adjacent_zone=None, vertices=_ring(part, z_ceil, up=True), azimuth=None,
                        tilt=0.0, assembly=name, u_si=u)
                if r.ceiling == "cathedral":
                    s.area_factor = math.sqrt(1 + pitch * pitch)

    # ---------------- openings ----------------
    host_cats = {"wall_exterior", "wall_basement", "wall_garage_exterior", "wall_to_garage"}
    by_id = {s.id: s for s in surfaces}
    for o in b.openings:
        r = b.room(o.room)
        spec = b.fenestration.get(o.product) or {"u_si": None, "shgc": 0.0}
        if o.kind == "skylight":
            hosts = [s for s in surfaces if s.room == r.id and s.kind == "roof"]
            if not hosts:
                errs.append(f"opening {o.id}: skylights need a room with a cathedral or flat ceiling (room {r.id})")
                continue
            host = max(hosts, key=lambda s: s.area)
            c = Polygon([v[:2] for v in host.vertices]).centroid
            cx, cy = (o.at if o.at else (c.x, c.y))
            z = host.vertices[0][2] + 0.001
            hw, hh = o.width / 2, o.height / 2
            verts = [(cx - hw, cy - hh, z), (cx + hw, cy - hh, z), (cx + hw, cy + hh, z), (cx - hw, cy + hh, z)]
            sk = add(id=o.id, zone=r.id, room=r.id, level=r.level, kind="skylight", category="skylight",
                     boundary=host.boundary, adjacent_zone=None, vertices=verts, azimuth=None, tilt=0.0,
                     u_si=spec["u_si"], parent=host.id, product=o.product, shgc=spec.get("shgc"), label=o.label)
            host.children.append(sk.id)
            host._child_areas.append(sk.area)
            continue
        hosts = [s for s in surfaces if s.room == r.id and s.kind == "wall" and s.category in host_cats]
        if o.edge is not None:
            rawp = r.raw_polygon
            if not 0 <= o.edge < len(rawp):
                errs.append(f"opening {o.id}: edge {o.edge} out of range for room {r.id} ({len(rawp)} edges)")
                continue
            eseg = LineString([rawp[o.edge], rawp[(o.edge + 1) % len(rawp)]])
            hosts = [s for s in hosts if _overlap_len(LineString([s.vertices[1][:2], s.vertices[2][:2]]), eseg) > 0.05]
            if not hosts:
                errs.append(f"opening {o.id}: edge {o.edge} of room {r.id} (as written) has no exterior or garage "
                            "wall; use 'at' or check the edge index")
                continue
        if not hosts:
            errs.append(f"opening {o.id}: room {r.id} has no exterior or garage wall to host it")
            continue

        def dist(s):
            p = Point(o.at) if o.at else None
            return LineString([s.vertices[1][:2], s.vertices[2][:2]]).distance(p) if p else -LineString(
                [s.vertices[1][:2], s.vertices[2][:2]]).length

        host = min(hosts, key=dist)
        if o.at is not None and dist(host) > 1.0:
            errs.append(f"opening {o.id}: 'at' point is {dist(host):.2f} m from the nearest exterior wall of "
                        f"room {r.id}; check the coordinates")
            continue
        if not r.conditioned and host.category == "wall_to_garage" and host.other_side:
            # a door between garage and house entered on the garage: host it on the conditioned wall
            host = by_id[host.other_side]
            warns.append(f"opening {o.id}: entered on {r.id}, placed on the house side ({host.room})")
            r = b.room(host.room)
        base = LineString([host.vertices[1][:2], host.vertices[2][:2]])
        L = base.length
        margin = 0.01
        if o.width > L - 2 * margin:
            errs.append(f"opening {o.id}: width {o.width:.2f} m does not fit on wall {host.id} ({L:.2f} m)")
            continue
        t = base.project(Point(o.at)) if o.at else L / 2
        t = min(max(t, o.width / 2 + margin), L - o.width / 2 - margin)
        z0 = host.vertices[1][2]
        a_, c_ = t - o.width / 2, t + o.width / 2
        tops = [z for pa_, pc_, z in (host.profile or [(0.0, L, host.vertices[0][2])]) if pc_ > a_ and pa_ < c_]
        z1 = min(tops) if tops else host.vertices[0][2]
        bot = z0 + o.sill
        top = bot + o.height
        if top > z1 - margin:
            warns.append(f"opening {o.id}: head at {top - z0:.2f} m exceeds wall height {z1 - z0:.2f} m; lowered to fit")
            top = z1 - margin
            bot = max(z0 + margin if o.kind == "window" else z0, top - o.height)
        (x1, y1), (x2, y2) = base.coords
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        a, c = t - o.width / 2, t + o.width / 2
        pa, pc = (x1 + ux * a, y1 + uy * a), (x1 + ux * c, y1 + uy * c)
        verts = [(pa[0], pa[1], top), (pa[0], pa[1], bot), (pc[0], pc[1], bot), (pc[0], pc[1], top)]
        kind = "door" if o.kind == "door" else "window"
        op = add(id=o.id, zone=r.id, room=r.id, level=r.level, kind=kind, category=o.kind, boundary=host.boundary,
                 adjacent_zone=host.adjacent_zone, vertices=verts, azimuth=None, tilt=90.0, u_si=spec["u_si"],
                 parent=host.id, product=o.product, shgc=spec.get("shgc", 0.0), label=o.label)
        for other_id in host.children:
            other = next(s for s in surfaces if s.id == other_id)
            oa = LineString([other.vertices[1][:2], other.vertices[2][:2]])
            ob = LineString([pa, pc])
            if oa.buffer(0.001).intersection(ob).length > 0.01:
                zo = (other.vertices[1][2], other.vertices[0][2])
                if not (top <= zo[0] or bot >= zo[1]):
                    warns.append(f"openings {other.id} and {o.id} overlap on wall {host.id}")
        host.children.append(op.id)
        host._child_areas.append(op.area)

    # split levels: exterior walls that actually touch a room on another level
    for w in [x for x in surfaces if x.kind == "wall" and x.boundary == "outside" and x.room]:
        (xa, ya, _), (xb, yb, _) = w.vertices[1], w.vertices[2]
        L = math.hypot(xb - xa, yb - ya)
        if L < 0.1:
            continue
        mx, my = (xa + xb) / 2 + (yb - ya) / L * 0.05, (ya + yb) / 2 - (xb - xa) / L * 0.05
        zw0, zw1 = w.vertices[1][2], max(v[2] for v in w.vertices)
        for x in b.rooms:
            if x.level == w.level or not polys[x.id].contains(Point(mx, my)):
                continue
            ov = min(zw1, room_top(x)) - max(zw0, room_z0(x))
            if ov > 0.5:
                warns.append(f"wall {w.id} ({w.room}) touches room {x.id} on level {x.level} over {ov:.1f} m of "
                             "height (split level); modelled as exterior, which overstates its load")
                break

    # ---------------- attic ----------------
    zones = {r.id: {"kind": "room", "conditioned": r.conditioned, "type": r.type, "level": r.level,
                    "floor_area": polys[r.id].area, "volume": polys[r.id].area * r.ceiling_height}
             for r in b.rooms}
    if attic_parts:
        # one attic zone per ceiling height (e.g. a one-storey wing next to a two-storey block);
        # the highest is "attic", the others "attic2", "attic3", ...
        clusters: list[list] = []
        for part in sorted(attic_parts, key=lambda t: -t[1]):
            for cl in clusters:
                if abs(cl[0] - part[1]) <= 0.3:
                    cl[1].append(part)
                    break
            else:
                clusters.append([part[1], [part]])
        rname, ru = asm(None, "roof_attic")
        for i, (_, parts) in enumerate(clusters):
            zid = "attic" if i == 0 else f"attic{i + 1}"
            base_z = max(z for _, z, _, _ in parts)
            foot = unary_union([p for p, _, _, _ in parts])
            for p, z, rr, cs in parts:
                f = add(id=ids(f"{zid}_floor"), zone=zid, room=None, level=None, kind="floor",
                        category="attic_floor", boundary="zone", adjacent_zone=rr.id, vertices=_ring(p, z, up=False),
                        azimuth=None, tilt=180.0)
                f.other_side, cs.other_side = cs.id, f.id
                cs.adjacent_zone = zid
            roof_surfs, gables, vol = _roof(b, foot, base_z, warns)
            for verts in roof_surfs:
                add(id=ids(f"{zid}_roof"), zone=zid, room=None, level=None, kind="roof", category="roof_attic",
                    boundary="outside", adjacent_zone=None, vertices=verts, azimuth=None, tilt=0.0, assembly=rname,
                    u_si=ru)
            if gables:
                gname, gu = asm(None, "wall_attic_gable")
                for verts in gables:
                    add(id=ids(f"{zid}_gable"), zone=zid, room=None, level=None, kind="wall",
                        category="wall_attic_gable", boundary="outside", adjacent_zone=None, vertices=verts,
                        azimuth=None, tilt=90.0, assembly=gname, u_si=gu)
            zones[zid] = {"kind": "attic", "conditioned": False, "type": f"attic_{b.attic['type']}",
                          "floor_area": foot.area, "volume": vol}
        if len(clusters) > 1:
            warns.append(f"{len(clusters)} attic zones at different ceiling heights; walls of upper storeys above a "
                         "lower roof are treated as exterior walls (slightly conservative)")

    # ---------------- crawlspace ----------------
    if crawl_parts:
        depth = float(fnd.get("depth_below_grade", 0.0))
        foot = unary_union([p for p, _, _ in crawl_parts])
        z_top = max(z for _, _, z in crawl_parts)
        z_bot = -depth
        if z_top - z_bot < 0.1:
            errs.append(f"crawlspace height {z_top - z_bot:.2f} m: check the floor elevation and "
                        "foundation.depth_below_grade")
        basement = unary_union([polys[x.id] for x in b.rooms if room_z0(x) < BELOW_GRADE_LEVEL])
        wname, wu = asm(None, "wall_crawlspace")
        per = 0.0
        for poly in _simple_parts(foot) if foot.geom_type != "Polygon" or foot.interiors else [foot]:
            ring = list(poly.exterior.coords)[:-1]
            if not Polygon(ring).exterior.is_ccw:
                ring.reverse()
            for p1, p2 in zip(ring, ring[1:] + ring[:1]):
                if math.dist(p1, p2) < 2 * TOL:
                    continue
                seg = LineString([p1, p2])
                keep = _complement(_covered(seg, basement), seg.length) if not basement.is_empty else [(0, seg.length)]
                ux, uy = (p2[0] - p1[0]) / seg.length, (p2[1] - p1[1]) / seg.length
                for a, c in keep:  # the stretch along a basement is that basement's foundation wall
                    q1, q2 = (p1[0] + ux * a, p1[1] + uy * a), (p1[0] + ux * c, p1[1] + uy * c)
                    s = add(id=ids("crawl_wall"), zone="crawlspace", room=None, level=None, kind="wall",
                            category="wall_crawlspace", boundary="foundation", adjacent_zone=None,
                            vertices=_wall_verts(q1, q2, z_bot, z_top), azimuth=None, tilt=90.0, assembly=wname,
                            u_si=wu)
                    s.depth_below_grade = depth
                    per += c - a
        for p, fs, zf in crawl_parts:
            c = add(id=ids("crawl_ceiling"), zone="crawlspace", room=None, level=None, kind="ceiling",
                    category="crawl_ceiling", boundary="zone", adjacent_zone=fs.zone,
                    vertices=_ring(p, zf, up=True), azimuth=None, tilt=0.0)
            c.other_side, fs.other_side = fs.id, c.id
        sname, su = asm(None, "slab_crawlspace")
        for part in _simple_parts(foot) if (foot.geom_type != "Polygon" or foot.interiors) else [foot]:
            s = add(id=ids("crawl_floor"), zone="crawlspace", room=None, level=None, kind="floor",
                    category="slab_crawlspace", boundary="ground", adjacent_zone=None,
                    vertices=_ring(part, z_bot, up=False), azimuth=None, tilt=180.0, assembly=sname, u_si=su)
        zones["crawlspace"] = {"kind": "crawlspace", "conditioned": False,
                               "type": fnd["type"], "floor_area": foot.area,
                               "volume": foot.area * (z_top - z_bot), "perimeter": per}

    # pair garage floors/ceilings (floor over garage, garage ceiling under room)
    for s in list(surfaces):
        if s.category in ("floor_over_garage", "floor_over_basement_unconditioned", "ceiling_to_garage") and not s.other_side:
            v = list(reversed(s.vertices))
            t = add(id=ids(f"{s.adjacent_zone}_{'ceiling' if s.kind == 'floor' else 'floor'}"), zone=s.adjacent_zone,
                    room=s.adjacent_zone, level=b.room(s.adjacent_zone).level,
                    kind="ceiling" if s.kind == "floor" else "floor", category=s.category, boundary="zone",
                    adjacent_zone=s.zone, vertices=v, azimuth=None, tilt=0.0, assembly=s.assembly, u_si=s.u_si)
            s.other_side, t.other_side = t.id, s.id

    # slab exposed perimeters: exterior wall length of the owning room on its level
    for s in surfaces:
        if s.category in ("slab", "slab_garage"):
            slab_poly = Polygon([v[:2] for v in s.vertices])
            per = 0.0
            for w in surfaces:
                if w.room == s.room and w.kind == "wall" and w.boundary in ("outside", "foundation"):
                    seg = LineString([w.vertices[1][:2], w.vertices[2][:2]])
                    per += seg.intersection(slab_poly.boundary.buffer(TOL)).length
            s.exposed_perimeter = per
        if s.category == "slab_crawlspace":
            s.exposed_perimeter = zones["crawlspace"]["perimeter"]

    if errs:
        raise ModelError(errs)
    return {"surfaces": surfaces, "zones": zones, "warnings": warns}


# ---------------- roofs ----------------

def _rectangles(poly: Polygon):
    """Decompose a rectilinear polygon (axis-aligned edges) into non-overlapping rectangles."""
    coords = list(poly.exterior.coords)
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        if abs(x1 - x2) > 1e-3 and abs(y1 - y2) > 1e-3:
            return None
    xs = sorted({round(x, 3) for x, _ in coords})
    ys = sorted({round(y, 3) for _, y in coords})
    cells = [[poly.buffer(-1e-4).contains(Point((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2))
              for j in range(len(ys) - 1)] for i in range(len(xs) - 1)]
    used = [[False] * (len(ys) - 1) for _ in range(len(xs) - 1)]
    rects = []
    # greedy: largest-area rectangles first
    while True:
        best = None
        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                if not cells[i][j] or used[i][j]:
                    continue
                # grow in x then y
                for i2 in range(i, len(xs) - 1):
                    if not cells[i2][j] or used[i2][j]:
                        break
                    j2 = j
                    while j2 + 1 < len(ys) - 1 and all(cells[k][j2 + 1] and not used[k][j2 + 1] for k in range(i, i2 + 1)):
                        j2 += 1
                    area = (xs[i2 + 1] - xs[i]) * (ys[j2 + 1] - ys[j])
                    if best is None or area > best[0]:
                        best = (area, i, i2, j, j2)
        if best is None:
            break
        _, i, i2, j, j2 = best
        for a in range(i, i2 + 1):
            for c in range(j, j2 + 1):
                used[a][c] = True
        rects.append(box(xs[i], ys[j], xs[i2 + 1], ys[j2 + 1]))
    return rects


def _outward(verts, center):
    """Reverse vertex order if the polygon normal points toward `center` (x, y, z)."""
    nx, ny, nz = newell_normal(verts)
    cx = sum(v[0] for v in verts) / len(verts) - center[0]
    cy = sum(v[1] for v in verts) / len(verts) - center[1]
    cz = sum(v[2] for v in verts) / len(verts) - center[2]
    return verts if nx * cx + ny * cy + nz * cz >= 0 else list(reversed(verts))


def _roof(b: Building, foot, base_z: float, warns: list[str]):
    """Roof planes and gable walls above the attic footprint. Returns (roofs, gables, volume).

    Each roof section is a rectangle (from attic.roof_sections, or an automatic rectilinear
    decomposition of the attic footprint) roofed as hip (default), gable, shed or flat at a
    uniform pitch. Gable ends shared by two sections are omitted (they are inside the attic).
    """
    pitch = float(b.attic.get("roof_pitch", 6.0)) / 12.0
    sections = b.attic.get("roof_sections")
    rects = []
    if sections:
        for sec in sections:
            poly = Polygon(sec["polygon"])
            if poly.intersection(foot).area >= 0.5 * poly.area:
                rects.append((poly, sec.get("type", "hip"), sec.get("ridge")))
    else:
        for poly in getattr(foot, "geoms", [foot]):
            rr = _rectangles(poly.simplify(0.001))
            if rr is None:
                warns.append("attic footprint is not rectilinear; roof drawn as a flat plane at mid-rise "
                             "(set attic.roof_sections for a pitched roof)")
                rects.append((poly, "flat", None))
            else:
                rects += [(r, "hip", None) for r in rr]
    all_rects = [r for r, _, _ in rects]
    roofs, gables, vol = [], [], 0.0
    for poly, typ, ridge in rects:
        minx, miny, maxx, maxy = poly.bounds
        lx, ly = maxx - minx, maxy - miny
        is_rect = len(poly.exterior.coords) == 5 and abs(poly.area - lx * ly) < 1e-3
        if typ == "flat" or not is_rect:
            if typ != "flat":
                warns.append("roof section is not an axis-aligned rectangle; drawn flat at mid-rise")
            rise = min(lx, ly) / 2 * pitch
            roofs.append(_ring(poly, base_z + rise / 2, up=True))
            vol += poly.area * rise / 2
            continue
        along_x = (ridge == "x") if ridge else lx >= ly
        span = ly if along_x else lx
        rise = span / 2 * pitch
        zr = base_z + rise
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        ctr = (cx, cy, base_z + rise / 3)
        c00, c10, c11, c01 = (minx, miny, base_z), (maxx, miny, base_z), (maxx, maxy, base_z), (minx, maxy, base_z)
        planes, ends = [], []
        if typ == "gable":
            if along_x:
                r0, r1 = (minx, cy, zr), (maxx, cy, zr)
                planes += [[c00, c10, r1, r0], [c11, c01, r0, r1]]
                ends += [([c00, c01, r0], LineString([c00[:2], c01[:2]])), ([c10, c11, r1], LineString([c10[:2], c11[:2]]))]
            else:
                r0, r1 = (cx, miny, zr), (cx, maxy, zr)
                planes += [[c10, c11, r1, r0], [c01, c00, r0, r1]]
                ends += [([c00, c10, r0], LineString([c00[:2], c10[:2]])), ([c01, c11, r1], LineString([c01[:2], c11[:2]]))]
            vol += poly.area * rise / 2
        elif typ == "shed":
            top = base_z + span * pitch
            ctr = (cx, cy, base_z + span * pitch / 3)
            if along_x:  # slopes up toward +y
                h11, h01 = (maxx, maxy, top), (minx, maxy, top)
                planes.append([c00, c10, h11, h01])
                ends += [([c00, c01, h01], LineString([c00[:2], c01[:2]])),
                         ([c10, c11, h11], LineString([c10[:2], c11[:2]])),
                         ([c01, c11, h11, h01], LineString([c01[:2], c11[:2]]))]
            else:  # slopes up toward +x
                h10, h11 = (maxx, miny, top), (maxx, maxy, top)
                planes.append([c00, h10, h11, c01])
                ends += [([c00, c10, h10], LineString([c00[:2], c10[:2]])),
                         ([c01, c11, h11], LineString([c01[:2], c11[:2]])),
                         ([c10, c11, h11, h10], LineString([c10[:2], c11[:2]]))]
            vol += poly.area * span * pitch / 2
        else:  # hip
            half = span / 2
            if along_x:
                r0, r1 = (minx + half, cy, zr), (maxx - half, cy, zr)
            else:
                r0, r1 = (cx, miny + half, zr), (cx, maxy - half, zr)
            if math.dist(r0, r1) < 1e-3:
                apex = (cx, cy, zr)
                planes += [[c00, c10, apex], [c10, c11, apex], [c11, c01, apex], [c01, c00, apex]]
            elif along_x:
                planes += [[c00, c10, r1, r0], [c11, c01, r0, r1], [c10, c11, r1], [c01, c00, r0]]
            else:
                planes += [[c10, c11, r1, r0], [c01, c00, r0, r1], [c11, c01, r1], [c00, c10, r0]]
            vol += poly.area * rise / 3
        roofs += [_outward(v, ctr) for v in planes]
        for verts, base_line in ends:
            shared = any(o is not poly and base_line.intersection(o.boundary.buffer(TOL)).length > base_line.length * 0.5
                         for o in all_rects)
            if not shared:
                gables.append(_outward(verts, (cx, cy, base_z)))
    return roofs, gables, vol


def summarize(geo: dict) -> dict:
    """Areas by zone and category (m2), for QA and the takeoff table."""
    out: dict = {}
    for s in geo["surfaces"]:
        z = out.setdefault(s.zone, {})
        key = s.category
        z[key] = z.get(key, 0.0) + (s.net_area if s.kind in ("wall", "roof", "ceiling", "floor") else s.area)
    return out
