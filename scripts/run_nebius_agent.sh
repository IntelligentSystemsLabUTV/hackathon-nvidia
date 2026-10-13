#!/usr/bin/env bash
set -euo pipefail

workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
agenticros_dir="${workspace_dir}/tools/agenticros"

# Read .env as literal KEY=VALUE pairs (never executed as shell code). Like
# `node --env-file`, variables already set by the caller win over .env, and
# .env wins over the simulation defaults below.
load_env_file() {
  local line key value
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%$'\r'}"
    [[ "${line}" =~ ^[[:space:]]*(#|$) ]] && continue
    [[ "${line}" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[2]}"
    value="${BASH_REMATCH[3]}"
    if [[ "${value}" =~ ^\"(.*)\"[[:space:]]*$ || "${value}" =~ ^\'(.*)\'[[:space:]]*$ ]]; then
      value="${BASH_REMATCH[1]}"
    else
      value="${value%%[[:space:]]#*}"
      value="${value%"${value##*[![:space:]]}"}"
    fi
    if [[ -z "${!key+x}" ]]; then
      export "${key}=${value}"
    fi
  done < "$1"
}

if [[ -f "${workspace_dir}/.env" ]]; then
  load_env_file "${workspace_dir}/.env"
fi

export AGENTICROS_CONFIG_PATH="${AGENTICROS_CONFIG_PATH:-${workspace_dir}/config/agenticros.json}"

# Named places (rooms) of the simulated world, used when Nav2 runs
# (go2_sim.launch.py nav:=map). GO2_WORLD must match the launched world.
places_file="${workspace_dir}/src/go2_sim_worlds/config/places/${GO2_WORLD:-house}.json"
if [[ -z "${AGENTICROS_PLACES_PATH:-}" && -f "${places_file}" ]]; then
  export AGENTICROS_PLACES_PATH="${places_file}"
fi

# Perception: by default the vision model localizes targets without YOLO
# (NEBIUS_PERCEPTION=vlm). NEBIUS_PERCEPTION=yolo adds tiled YOLO for COCO targets,
# e.g. NEBIUS_PERCEPTION=yolo ./scripts/run_nebius_agent.sh "vai vicino al frigorifero".

# Defaults for the Go2 Gazebo simulation (ZED X camera, ~110 deg HFOV).
export NEBIUS_DEPTH_TOPIC="${NEBIUS_DEPTH_TOPIC-/dottorcane/slam/zed_x_driver/depth_distances}"
export NEBIUS_CAMERA_HFOV_DEG="${NEBIUS_CAMERA_HFOV_DEG:-110}"
# Measured in the house simulation (headless, real_time_factor 1.0) with
# AGENTICROS_DEBUG_POSE_TOPIC: with these values -90 deg commands turn 91-93 deg,
# -45 -> 46, +20 -> 18, and 1 m / 0.5 m advances cover 0.97 / 0.51 m. The former
# 0.65 / 0.7 turned ~18% and walked ~20% too far, so the dead-reckoned heading
# drifted ~16 deg per quarter turn. Commands are timed in wall-clock seconds: if
# the simulation runs slower (real_time_factor < 1), scale both by that factor.
export NEBIUS_TURN_EFFICIENCY="${NEBIUS_TURN_EFFICIENCY:-0.77}"
export NEBIUS_FORWARD_EFFICIENCY="${NEBIUS_FORWARD_EFFICIENCY:-0.84}"

# Ground-truth motion diagnostics are opt-in: they add ~6 s to every motion.
# Enable with AGENTICROS_DEBUG_POSE_TOPIC=/gz/dottorcane/pose.
export AGENTICROS_DEBUG_POSE_TOPIC="${AGENTICROS_DEBUG_POSE_TOPIC:-}"

exec node \
  "${agenticros_dir}/packages/agenticros-nebius/dist/index.js" \
  "$@"
