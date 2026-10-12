"""Ground truth v2: rasterize each object's visual mesh into the depth image and
compare with the scene depth pixel by pixel, so occluded parts (or objects
behind walls) are not counted as visible.

Per frame and object: visible mask -> visible box (normalized), visible pixel
fraction, near-surface distance (12th percentile of scene depth on the visible
pixels, like the agent), bearing of the visible-box centre. Output: gt.json.
"""
import glob
import json
import math
import os
import re
import xml.etree.ElementTree as ET

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.join(HERE, "..", "..", "src", "go2_sim_worlds", "worlds", "house.world")
MODELS = os.path.join(HERE, "..", "..", "config", "gazebo", "house", "models")

DW, DH = 672, 376
DF = 235.2853004079968
DCX, DCY = 336.0, 188.0
CAM_OFFSET = np.array([0.116 + 0.00795, 0.06, 0.165])
HFOV = 110.0

CATEGORY = {
    "Refrigerator_01": "refrigerator",
    "Bed_01": "bed",
    "SofaC_01": "sofa",
    "TV_01": "television",
    "TV_02": "television",
    "KitchenTable_01": "dining table",
    "ChairA_01": "chair",
    "ChairD_01": "chair",
    "BalconyTable_01": "small round table",
    "CoffeeTable_01": "coffee table",
    "Wardrobe_01": "wardrobe",
    "FitnessEquipment_01": "fitness machine",
    "Dumbbell_01": "barbell",
    "Ball_01": "exercise ball",
    "Trash_01": "trash can",
    "NightStand_01": "nightstand",
    "ReadingDesk_01": "desk",
    "CookingBench_01": "stove",
    "KitchenCabinet_01": "kitchen cabinet",
    "ShoeRack_01": "shoe rack",
    "Door_01": "front door",
    "TVCabinet_01": "TV cabinet",
}


def rpy_matrix(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ])


def quat_matrix(x, y, z, w):
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def node_matrix(node):
    m = np.eye(4)
    for child in list(node):
        tag = child.tag.split("}")[1]
        if tag == "matrix":
            m = m @ np.array([float(v) for v in child.text.split()]).reshape(4, 4)
        elif tag == "translate":
            t = np.eye(4)
            t[:3, 3] = [float(v) for v in child.text.split()]
            m = m @ t
        elif tag == "scale":
            s = np.eye(4)
            s[0, 0], s[1, 1], s[2, 2] = [float(v) for v in child.text.split()]
            m = m @ s
        elif tag == "rotate":
            ax, ay, az, ang = [float(v) for v in child.text.split()]
            a = math.radians(ang)
            axis = np.array([ax, ay, az])
            axis = axis / (np.linalg.norm(axis) or 1)
            K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
            R = np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * K @ K
            r4 = np.eye(4)
            r4[:3, :3] = R
            m = m @ r4
    return m


def dae_triangles(path):
    """All triangles (N,3,3) in meters, model frame, node transforms applied."""
    root = ET.parse(path).getroot()
    ns = {"c": root.tag.split("}")[0].strip("{")}
    unit = root.find("c:asset/c:unit", ns)
    scale = float(unit.get("meter")) if unit is not None and unit.get("meter") else 1.0
    geoms = {}
    for g in root.findall(".//c:library_geometries/c:geometry", ns):
        mesh = g.find("c:mesh", ns)
        sources = {}
        for src in mesh.findall("c:source", ns):
            arr = src.find("c:float_array", ns)
            if arr is None or not arr.text:
                continue
            sources["#" + src.get("id")] = np.array(arr.text.split(), dtype=np.float64)
        verts_el = mesh.find("c:vertices", ns)
        pos_src = None
        for inp in verts_el.findall("c:input", ns):
            if inp.get("semantic") == "POSITION":
                pos_src = inp.get("source")
        pos = sources[pos_src].reshape(-1, 3)
        tris = []
        for prim in list(mesh):
            tag = prim.tag.split("}")[1]
            if tag not in ("triangles", "polylist"):
                continue
            inputs = prim.findall("c:input", ns)
            stride = max(int(i.get("offset")) for i in inputs) + 1
            voff = [int(i.get("offset")) for i in inputs if i.get("semantic") == "VERTEX"][0]
            p_el = prim.find("c:p", ns)
            if p_el is None or not p_el.text:
                continue
            idx = np.array(p_el.text.split(), dtype=np.int64).reshape(-1, stride)[:, voff]
            if tag == "triangles":
                tris.append(idx.reshape(-1, 3))
            else:
                vcount = np.array(prim.find("c:vcount", ns).text.split(), dtype=np.int64)
                k = 0
                out = []
                for n in vcount:
                    poly = idx[k:k + n]
                    for j in range(1, n - 1):
                        out.append([poly[0], poly[j], poly[j + 1]])
                    k += n
                if out:
                    tris.append(np.array(out))
        if tris:
            geoms["#" + g.get("id")] = pos[np.vstack(tris)]  # (T,3,3)
    out = []

    def walk(node, mat):
        m = mat @ node_matrix(node)
        for child in list(node):
            tag = child.tag.split("}")[1]
            if tag == "instance_geometry" and child.get("url") in geoms:
                t = geoms[child.get("url")]
                flat = np.c_[t.reshape(-1, 3), np.ones(t.shape[0] * 3)] @ m.T
                out.append(flat[:, :3].reshape(-1, 3, 3))
            elif tag == "node":
                walk(child, m)

    for vs in root.findall(".//c:library_visual_scenes/c:visual_scene", ns):
        for node in vs.findall("c:node", ns):
            walk(node, np.eye(4))
    return np.vstack(out) * scale


def load_objects():
    s = open(WORLD).read()
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    objs = []
    for inc in re.findall(r"<include>(.*?)</include>", s, flags=re.S):
        name = re.search(r"<name>(.*?)</name>", inc)
        uri = re.search(r"<uri>model://(.*?)</uri>", inc)
        pose = re.search(r"<pose>(.*?)</pose>", inc)
        if not (name and uri and pose):
            continue
        model = uri.group(1).strip()
        key = model.replace("aws_robomaker_residential_", "")
        if key not in CATEGORY:
            continue
        sdf = open(os.path.join(MODELS, model, "model.sdf")).read()
        vis_uri = re.search(r"<visual.*?<uri>(?:model://)?(.*?)</uri>", sdf, flags=re.S)
        cand = os.path.join(MODELS, vis_uri.group(1).strip()) if vis_uri else ""
        if not os.path.isfile(cand):
            cand = os.path.join(MODELS, model, vis_uri.group(1).strip()) if vis_uri else ""
        if not os.path.isfile(cand):
            dae = sorted(glob.glob(os.path.join(MODELS, model, "meshes", "*.DAE")))
            vis = [f for f in dae if "visual" in f.lower()]
            cand = (vis or dae)[0]
        path = cand
        p = [float(v) for v in pose.group(1).split()]
        tris = dae_triangles(path)
        R = rpy_matrix(p[3], p[4], p[5])
        tw = tris.reshape(-1, 3) @ R.T + np.array(p[:3])
        objs.append({"name": name.group(1).strip(), "category": CATEGORY[key], "tris": tw.reshape(-1, 3, 3)})
    return objs


def bearing_from_x(xn):
    half = math.tan(math.radians(HFOV / 2))
    return -math.degrees(math.atan((xn - 0.5) * 2 * half))


# pixel-centre ray directions in camera coords (x fwd, y left, z up)
uu, vv = np.meshgrid(np.arange(DW) + 0.5, np.arange(DH) + 0.5)
RAY_Y = -(uu - DCX) / DF
RAY_Z = -(vv - DCY) / DF


def raster_depth(tris_cam):
    """Object depth buffer (planar x) for camera-frame triangles; inf where empty."""
    keep = (tris_cam[:, :, 0] > 0.12).all(axis=1)
    t = tris_cam[keep]
    if len(t) == 0:
        return None
    u = DCX - DF * t[:, :, 1] / t[:, :, 0]
    v = DCY - DF * t[:, :, 2] / t[:, :, 0]
    inside = ~(((u < 0).all(1)) | ((u > DW).all(1)) | ((v < 0).all(1)) | ((v > DH).all(1)))
    t, u, v = t[inside], u[inside], v[inside]
    if len(t) == 0:
        return None
    order = np.argsort(-t[:, :, 0].max(axis=1))  # far first, near last
    ids = np.full((DH, DW), -1, dtype=np.int32)
    for i in order:
        pts = np.round(np.stack([u[i], v[i]], axis=1) * 16).astype(np.int32)
        cv2.fillConvexPoly(ids, pts, int(i), lineType=cv2.LINE_8, shift=4)
    mask = ids >= 0
    if not mask.any():
        return None
    p0 = t[:, 0, :]
    n = np.cross(t[:, 1, :] - p0, t[:, 2, :] - p0)
    c = (n * p0).sum(1)
    sel = ids[mask]
    nd = n[sel, 0] + n[sel, 1] * RAY_Y[mask] + n[sel, 2] * RAY_Z[mask]
    with np.errstate(divide="ignore", invalid="ignore"):
        d = c[sel] / nd
    # degenerate / grazing triangles: fall back to the triangle's mean depth
    bad = ~np.isfinite(d) | (d <= 0)
    d[bad] = t[sel[bad], :, 0].mean(1)
    out = np.full((DH, DW), np.inf)
    out[mask] = d
    return out


def main():
    objs = load_objects()
    print("objects:", len(objs), "triangles:", sum(len(o["tris"]) for o in objs))
    gt = {}
    for meta_path in sorted(glob.glob(os.path.join(HERE, "data", "frames", "*.json"))):
        meta = json.load(open(meta_path))
        name = meta["name"]
        if name.startswith("ldc"):
            continue  # LDC25 frames: the house furniture is not in that world
        scene = np.load(os.path.join(HERE, "data", "frames", f"{name}.depth.npy")).astype(np.float64)
        scene_far = ~np.isfinite(scene) | (scene <= 0)
        P = meta["pose"]
        Rb = quat_matrix(P["qx"], P["qy"], P["qz"], P["qw"])
        cam = np.array([P["x"], P["y"], P["z"]]) + Rb @ CAM_OFFSET
        items = []
        for o in objs:
            tc = ((o["tris"].reshape(-1, 3) - cam) @ Rb).reshape(-1, 3, 3)
            od = raster_depth(tc)
            if od is None:
                continue
            obj_px = np.isfinite(od)
            tol = 0.05 + 0.01 * od
            vis = obj_px & ((~scene_far & (np.abs(scene - od) < tol)) | (scene_far & (od > 9.5)))
            occl = obj_px & ~scene_far & (scene < od - tol)
            n_obj, n_vis = int(obj_px.sum()), int(vis.sum())
            if n_vis < 4:
                items.append({"name": o["name"], "category": o["category"], "visible_px": n_vis, "object_px": n_obj, "visible_box": None})
                continue
            ys, xs = np.nonzero(vis)
            box = [xs.min() / DW, ys.min() / DH, (xs.max() + 1) / DW, (ys.max() + 1) / DH]
            oys, oxs = np.nonzero(obj_px)
            full = [oxs.min() / DW, oys.min() / DH, (oxs.max() + 1) / DW, (oys.max() + 1) / DH]
            sd = np.sort(scene[vis & ~scene_far])
            dist = float(sd[int(0.12 * len(sd))]) if len(sd) else None
            items.append({
                "name": o["name"],
                "category": o["category"],
                "visible_px": n_vis,
                "object_px": n_obj,
                "occluded_px": int(occl.sum()),
                "visible_frac": round(n_vis / max(1, n_obj), 3),
                "visible_box": [round(b, 4) for b in box],
                "full_box": [round(b, 4) for b in full],
                "centroid_x": round(float(xs.mean() + 0.5) / DW, 4),
                "distance_m": round(dist, 2) if dist is not None else None,
                "bearing_deg": round(bearing_from_x((box[0] + box[2]) / 2), 1),
                "bearing_centroid_deg": round(bearing_from_x(float(xs.mean() + 0.5) / DW), 1),
            })
            # save the visible mask for later checks (point-in-object tests)
            np.save(os.path.join(HERE, "data", "masks", f"{name}__{o['name']}.npy"), np.packbits(vis))
        gt[name] = {"pose": P, "objects": items}
        print(name, sum(1 for i in items if i.get("visible_box")), flush=True)
    json.dump(gt, open(os.path.join(HERE, "data", "gt.json"), "w"), indent=1)


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "data", "masks"), exist_ok=True)
    main()
