"""Ironclad CanSat v2: lightweight rib-cage frame, classic can size (66 x 115 mm).
Units: mm. Run with python3 -I cansat_v2.py <outdir>
"""
import sys, os, math, itertools, json
import cadquery as cq

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT, exist_ok=True)

OD, H = 66.0, 115.0
R = OD / 2
RING_W = 3.0            # radial width of each rib ring (ID 60)
RING_T = 2.0
DECK_T = 1.6
INNER_R = R - RING_W    # 30
FIT_R = INNER_R - 0.5   # parts must stay inside this radius

# ---------------- printed structure ----------------
def ring(z, t=RING_T, ro=R, ri=INNER_R):
    return cq.Workplane("XY").workplane(offset=z).circle(ro).circle(ri).extrude(t)

def deck(z, holes):
    d = cq.Workplane("XY").workplane(offset=z).circle(INNER_R + 0.01).extrude(DECK_T)
    for (hx, hy, hr) in holes:
        d = d.cut(cq.Workplane("XY").workplane(offset=z - 1).center(hx, hy).circle(hr).extrude(DECK_T + 2))
    return d

RINGS = [8.0, 36.0, 60.0, 72.0, 86.0, 110.0]
DECKS = {"A": 8.0, "B": 60.0, "C": 72.0, "D": 86.0}
N_STRUTS = 8
STRUT = float(os.environ.get("STRUT", "3.0"))
cage = None
for z in RINGS:
    r = ring(z)
    cage = r if cage is None else cage.union(r)
for i in range(N_STRUTS):
    a = 2 * math.pi * i / N_STRUTS + math.pi / N_STRUTS
    rc = R - STRUT / 2
    x, y = rc * math.cos(a), rc * math.sin(a)
    s = (cq.Workplane("XY").workplane(offset=8.0).center(x, y)
         .rect(STRUT, STRUT).extrude(112.0 - 8.0)
         .rotate((x, y, 0), (x, y, 1), math.degrees(a)))
    cage = cage.union(s)

# decks with lightening holes placed in free areas
deck_holes = {
    "A": [(-20, -18, 4), (20, -18, 4)],
    "B": [(13, -2, 0.1)],
    "C": [(-22, 10, 4), (22, 10, 4)],
    "D": [(-15, 15, 5), (15, 15, 5), (-15, -15, 5), (15, -15, 5)],
}
decks = None
for k, z in DECKS.items():
    d = deck(z, deck_holes[k])
    decks = d if decks is None else decks.union(d)
frame = cage.union(decks)
# wire pass-through for antenna and cables
frame = frame.cut(cq.Workplane("XY").workplane(offset=-1).center(-20, 12).circle(1.6).extrude(H + 2))

# hinge knuckles on top ring (x = +30) and latch post (x = -28)
hinge_base = cq.Workplane("XY").workplane(offset=110).center(30.5, 0).rect(5, 14).extrude(4)
frame = frame.union(hinge_base)
latch_post = cq.Workplane("XY").workplane(offset=103).center(-29.0, 0).rect(3.0, 6).extrude(8)  # overlaps top ring so it is fused
frame = frame.union(latch_post)

# TPU crush ring under the frame (flexible, absorbs landing)
tpu = (cq.Workplane("XY").circle(R).circle(25.0).extrude(8.0)
       .faces(">Z").edges().fillet(0.8))
# cut a slot so the antenna can pass
# (antenna sits at r = 23.3, inside the ring's inner radius of 25 mm)

# lid with hinge and thread hook
lid = cq.Workplane("XY").workplane(offset=112.0).circle(R - 0.5).extrude(3.0)
lid = lid.union(cq.Workplane("XY").workplane(offset=114.0).center(30.5, 0).rect(5, 10).extrude(2))
lid = lid.cut(cq.Workplane("XY").workplane(offset=111.0).center(30.5, 0).rect(5.4, 14.4).extrude(3.2))
lid = lid.union(cq.Workplane("XY").workplane(offset=106.0).center(-25.0, 0).rect(3, 3).extrude(6))  # thread hook
lid = lid.cut(cq.Workplane("XY").workplane(offset=111.0).center(0, 0).circle(2.0).extrude(5))      # parachute line hole

# ---------------- bought parts (blocks at datasheet sizes) ----------------
# name: (x, y, z_bottom, w, d, h)   or cylinder: (x, y, z, r, h, "cyl")
PARTS = {
    "Air quality sensor PMS5003 (standing)": (0, -11, 10 - 0.4 + 0.4, 38, 21, 50),
    "LiPo 1S 360 mAh 30C (standing)": (0, 2.0, 9.6, 50, 3, 25),
    "Buzzer": (20, 10.5, 9.6, 6, 9.5, "cyl"),
    "5 V boost MT3608 (under deck B)": (0, 13, 45.9, 36, 17, 14),
    "Radio Ebyte E32-900T20D": (-9, 0, 61.6, 21, 43, 10),
    "ESP32-C3 SuperMini": (13, 0, 61.6, 22.5, 18, 8),
    "Burn-wire MOSFET (IRLZ44N on perfboard)": (13, 17, 61.6, 12, 8, 9),
    "BME280 (pressure, temperature, humidity)": (8, -18, 61.6, 12, 15, 3),
    "GPS NEO-6M with patch antenna": (0, -6, 73.6, 36, 26, 12),
    "microSD module (TF mini)": (0, 17, 73.6, 20, 18, 12),
    "Lid spring": (0, 0, 87.6, 4, 10, "cyl"),
    "Packed parachute": (0, 0, 88.0, 0, 0, "chute"),
    "Antenna (quarter-wave wire, 86 mm)": (-20, 12, -24, 0.8, 86, "cyl"),
}

def part_solid(name, spec):
    if spec[-1] == "cyl":
        x, y, z, r, h, _ = spec
        return cq.Workplane("XY").workplane(offset=z).center(x, y).circle(r).extrude(h)
    if spec[-1] == "chute":
        return (cq.Workplane("XY").workplane(offset=89.6).circle(23).circle(5).extrude(16))
    x, y, z, w, d, h = spec
    return cq.Workplane("XY").workplane(offset=z).center(x, y).rect(w, d).extrude(h)

parts = {n: part_solid(n, s) for n, s in PARTS.items()}

# ---------------- checks ----------------
problems = []
def bbox(wp):
    return wp.val().BoundingBox()
for n, wp in parts.items():
    if n.startswith("Antenna"):
        continue
    bb = bbox(wp)
    spec = PARTS[n]
    if spec[-1] == "cyl":
        rmax = math.hypot(spec[0], spec[1]) + spec[3]
        if rmax > FIT_R + 0.01:
            problems.append(f"OUTSIDE: {n} reaches r={rmax:.1f} mm (limit {FIT_R})")
        continue
    corners = [(bb.xmin, bb.ymin), (bb.xmin, bb.ymax), (bb.xmax, bb.ymin), (bb.xmax, bb.ymax)]
    rmax = max(math.hypot(cx, cy) for cx, cy in corners)
    if n == "Packed parachute":
        rmax = 23
    if rmax > FIT_R + 0.01:
        problems.append(f"OUTSIDE: {n} reaches r={rmax:.1f} mm (limit {FIT_R})")
    if bb.zmax > H + 0.01:
        problems.append(f"TOO TALL: {n} top at {bb.zmax:.1f}")
names = list(parts)
for a, b in itertools.combinations(names, 2):
    inter = parts[a].intersect(parts[b])
    v = inter.val().Volume() if inter.vals() else 0
    if v > 0.5:
        problems.append(f"CLASH: {a} x {b} ({v:.1f} mm3)")
for n, wp in parts.items():
    for sname, s in (("frame", frame), ("TPU ring", tpu), ("lid", lid)):
        inter = wp.intersect(s)
        v = inter.val().Volume() if inter.vals() else 0
        if v > 0.5:
            problems.append(f"CLASH: {n} x {sname} ({v:.1f} mm3)")

# ---------------- mass of printed parts ----------------
PLA, TPU = 1.24e-3, 1.21e-3   # g per mm3
vol_frame, vol_lid, vol_tpu = frame.val().Volume(), lid.val().Volume(), tpu.val().Volume()
mass = {
    "frame_g_solid": round(vol_frame * PLA, 1),
    "lid_g_solid": round(vol_lid * PLA, 1),
    "tpu_ring_g_solid": round(vol_tpu * TPU, 1),
}
mass["printed_total_g_solid"] = round(sum(mass.values()), 1)

# old v1 shell for comparison (80 x 180, 2 mm wall + 4 decks)
old_shell = (cq.Workplane("XY").circle(40).extrude(180)
             .cut(cq.Workplane("XY").workplane(offset=2).circle(38).extrude(178)))
old_decks = None
for z in (8, 48, 92, 128):
    d = cq.Workplane("XY").workplane(offset=z).circle(37).extrude(2)
    old_decks = d if old_decks is None else old_decks.union(d)
mass["v1_shell_and_decks_g_solid"] = round((old_shell.val().Volume() + old_decks.val().Volume()) * PLA, 1)

# ---------------- exports ----------------
cq.exporters.export(frame, os.path.join(OUT, "01_rib_cage_frame_PLA.stl"), tolerance=0.05)
cq.exporters.export(lid, os.path.join(OUT, "02_hinged_lid_PLA.stl"), tolerance=0.05)
cq.exporters.export(tpu, os.path.join(OUT, "03_crush_ring_TPU.stl"), tolerance=0.05)

asm = cq.Assembly(name="Ironclad_CanSat_v2")
asm.add(frame, name="Rib cage frame (PLA)", color=cq.Color(0.85, 0.85, 0.88, 1))
asm.add(lid, name="Hinged lid (PLA)", color=cq.Color(0.75, 0.75, 0.8, 1))
asm.add(tpu, name="Crush ring (TPU)", color=cq.Color(0.15, 0.6, 0.55, 1))
palette = [(0.35, 0.55, 0.8), (0.25, 0.25, 0.25), (0.1, 0.1, 0.1), (0.0, 0.47, 0.3), (0.12, 0.12, 0.12),
           (0.55, 0.35, 0.15), (0.47, 0.24, 0.63), (0.59, 0.47, 0.24), (0.78, 0.63, 0.0), (0.6, 0.6, 0.6),
           (1.0, 0.43, 0.0), (0.8, 0.2, 0.2), (0.7, 0.7, 0.7)]
for (n, wp), c in zip(parts.items(), palette):
    asm.add(wp, name=n, color=cq.Color(*c, 1))
asm.save(os.path.join(OUT, "Ironclad_CanSat_v2.step"))

report = {"problems": problems, "mass": mass,
          "volumes_mm3": {"frame": round(vol_frame), "lid": round(vol_lid), "tpu": round(vol_tpu)}}
with open(os.path.join(OUT, "report.json"), "w") as f:
    json.dump(report, f, indent=1)

# pickle meshes for rendering
import pickle
def mesh(wp):
    vs, ts = wp.val().tessellate(0.2)
    return [(v.x, v.y, v.z) for v in vs], ts
meshes = {"frame": mesh(frame), "lid": mesh(lid), "tpu": mesh(tpu)}
for n, wp in parts.items():
    meshes[n] = mesh(wp)
with open(os.path.join(OUT, "meshes.pkl"), "wb") as f:
    pickle.dump(meshes, f)
print(json.dumps(report, indent=1))
