#!/usr/bin/env bash
# name x y qz qw
set -u
while read -r name x y qz qw; do
  gz service -s /world/default/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 3000 \
    --req "name: \"dottorcane\", position: {x: $x, y: $y, z: 0.30}, orientation: {x: 0, y: 0, z: $qz, w: $qw}" >/dev/null
  sleep 4
  python3 "$(dirname "$0")/capture.py" "$name" 8 45
done <<'POS'
living 0.6 -3.6 0.7071 0.7071
kitchen 7.0 -1.6 0.0 1.0
dining 4.9 0.9 0.0 1.0
bedroom -6.2 0.3 0.7071 0.7071
second -5.8 -3.0 0.7071 0.7071
gym 3.0 1.2 0.7071 0.7071
POS
echo ALLDONE
