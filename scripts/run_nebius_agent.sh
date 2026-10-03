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

# Defaults for the Go2 Gazebo simulation (ZED X camera, ~110 deg HFOV).
export NEBIUS_DEPTH_TOPIC="${NEBIUS_DEPTH_TOPIC-/dottorcane/slam/zed_x_driver/depth_distances}"
export NEBIUS_CAMERA_HFOV_DEG="${NEBIUS_CAMERA_HFOV_DEG:-110}"
# Measured in simulation (CHAMP gait with acceleration ramp, bullet contacts):
# ~60% of the commanded yaw and ~65% of the commanded distance while the
# command lasts, plus a short coast while the ramp brings the base to rest.
export NEBIUS_TURN_EFFICIENCY="${NEBIUS_TURN_EFFICIENCY:-0.65}"
export NEBIUS_FORWARD_EFFICIENCY="${NEBIUS_FORWARD_EFFICIENCY:-0.7}"

# Ground-truth motion diagnostics are opt-in: they add ~6 s to every motion.
# Enable with AGENTICROS_DEBUG_POSE_TOPIC=/gz/dottorcane/pose.
export AGENTICROS_DEBUG_POSE_TOPIC="${AGENTICROS_DEBUG_POSE_TOPIC:-}"

exec node \
  "${agenticros_dir}/packages/agenticros-nebius/dist/index.js" \
  "$@"
