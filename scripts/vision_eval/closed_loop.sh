#!/usr/bin/env bash
# Closed-loop run from the house spawn point, with the ground-truth distance to the target at the end.
# The ground-truth pose is read only here, for evaluation; the agent never sees it.
# Usage (in the container, sim running): [START="x y yaw_deg"] closed_loop.sh <name> <target_x> <target_y> <prompt...>
#   NEBIUS_PERCEPTION=vlm|yolo selects the mode (default here: vlm).
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "${here}/../.." && pwd)"
name="$1"; tx="$2"; ty="$3"; shift 3
prompt="$*"
mkdir -p "${here}/results/closed_loop"
# Start pose: the house spawn by default; START="x y yaw_deg" overrides it (e.g. START="-6.2 0.3 90" in the bedroom).
read -r sx sy syaw <<<"${START:-0.0 1.5 0}"
read -r qz qw < <(python3 -c "import math; a=math.radians(${syaw})/2; print(f'{math.sin(a):.6f} {math.cos(a):.6f}')")
gz service -s /world/default/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 3000 \
  --req "name: \"dottorcane\", position: {x: ${sx}, y: ${sy}, z: 0.30}, orientation: {x: 0, y: 0, z: ${qz}, w: ${qw}}" >/dev/null
sleep 4
log="${here}/results/closed_loop/run_${name}.log"
# The log is also written with a timestamp per line (run_<name>.tslog), to align it with the
# ground-truth trajectory recorded by closed_loop_matrix.sh (closed_loop_traj.py).
NEBIUS_PERCEPTION="${NEBIUS_PERCEPTION:-vlm}" timeout 700 "${workspace}/scripts/run_nebius_agent.sh" "$prompt" 2>&1 \
  | python3 -u "${here}/stamp_log.py" "$log"
echo "===== $name: $prompt"
grep -E "^\[(Step|Decision|Verify|Perception\] depth)|^[A-Z][a-z]" "$log" | cut -c1-200 | tail -24
pose="$("${here}/pose_now.sh" | head -1)"
echo "$pose"
python3 "${here}/dist_to.py" "$pose" "$tx" "$ty"
