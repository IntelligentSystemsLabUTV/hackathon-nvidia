import json, sys, importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sc", os.path.join(HERE, "score.py")); sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
cfg = sys.argv[1]
recs = {}
for l in open(os.path.join(HERE, "results", "vlm", f"{cfg}.jsonl")):
    r = json.loads(l); recs[(r["frame"], r["target"])] = r
rows = []
for r in recs.values():
    r = sc.reparse(r)
    s = sc.score_record(r)
    rows.append((r, s))
mode = sys.argv[2] if len(sys.argv) > 2 else "dist"
for r, s in rows:
    if mode == "dist" and "dist_err_best" in s and not (s["dist_err_best"] <= 0.3 or s["dist_err_best"] / max(0.3, s["gt_dist"]) <= 0.2):
        inst = [o for o in sc.GT[r["frame"]]["objects"] if o["category"] == r["target"] and o.get("visible_box")]
        print(f"{r['frame']:11s} {r['target']:14s} gt={s['gt_dist']:.2f} err={s['dist_err_best']:.2f} box={[round(v,2) for v in r.get('box', [])]} gtbox={[ [round(v,2) for v in o['visible_box']] for o in inst]} conv={r.get('conv')}")
    if mode == "fn" and s["fn"]:
        inst = [o for o in sc.GT[r["frame"]]["objects"] if o["category"] == r["target"] and o.get("visible_box")]
        print(f"FN {r['frame']:11s} {r['target']:14s} px={[o['visible_px'] for o in inst]} dist={[o['distance_m'] for o in inst]} raw={r['raw'][-160:]!r}")
    if mode == "fp" and s["fp"]:
        print(f"FP {r['frame']:11s} {r['target']:14s} box={[round(v,2) for v in r.get('box', [])]} raw={r['raw'][-200:]!r}")
