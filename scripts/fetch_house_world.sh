#!/usr/bin/env bash
# Download the AWS RoboMaker Small House models (~105 MB) used by
# `ros2 launch go2_sim go2_sim.launch.py world:=house`.
#
# Source: pantelis/turtlebot-maze, a Gazebo Harmonic port of
# aws-robotics/aws-robomaker-small-house-world, pinned to a known commit.
# Output (ignored by Git):
#   config/gazebo/house/models/aws_robomaker_residential_*
#   config/gazebo/house/photos/*.jpg
set -euo pipefail

repo_url="https://github.com/pantelis/turtlebot-maze.git"
repo_rev="${HOUSE_WORLD_REV:-d306a5c94a359b595c76800e7b8766fa9e2503b0}"

workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest_dir="${1:-${workspace_dir}/config/gazebo/house}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

echo "Fetching ${repo_url} @ ${repo_rev}"
git -C "${tmp_dir}" init -q repo
git -C "${tmp_dir}/repo" remote add origin "${repo_url}"
git -C "${tmp_dir}/repo" sparse-checkout set tb_worlds/models tb_worlds/photos
git -C "${tmp_dir}/repo" fetch -q --depth 1 --filter=blob:none origin "${repo_rev}"
git -C "${tmp_dir}/repo" checkout -q FETCH_HEAD

src="${tmp_dir}/repo/tb_worlds"
mkdir -p "${dest_dir}/models" "${dest_dir}/photos"
rm -rf "${dest_dir}"/models/aws_robomaker_residential_*
cp -r "${src}"/models/aws_robomaker_residential_* "${dest_dir}/models/"
cp "${src}"/photos/*.jpg "${dest_dir}/photos/"

# Portrait meshes look for ../../../../photos (the TurtleBot layout mounts
# the photos next to the share directory). Point them to house/photos.
grep -rlZ --include='*.DAE' '\.\./\.\./\.\./\.\./photos/' "${dest_dir}/models" \
  | xargs -0 -r sed -i 's#\.\./\.\./\.\./\.\./photos/#../../../photos/#g'

# The floor and the carpets collide as thin triangle meshes (3-4 cm and
# 3 mm slabs at z = 0). With DART + bullet the Go2 feet sink into them and the
# robot collapses before CHAMP can stand it up. They are flush with the ground
# plane, so drop their collisions and let the robot walk on the plane.
for model in FloorB_01 Carpet_01; do
  python3 -I - "${dest_dir}/models/aws_robomaker_residential_${model}/model.sdf" <<'EOF'
import re
import sys

path = sys.argv[1]
with open(path) as f:
    sdf = f.read()
sdf = re.sub(r'\s*<collision name="[^"]*">.*?</collision>', '', sdf, flags=re.S)
with open(path, 'w') as f:
    f.write(sdf)
EOF
done

count="$(find "${dest_dir}/models" -mindepth 1 -maxdepth 1 -type d | wc -l)"
echo "Installed ${count} models in ${dest_dir}/models"
