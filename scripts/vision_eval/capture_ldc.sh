#!/usr/bin/env bash
set -u
python3 "$(dirname "$0")/capture.py" ldcspawn 8 45
while read -r name x y qz qw n step; do
  gz service -s /world/default/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 3000 \
    --req "name: \"dottorcane\", position: {x: $x, y: $y, z: 0.30}, orientation: {x: 0, y: 0, z: $qz, w: $qw}" >/dev/null
  sleep 4
  python3 "$(dirname "$0")/capture.py" "$name" "$n" "$step"
done <<'POS'
ldcmid 2.9 4.6 -0.7071 0.7071 3 20
ldcnear 3.3 3.2 -0.7071 0.7071 3 20
ldcfar 2.4 10.5 -0.6 0.8 3 20
POS
echo ALLDONE
