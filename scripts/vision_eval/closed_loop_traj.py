"""Ground-truth trajectories of the closed-loop A/B runs, and the drift of the no-map graph.

Evaluation only: the ground-truth pose is recorded outside the agent, which never sees it.
Needs, in results/closed_loop/:
  gt_trajectory.txt   "epoch x y yaw_deg" lines of /gz/dottorcane/pose (any recorder at ~1 Hz)
  run_<name>.tslog    the run log with an epoch timestamp in front of every line
  spec.txt            the spec given to closed_loop_matrix.sh (start pose and target per run)

For each run: path walked, closest approach to the target, zones visited, and for every
[Graph] place and [Explore] line the dead-reckoned position / heading against the truth.
--rotations: for every commanded rotation of at least 60 deg, the fraction actually turned,
by distance of the robot centre from the nearest obstacle of the occupancy map.

Usage: python closed_loop_traj.py [spec] [--plot out.png] [--rotations]
"""
import math
import os
import re
import shlex
import sys

import numpy as np

import topo_eval as T
from explore_choice_eval import zone_of

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "results", "closed_loop")


def wrap(a):
    return (a + 180) % 360 - 180


def load_traj():
    rows = [l.split() for l in open(os.path.join(D, "gt_trajectory.txt")) if l.strip()]
    return np.array([[float(v) for v in r] for r in rows])


def at(traj, t):
    i = int(np.argmin(abs(traj[:, 0] - t)))
    return traj[i, 1:], abs(traj[i, 0] - t)


def analyse(name, start, target, traj):
    path = os.path.join(D, f"run_{name}.tslog")
    if not os.path.exists(path):
        return None
    lines = [l.rstrip("\n").split(" ", 1) for l in open(path, errors="replace") if " " in l]
    lines = [(float(t), s) for t, s in lines]
    t0, t1 = lines[0][0], lines[-1][0]
    seg = traj[(traj[:, 0] >= t0 - 1) & (traj[:, 0] <= t1 + 1)]
    sx, sy, syaw = start
    c, s = math.cos(math.radians(syaw)), math.sin(math.radians(syaw))
    world = lambda x, y: (sx + c * x - s * y, sy + s * x + c * y)
    res = {"name": name, "graph": [], "heading": [], "lines": lines}
    if len(seg):
        res["path_m"] = float(np.sum(np.hypot(np.diff(seg[:, 1]), np.diff(seg[:, 2]))))
        d = np.hypot(seg[:, 1] - target[0], seg[:, 2] - target[1])
        res["min_dist_m"] = float(d.min())
        res["final"] = seg[-1, 1:]
        zones = []
        for x, y in seg[:, 1:3]:
            z = zone_of(x, y)
            if z and (not zones or zones[-1] != z):
                zones.append(z)
        res["zones"] = zones
        res["xy"] = seg[:, 1:3]
    for t, text in lines:
        m = re.match(r"\[Graph\] place (\d+) of \d+ at \((-?[\d.]+), (-?[\d.]+)\) m", text)
        if m:
            (tx, ty, tyaw), dt = at(traj, t)
            ex, ey = world(float(m.group(2)), float(m.group(3)))
            res["graph"].append((int(m.group(1)), ex, ey, tx, ty, math.hypot(ex - tx, ey - ty), dt))
        m = re.match(r"\[Explore\] (?:turn|walk|blocked) toward heading -?[\d.]+ deg \(robot (-?[\d.]+) deg", text)
        if m:
            (tx, ty, tyaw), dt = at(traj, t)
            res["heading"].append(wrap(syaw + float(m.group(1)) - tyaw))
    return res


def main():
    args = sys.argv[1:]
    plot = None
    rotations = "--rotations" in args
    args = [a for a in args if a != "--rotations"]
    if "--plot" in args:
        i = args.index("--plot")
        plot = args[i + 1]
        del args[i:i + 2]
    spec = args[0] if args else os.path.join(D, "spec.txt")
    traj = load_traj()
    runs = []
    for line in open(spec):
        if not line.strip() or line.startswith("#"):
            continue
        name, choice, start, tx, ty = shlex.split(line)[:5]
        r = analyse(name, tuple(map(float, start.split())), (float(tx), float(ty)), traj)
        if r:
            r["choice"] = choice
            r["target"] = (float(tx), float(ty))
            runs.append(r)
    print("name\tchoice\tpath_m\tmin_dist_m\tzones\tgraph_err_m(place:err)\theading_err_deg(median|last)")
    for r in runs:
        g = " ".join(f"{p}:{e:.1f}" for p, *_, e, _dt in r["graph"])
        h = r["heading"]
        hs = f"{np.median(np.abs(h)):.0f}|{h[-1]:+.0f}" if h else "-"
        print(f"{r['name']}\t{r['choice']}\t{r.get('path_m', 0):.1f}\t{r.get('min_dist_m', math.nan):.2f}\t"
              f"{'>'.join(z[:3] for z in r.get('zones', []))}\t{g}\t{hs}")
    if plot:
        draw(runs, plot, traj)
    if rotations:
        rotation_table(runs, traj)


def rotations_of(run, traj, clear):
    """(x, y, obstacle distance, turned / commanded) for every commanded rotation of at least 60 deg."""
    h = T.MAP.shape[0]
    acts = [(t, float(m.group(1))) for t, s in run["lines"]
            for m in [re.match(r"\[Decision\].*-> rotate\((-?[\d.]+) deg\)", s)] if m]
    rows = []
    for i, (t, cmd) in enumerate(acts):
        if abs(cmd) < 60:
            continue
        t_end = min(t + 7, acts[i + 1][0] - 0.5) if i + 1 < len(acts) else t + 7
        (x, y, yaw0), dt = at(traj, t)
        (_, _, yaw1), _ = at(traj, t_end)
        if dt > 2:
            continue
        d = clear[h - 1 - int((y - T.ORIGIN[1]) / T.RES), int((x - T.ORIGIN[0]) / T.RES)]
        rows.append((x, y, d, wrap(yaw1 - yaw0) / cmd))
    return rows


def clearance_map():
    from scipy.ndimage import distance_transform_edt
    return distance_transform_edt(T.MAP == 254) * T.RES


def rotation_table(runs, traj):
    clear = clearance_map()
    a = np.array([(d, k) for r in runs for _x, _y, d, k in rotations_of(r, traj, clear)])
    print(f"\nrotations >= 60 deg: {len(a)}; turned / commanded by obstacle distance (map)")
    for lo, hi in [(0, 0.4), (0.4, 0.8), (0.8, 1.2), (1.2, 99)]:
        m = (a[:, 0] >= lo) & (a[:, 0] < hi)
        if m.sum():
            print(f"  [{lo}, {hi}) m: n={m.sum():3d}  median {np.median(a[m, 1]):.2f}  below 0.7: {(a[m, 1] < 0.7).sum()}")


def draw(runs, out, traj):
    """Trajectories over the map (vision blue, open orange), targets green, rotations that
    turned less than 70% of the command red; cropped to the house."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.fromarray(T.MAP).convert("RGB")
    scale = 4
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    dr = ImageDraw.Draw(img)
    h = T.MAP.shape[0]

    def px(x, y):
        return ((x - T.ORIGIN[0]) / T.RES * scale, (h - (y - T.ORIGIN[1]) / T.RES) * scale)

    colors = {"vision": (0, 110, 220), "open": (220, 90, 0)}
    clear = clearance_map()
    for r in runs:
        if "xy" in r:
            dr.line([px(x, y) for x, y in r["xy"]], fill=colors.get(r["choice"], (0, 0, 0)), width=3)
    for r in runs:
        for x, y, _d, k in rotations_of(r, traj, clear):
            if k < 0.7:
                cx, cy = px(x, y)
                dr.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(220, 0, 0))
        tx, ty = r["target"]
        x, y = px(tx, ty)
        dr.ellipse([x - 12, y - 12, x + 12, y + 12], outline=(0, 160, 0), width=4)
    x0, y0 = px(-9.8, 6.0)
    x1, y1 = px(9.8, -6.0)
    img = img.crop((int(x0), int(y0), int(x1), int(y1)))
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, color) in enumerate([("vision", colors["vision"]), ("open", colors["open"]),
                                        ("rotazione < 70%", (220, 0, 0)), ("bersaglio", (0, 160, 0))]):
        dr.rectangle([20, 20 + 36 * i, 44, 44 + 36 * i], fill=color)
        dr.text((54, 18 + 36 * i), label, fill=(0, 0, 0), font=font)
    img.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
