#!/usr/bin/env bash
# Closed-loop run on LDC25 from the spawn point (original demo request).
# Usage (in the container, sim world:=ldc25 running): NEBIUS_PERCEPTION=vlm|yolo hydrant_run.sh
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "${here}/../.." && pwd)"
mode="${NEBIUS_PERCEPTION:-vlm}"
mkdir -p "${here}/results/closed_loop"
log="${here}/results/closed_loop/run_hydrant_${mode}.log"
NEBIUS_PERCEPTION="$mode" timeout 700 "${workspace}/scripts/run_nebius_agent.sh" "cerca l'idrante rosso e vacci vicino" > "$log" 2>&1
grep -E "^\[(Goal|Step|Decision|Verify|Perception\] depth)|^[A-Z][a-z]" "$log" | cut -c1-200 | tail -26
pose="$(timeout 8 ros2 topic echo --once /gz/dottorcane/pose 2>/dev/null | grep -A3 position | tr '\n' ' ')"
echo "$pose"
python3 - "$pose" <<'PY'
import math, re, sys
v = dict(re.findall(r"(x|y|z): (-?[0-9.e-]+)", sys.argv[1]))
px, py = float(v["x"]), float(v["y"])
print(f"robot centre -> hydrant centre (3.5, 1.5): {math.hypot(3.5 - px, 1.5 - py):.2f} m")
PY
