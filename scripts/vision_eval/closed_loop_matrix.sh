#!/usr/bin/env bash
# Closed-loop A/B runs of the no-map exploration (sim of the house running, nav:=none).
# Each line of the spec file: <name> <explore_choice: vision|open> <start "x y yaw"> <target_x> <target_y> <prompt...>
# e.g.  bed_v1 vision "0.0 1.5 0" -6.165 2.031 vai in camera da letto
# Results: results/closed_loop/run_<name>.{log,tslog,out}, one line per run in results/closed_loop/summary.tsv,
# and the ground-truth trajectory in results/closed_loop/gt_trajectory.txt (analysis: closed_loop_traj.py).
# Ground truth (final pose, trajectory) is read only here and in closed_loop.sh, for evaluation; the agent never sees it.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
spec="$1"
summary="${here}/results/closed_loop/summary.tsv"
mkdir -p "${here}/results/closed_loop"
python3 "${here}/record_pose.py" "${here}/results/closed_loop/gt_trajectory.txt" &
recorder=$!
trap 'kill "$recorder" 2>/dev/null' EXIT
[[ -f "$summary" ]] || printf "name\tchoice\tsteps\toutcome\twall_s\texplorations\tvision_choices\tplaces\tgt_dist_m\n" > "$summary"
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  eval "set -- $line"
  name="$1"; choice="$2"; start="$3"; tx="$4"; ty="$5"; shift 5
  t0=$(date +%s)
  START="$start" NEBIUS_EXPLORE_CHOICE="$choice" "${here}/closed_loop.sh" "$name" "$tx" "$ty" "$@" > "${here}/results/closed_loop/run_${name}.out" 2>&1
  t1=$(date +%s)
  python3 - "$name" "$choice" "$((t1 - t0))" "${here}/results/closed_loop" >> "$summary" <<'PY'
import re, sys
name, choice, wall, d = sys.argv[1:5]
log = open(f"{d}/run_{name}.log").read()
out = open(f"{d}/run_{name}.out").read()
steps = len(re.findall(r"^\[Step \d+\]", log, re.M))
final = [l for l in log.splitlines() if l and not l.startswith("[") and not l.startswith(" ")]
outcome = "arrived" if any(l.startswith("Obiettivo raggiunto") for l in final) else (final[-1][:40] if final else "?")
expl = re.findall(r"exploration (\d+)/\d+", log)
places = re.findall(r"\[Graph\] place \d+ of (\d+)", log)
gt = re.search(r"target centre: ([0-9.]+) m", out)
print("\t".join([name, choice, str(steps), outcome, wall, str(max(map(int, expl), default=0)), str(len(re.findall(r"\[Explore\] vision model:", log))),
                 str(max(map(int, places), default=0)), gt.group(1) if gt else "?"]))
PY
  tail -1 "$summary"
done < "$spec"
