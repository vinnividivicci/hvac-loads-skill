"""Self-contained interactive 3D viewer (single HTML file) of the exact surfaces used in the calculation.

three.js is loaded from the jsDelivr CDN at view time (internet needed to open the page).
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Building
from .units import W_PER_BTUH, m2_to_ft2

TYPE_COLORS = {
    "wall_exterior": "#d9a066", "wall_basement": "#8c7a6b", "wall_crawlspace": "#8c7a6b",
    "wall_to_garage": "#c97b63", "wall_to_basement_unconditioned": "#c97b63", "wall_garage_exterior": "#b5b5a8",
    "wall_attic_gable": "#c9b18f", "wall_interior": "#e8e4dc", "ceiling_attic": "#f2e8c9",
    "ceiling_interior": "#efece6", "ceiling_to_garage": "#c97b63", "ceiling_garage": "#cfcfc4",
    "roof_attic": "#7a4e3a", "roof_cathedral": "#8b5a44", "roof_flat": "#6f5b52", "roof_garage": "#6d6d63",
    "floor_crawlspace": "#b8a48c", "floor_exposed": "#a0522d", "floor_over_garage": "#c97b63",
    "floor_over_basement_unconditioned": "#c97b63", "floor_interior": "#ddd6c8", "slab": "#9e9e9e",
    "slab_garage": "#8f8f86", "slab_crawlspace": "#7d6f60", "attic_floor": "#e8dcb5", "crawl_ceiling": "#b8a48c",
    "window": "#5fa8d3", "glass_door": "#5fa8d3", "skylight": "#5fa8d3", "door": "#6b4f3a",
}

TEMPLATE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --bg:#f6f4ef; --panel:#ffffffee; --ink:#1f2328; --muted:#5b636e; --line:#d7d2c8; --accent:#2f6f9f; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#15181c; --panel:#1f242bee; --ink:#e8eaed; --muted:#9aa4b1; --line:#343b45; --accent:#7fb3dd; } }
:root[data-theme="dark"] { --bg:#15181c; --panel:#1f242bee; --ink:#e8eaed; --muted:#9aa4b1; --line:#343b45; --accent:#7fb3dd; }
html,body { margin:0; height:100%; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; overflow:hidden; }
#c { position:fixed; inset:0; width:100vw; height:100vh; display:block; }
#panel { position:fixed; top:12px; left:12px; width:290px; max-height:calc(100% - 24px); overflow:auto; background:var(--panel);
  border:1px solid var(--line); border-radius:10px; padding:12px 14px; box-shadow:0 4px 18px #0002; }
#panel h1 { font-size:15px; margin:0 0 2px; } #panel .sub { color:var(--muted); font-size:12px; margin-bottom:10px; }
label { display:block; margin:3px 0; cursor:pointer; } select { width:100%; padding:4px; background:var(--bg); color:var(--ink); border:1px solid var(--line); border-radius:6px; }
.sec { border-top:1px solid var(--line); margin-top:10px; padding-top:8px; } .sec b { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
#legend div { display:flex; align-items:center; gap:6px; font-size:12px; margin:2px 0; } #legend i { width:14px; height:14px; border-radius:3px; display:inline-block; border:1px solid #0003; }
#info { font-size:12px; white-space:pre-wrap; word-break:break-word; min-height:40px; }
#compass { position:fixed; right:16px; top:16px; width:64px; height:64px; }
#toggle { display:none; position:fixed; left:12px; top:12px; z-index:2; }
@media (max-width:640px) { #panel { width:calc(100% - 56px); max-height:45%; top:auto; bottom:12px; } }
button { flex:1; padding:4px 6px; background:var(--bg); color:var(--ink); border:1px solid var(--line); border-radius:6px; cursor:pointer; }
.lbl { position:fixed; transform:translate(-50%,-50%); font-size:11px; padding:1px 4px; border-radius:4px; background:#ffffffcc; color:#1f2328; pointer-events:none; white-space:nowrap; }
.bar { height:10px; border-radius:5px; background:linear-gradient(90deg,#2c7bb6,#abd9e9,#ffffbf,#fdae61,#d7191c); margin:4px 0; }
</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.min.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/"}}</script>
</head>
<body>
<canvas id="c"></canvas>
<div id="panel">
  <h1>__TITLE__</h1>
  <div class="sub">__SUBTITLE__</div>
  <label>{Colour by}
    <select id="mode">
      <option value="type">{Surface type}</option>
      <option value="boundary">{Boundary condition}</option>
      <option value="u">{U-value (W/m²K)}</option>
      <option value="heat">{Room heating load (W/m² floor)}</option>
      <option value="cool">{Room sensible cooling (W/m² floor)}</option>
    </select></label>
  <div class="sec"><b>{Show}</b><div id="levels"></div>
    <label><input type="checkbox" id="showRoof" checked> {Roof / attic}</label>
    <label><input type="checkbox" id="showCrawl" checked> {Crawlspace / foundation}</label>
    <label><input type="checkbox" id="showInterior"> {Interior partitions}</label>
    <label><input type="checkbox" id="xray"> {X-ray (translucent)}</label>
    <label><input type="checkbox" id="labels" checked> {Room labels}</label>
    <label><input type="checkbox" id="grade"> {Grade plane}</label>
    <div style="display:flex;gap:6px;margin-top:6px"><button id="top">{Top view}</button><button id="iso">{3D view}</button></div>
  </div>
  <div class="sec"><b>{Legend}</b><div id="legend"></div></div>
  <div class="sec"><b>{Selection}</b><div id="info">{Click a surface.}</div></div>
</div>
<div id="labelLayer"></div>
<svg id="compass" viewBox="-32 -32 64 64"><circle r="30" fill="var(--panel)" stroke="var(--line)"/><g id="needle"><path d="M0,-24 L7,6 L0,1 L-7,6Z" fill="#c0392b"/><text y="-12" text-anchor="middle" font-size="10" fill="var(--ink)" dy="-14">N</text></g></svg>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
const DATA = __DATA__;
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias:true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const css = getComputedStyle(document.documentElement);
scene.background = new THREE.Color(css.getPropertyValue('--bg').trim() || '#f6f4ef');
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 2000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x888877, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(30, 60, 20); scene.add(sun);
const P = (v) => new THREE.Vector3(v[0], v[2], -v[1]);   // plan (x,y,z) -> three (x,z,-y), y up
const groups = [];
const meshes = [];
function tri(verts) {
  const pts = verts.map(P);
  const n = new THREE.Vector3();
  for (let i = 0; i < pts.length; i++) { const a = pts[i], b = pts[(i+1)%pts.length];
    n.x += (a.y - b.y) * (a.z + b.z); n.y += (a.z - b.z) * (a.x + b.x); n.z += (a.x - b.x) * (a.y + b.y); }
  n.normalize();
  const u = new THREE.Vector3().subVectors(pts[1], pts[0]).normalize();
  const w = new THREE.Vector3().crossVectors(n, u).normalize();
  const flat = pts.map(p => new THREE.Vector2(p.clone().sub(pts[0]).dot(u), p.clone().sub(pts[0]).dot(w)));
  let faces = THREE.ShapeUtils.triangulateShape(flat, []);
  const pos = []; for (const p of pts) pos.push(p.x, p.y, p.z);
  const idx = []; for (const f of faces) idx.push(f[0], f[1], f[2]);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
  return g;
}
function ramp(t) { const stops = [[44,123,182],[171,217,233],[255,255,191],[253,174,97],[215,25,28]];
  t = Math.max(0, Math.min(1, t)); const x = t * (stops.length - 1); const i = Math.min(stops.length - 2, Math.floor(x)); const f = x - i;
  const c = stops[i].map((v, k) => Math.round(v + (stops[i+1][k] - v) * f)); return `rgb(${c[0]},${c[1]},${c[2]})`; }
const BOUNDARY = { outside:'#e07b39', ground:'#7d6f60', foundation:'#9c8b77', zone:'#c97b63', adiabatic:'#e8e4dc' };
function colorFor(s, mode) {
  if (['window','glass_door','skylight'].includes(s.category)) return '#5fa8d3';
  if (mode === 'type') return DATA.typeColors[s.category] || '#bbbbbb';
  if (mode === 'boundary') return BOUNDARY[s.boundary] || '#bbbbbb';
  if (mode === 'u') { if (s.u == null) return '#e8e4dc'; return ramp((s.u - DATA.uRange[0]) / ((DATA.uRange[1] - DATA.uRange[0]) || 1)); }
  const r = DATA.rooms[s.zone]; const key = mode === 'heat' ? 'heat' : 'cool';
  if (!r || r[key] == null) return '#d9d6cf';
  const rng = DATA.loadRange[key]; return ramp((r[key] - rng[0]) / ((rng[1] - rng[0]) || 1));
}
const root = new THREE.Group(); scene.add(root);
for (const s of DATA.surfaces) {
  const g = tri(s.v);
  const glass = ['window','glass_door','skylight'].includes(s.category);
  const mat = new THREE.MeshStandardMaterial({ color:'#cccccc', side:THREE.DoubleSide, roughness:.85, metalness:0,
    transparent: glass, opacity: glass ? .55 : 1, polygonOffset:true, polygonOffsetFactor: glass || s.kind === 'door' ? -2 : 1, polygonOffsetUnits:1 });
  const m = new THREE.Mesh(g, mat); m.userData = s;
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({ color:0x333333, transparent:true, opacity:.35 }));
  m.add(edges); root.add(m); meshes.push(m);
}
const box = new THREE.Box3().setFromObject(root); const ctr = box.getCenter(new THREE.Vector3()); const size = box.getSize(new THREE.Vector3()).length();
function isoView() { controls.target.copy(ctr); camera.up.set(0, 1, 0); camera.position.set(ctr.x + size * .95, ctr.y + size * .8, ctr.z + size * 1.1); controls.update(); }
function topView() { controls.target.copy(ctr); camera.position.set(ctr.x, ctr.y + size * 1.6, ctr.z + 0.001); controls.update(); }
camera.near = size / 200; camera.far = size * 20; camera.updateProjectionMatrix(); isoView();
document.getElementById('top').onclick = () => { document.getElementById('showRoof').checked = false; refresh(); topView(); };
document.getElementById('iso').onclick = isoView;
// room labels at each room's floor centroid (HTML overlay)
const labels = [];
for (const [id, r] of Object.entries(DATA.rooms)) {
  if (!r.c) continue;
  const el = document.createElement('div'); el.className = 'lbl'; el.textContent = r.name;
  document.getElementById('labelLayer').appendChild(el);
  labels.push({ el, p: P(r.c), level: r.level });
}
const lv = document.getElementById('levels'); const levelOn = {};
for (const l of DATA.levels) { levelOn[l.id] = true; const el = document.createElement('label');
  el.innerHTML = `<input type="checkbox" checked data-l="${l.id}"> ${l.name}`; lv.appendChild(el); }
lv.addEventListener('change', e => { levelOn[e.target.dataset.l] = e.target.checked; refresh(); });
for (const id of ['mode','showRoof','showCrawl','showInterior','xray','labels','grade']) document.getElementById(id).addEventListener('change', refresh);
// grade plane (z = 0) so below-grade parts read correctly
const gsize = box.getSize(new THREE.Vector3());
const ground = new THREE.Mesh(new THREE.PlaneGeometry(gsize.x * 1.6, gsize.z * 1.6),
  new THREE.MeshStandardMaterial({ color: 0x7d9a5b, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false }));
ground.rotation.x = -Math.PI / 2; ground.position.set(ctr.x, 0, ctr.z); ground.visible = false; scene.add(ground);
function visible(s) {
  const roofZone = s.zone.startsWith('attic') || s.kind === 'roof';
  if (roofZone && !document.getElementById('showRoof').checked) return false;
  if (s.zone === 'crawlspace' && !document.getElementById('showCrawl').checked) return false;
  if (s.boundary === 'adiabatic' && s.kind === 'wall' && !document.getElementById('showInterior').checked) return false;
  if (s.level && levelOn[s.level] === false) return false;
  return true;
}
function legend(mode) {
  const L = document.getElementById('legend'); L.innerHTML = '';
  const add = (c, t) => { const d = document.createElement('div'); d.innerHTML = `<i style="background:${c}"></i>${t}`; L.appendChild(d); };
  if (mode === 'type') { const seen = new Set(DATA.surfaces.map(s => s.category)); for (const [k, c] of Object.entries(DATA.typeColors)) if (seen.has(k)) add(c, k.replaceAll('_',' ')); }
  else if (mode === 'boundary') { for (const [k, c] of Object.entries(BOUNDARY)) add(c, k); }
  else { const rng = mode === 'u' ? DATA.uRange : DATA.loadRange[mode === 'heat' ? 'heat' : 'cool'];
    const ip = DATA.ip; const k = mode === 'u' ? (ip ? 1 / 5.678263 : 1) : (ip ? 0.316998 : 1);
    const unit = mode === 'u' ? (ip ? 'Btu/h·ft²·°F' : 'W/m²K') : (ip ? 'Btu/h·ft²' : 'W/m²');
    const nd = mode === 'u' ? (ip ? 3 : 2) : (ip ? 1 : 0);
    L.innerHTML = `<div class="bar"></div><div style="display:flex;justify-content:space-between"><span>${(rng[0]*k).toFixed(nd)}</span><span>${(rng[1]*k).toFixed(nd)} ${unit}</span></div>`; }
}
function refresh() {
  const mode = document.getElementById('mode').value; const xr = document.getElementById('xray').checked;
  for (const m of meshes) { const s = m.userData; m.visible = visible(s); m.material.color.set(colorFor(s, mode));
    const glass = ['window','glass_door','skylight'].includes(s.category);
    m.material.transparent = glass || xr; m.material.opacity = glass ? .55 : (xr ? .25 : 1); m.material.depthWrite = !(glass || xr); m.material.needsUpdate = true; }
  legend(mode);
  const show = document.getElementById('labels').checked;
  for (const l of labels) l.el.style.display = show && levelOn[l.level] !== false ? '' : 'none';
  ground.visible = document.getElementById('grade').checked;
}
const Q = new URLSearchParams(location.search);
if (Q.get('mode')) document.getElementById('mode').value = Q.get('mode');
for (const [k, id] of [['roof', 'showRoof'], ['crawl', 'showCrawl'], ['interior', 'showInterior'], ['xray', 'xray'],
                       ['labels', 'labels'], ['grade', 'grade']]) if (Q.has(k)) document.getElementById(id).checked = Q.get(k) === '1';
const wanted = Q.get('level');
if (wanted && DATA.levels.some(l => l.id === wanted || l.name === wanted)) { for (const l of DATA.levels) {
  levelOn[l.id] = l.id === wanted || l.name === wanted;
  const cb = document.querySelector(`input[data-l="${l.id}"]`); if (cb) cb.checked = levelOn[l.id]; } }
refresh();
if (Q.get('view') === 'top') topView();
const ray = new THREE.Raycaster(); const mouse = new THREE.Vector2(); let down = null;
canvas.addEventListener('pointerdown', e => down = [e.clientX, e.clientY]);
canvas.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  const r = canvas.getBoundingClientRect(); mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera); const hit = ray.intersectObjects(meshes.filter(m => m.visible), false)[0];
  const info = document.getElementById('info'); if (!hit) { info.textContent = 'Click a surface.'; return; }
  const s = hit.object.userData; const room = DATA.rooms[s.zone];
  let t = `${s.id}\n${s.category.replaceAll('_',' ')} → ${s.boundary}${s.adj ? ' (' + s.adj + ')' : ''}\n` +
          `area ${s.a.toFixed(2)} m² (${(s.a * 10.7639).toFixed(1)} ft²)` + (s.u != null ? `\nU ${s.u.toFixed(3)} W/m²K (R-${(5.678263 / s.u).toFixed(1)} IP)` : '') +
          (s.az != null ? `\nfacing ${s.az.toFixed(0)}°` : '') + (s.asm ? `\nassembly: ${s.asm}` : '') + (s.label ? `\nlabel: ${s.label}` : '');
  if (room) t += `\n\nROOM ${room.name}\nfloor ${room.area.toFixed(1)} m² (${(room.area * 10.7639).toFixed(0)} ft²)` +
     (room.heatW != null ? `\nheating ${room.heatW.toFixed(0)} W (${room.heatBtu.toFixed(0)} Btu/h)\ncooling ${room.coolW.toFixed(0)} W sensible (${room.coolBtu.toFixed(0)} Btu/h)` : '');
  info.textContent = t;
});
const needle = document.getElementById('needle'); const v = new THREE.Vector3();
function resize() { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
addEventListener('resize', resize); resize();
(function loop() { requestAnimationFrame(loop); controls.update();
  camera.getWorldDirection(v); const az = Math.atan2(v.x, -v.z) * 180 / Math.PI;   // camera heading in plan (sheet-up = 0)
  needle.setAttribute('transform', `rotate(${-(az) - DATA.planNorth})`);
  const r = canvas.getBoundingClientRect();
  for (const l of labels) { if (l.el.style.display === 'none') continue; const q = l.p.clone().project(camera);
    l.el.style.left = `${(q.x + 1) / 2 * r.width}px`; l.el.style.top = `${(1 - q.y) / 2 * r.height}px`;
    l.el.style.visibility = q.z < 1 ? 'visible' : 'hidden'; }
  renderer.render(scene, camera); })();
</script>
</body>
</html>
"""


UI = {"en": {'Colour by': 'Colour by', 'Surface type': 'Surface type', 'Boundary condition': 'Boundary condition', 'U-value (W/m²K)': 'U-value', 'Room heating load (W/m² floor)': 'Room heating load (per floor area)', 'Room sensible cooling (W/m² floor)': 'Room sensible cooling (per floor area)', 'Show': 'Show', 'Roof / attic': 'Roof / attic', 'Crawlspace / foundation': 'Crawlspace / foundation', 'Interior partitions': 'Interior partitions', 'X-ray (translucent)': 'X-ray (translucent)', 'Room labels': 'Room labels', 'Grade plane': 'Grade plane', 'Top view': 'Top view', '3D view': '3D view', 'Legend': 'Legend', 'Selection': 'Selection', 'Click a surface.': 'Click a surface.'}, "fr": {'Colour by': 'Couleur selon', 'Surface type': 'Type de surface', 'Boundary condition': 'Condition limite', 'U-value (W/m²K)': 'Valeur U', 'Room heating load (W/m² floor)': 'Charge de chauffage (par surface)', 'Room sensible cooling (W/m² floor)': 'Climatisation sensible (par surface)', 'Show': 'Afficher', 'Roof / attic': 'Toit / entretoit', 'Crawlspace / foundation': 'Vide sanitaire / fondation', 'Interior partitions': 'Cloisons intérieures', 'X-ray (translucent)': 'Rayons X (translucide)', 'Room labels': 'Noms des pièces', 'Grade plane': 'Niveau du sol', 'Top view': 'Vue en plan', '3D view': 'Vue 3D', 'Legend': 'Légende', 'Selection': 'Sélection', 'Click a surface.': 'Cliquez une surface.'}}


def build(b: Building, geo: dict, out_html: Path, results: dict | None = None, subtitle: str = "",
          lang: str = "en") -> str:
    surfs = []
    us = []
    for s in geo["surfaces"]:
        net = s.net_area if s.kind in ("wall", "roof", "ceiling", "floor") else s.area
        surfs.append({"id": s.id, "zone": s.zone, "level": s.level, "kind": s.kind, "category": s.category,
                      "boundary": s.boundary, "adj": s.adjacent_zone, "v": [list(map(lambda x: round(x, 4), p)) for p in s.vertices],
                      "a": round(net, 3), "u": None if s.u_si is None or s.boundary == "adiabatic" else round(s.u_si, 4),
                      "az": None if s.azimuth is None else round(s.azimuth, 1), "asm": s.assembly or s.product,
                      "label": s.label})
        if s.u_si is not None and s.boundary != "adiabatic":
            us.append(s.u_si)
    rooms = {}
    heat_d, cool_d = [], []
    from shapely.geometry import Polygon as _Poly

    zfloor = {}
    for s in geo["surfaces"]:
        if s.kind == "floor" and s.room and s.zone == s.room:
            zfloor[s.room] = min(zfloor.get(s.room, 1e9), s.vertices[0][2])
    for r in b.rooms:
        fa = geo["zones"][r.id]["floor_area"]
        c = _Poly(r.polygon).representative_point()
        rec = {"name": r.name, "area": fa, "level": r.level,
               "c": [round(c.x, 3), round(c.y, 3), round(zfloor.get(r.id, 0.0) + 0.15, 3)]}
        m = (results or {}).get("rooms", {}).get(r.id)
        if m and r.conditioned:
            rec.update(heatW=m["heating_w"], coolW=m["cooling_sensible_w"], heatBtu=m["heating_w"] / W_PER_BTUH,
                       coolBtu=m["cooling_sensible_w"] / W_PER_BTUH, heat=m["heating_w"] / fa, cool=m["cooling_sensible_w"] / fa)
            heat_d.append(rec["heat"])
            cool_d.append(rec["cool"])
        rooms[r.id] = rec
    data = {"surfaces": surfs, "rooms": rooms, "typeColors": TYPE_COLORS,
            "levels": [{"id": lv.id, "name": lv.name} for lv in b.levels],
            "uRange": [min(us, default=0.0), max(us, default=1.0)],
            "loadRange": {"heat": [min(heat_d, default=0.0), max(heat_d, default=1.0)],
                          "cool": [min(cool_d, default=0.0), max(cool_d, default=1.0)]},
            "planNorth": b.plan_north_deg,
            "ip": (b.raw.get("project", {}).get("units_system") or ("SI" if b.is_canada else "IP")).upper() == "IP"}
    cfa = sum(z["floor_area"] for z in geo["zones"].values() if z.get("conditioned"))
    if lang == "fr":
        sub = subtitle or (f"{cfa:.0f} m² ({m2_to_ft2(cfa):.0f} pi²) conditionnés · {len(b.rooms)} pièces · "
                           "mêmes surfaces que le calcul des charges")
    else:
        sub = subtitle or (f"{cfa:.0f} m² ({m2_to_ft2(cfa):.0f} ft²) conditioned · {len(b.rooms)} rooms · "
                           "same surfaces as the load calculation")
    html = TEMPLATE
    for key, txt in UI.get(lang, UI["en"]).items():
        html = html.replace("{" + key + "}", _esc(txt))
    html = (html.replace("__LANG__", lang).replace("__TITLE__", _esc(b.name)).replace("__SUBTITLE__", _esc(sub))
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    return str(out_html)


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
