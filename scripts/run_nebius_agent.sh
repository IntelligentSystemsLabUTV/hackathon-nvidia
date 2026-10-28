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

# GO2_TARGET selects the robot:
#   sim      the Gazebo simulation (default, go2_sim.launch.py): same topics, frames,
#            middleware and Nav2 as the real robot, only the locomotion calibration differs;
#   real     the real Go2 (DottorCane stack on the Jetson, rmw_zenoh_cpp).
target="${GO2_TARGET:-sim}"
if [[ "${target}" != "real" && "${target}" != "sim" ]]; then
  echo >&2 "Unknown GO2_TARGET '${target}': use sim or real"
  exit 2
fi

# Overrides ros2init's rmw_fastrtps_cpp: the DottorCane nodes only talk over zenoh.
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
# GO2_AGENTICROS_CONFIG overrides the config (e.g. config/agenticros.local.json).
export AGENTICROS_CONFIG_PATH="${GO2_AGENTICROS_CONFIG:-${workspace_dir}/config/agenticros.json}"
# Depth from the Livox Mid-360 projected into the front camera (go2_real.launch.py).
export NEBIUS_DEPTH_TOPIC="${NEBIUS_DEPTH_TOPIC-/dottorcane/agent/depth}"
# Default camera: the Go2 front camera of config/agenticros.json, rectified,
# HFOV from the projection matrix of dottorcane_bringup/config/go2_camera.yaml
# (the simulated one has the same HFOV). Another camera (the USB camera): set
# NEBIUS_CAMERA_TOPIC and NEBIUS_CAMERA_HFOV_DEG to the HFOV that lidar_camera_depth
# prints at startup for the same camera.
export NEBIUS_CAMERA_HFOV_DEG="${NEBIUS_CAMERA_HFOV_DEG:-94.7}"
export NEBIUS_IMU_TOPIC="${NEBIUS_IMU_TOPIC-/dottorcane/go2_control/imu}"
# Estimated pose of the robot in the map frame (EKF + LIO-SAM; in simulation the
# stand-in of go2_sim.launch.py). Never the Gazebo ground truth.
export AGENTICROS_POSE_TOPIC="${AGENTICROS_POSE_TOPIC-/dottorcane/slam/ekf_global/odometry}"
export AGENTICROS_DEBUG_POSE_TOPIC="${AGENTICROS_DEBUG_POSE_TOPIC:-}"
# Named places of this localization session ("ricorda questo posto come cucina", and every
# target reached), in the map frame of EKF + LIO-SAM. That frame restarts with the
# DottorCane stack: delete the file then (the simulation clears it at start).
export NEBIUS_SESSION_PLACES="${NEBIUS_SESSION_PLACES:-on}"
# Every motion as a Nav2 behavior (spin, drive_on_heading, backup): closed
# loop on the LIO-SAM pose and checked against the costmap, never a cmd_vel from the agent.
# Without Nav2 the agent refuses to move; NEBIUS_NAV2_MOTION=off: timed ros2_move_for motions.
export NEBIUS_NAV2_MOTION="${NEBIUS_NAV2_MOTION:-on}"
export AGENTICROS_PLACES_PATH="${AGENTICROS_PLACES_PATH:-${workspace_dir}/logs/places_session.json}"
if [[ "${target}" == "real" ]]; then
  # Estimate for the standing Go2 (head camera ~4 cm above the base): measure it.
  export NEBIUS_CAMERA_HEIGHT_M="${NEBIUS_CAMERA_HEIGHT_M:-0.36}"
  # Not calibrated yet: the Unitree sport mode tracks velocity, unlike CHAMP in the
  # simulation. Measure with "ruota a destra di 90 gradi e avanza di un metro".
  export NEBIUS_TURN_EFFICIENCY="${NEBIUS_TURN_EFFICIENCY:-1.0}"
  export NEBIUS_FORWARD_EFFICIENCY="${NEBIUS_FORWARD_EFFICIENCY:-1.0}"
  # Search turn of exactly 4 quarter turns, back to the start heading (the default 360 + 90
  # took 5). Below 360 because the searched angle is the IMU-measured one: 4 x 84 deg seen on
  # the robot; 3 quarter turns never reach 330.
  export NEBIUS_FULL_TURN_DEG="${NEBIUS_FULL_TURN_DEG:-330}"
else
  # CHAMP stands lower than the sport mode (base ~0.22 m, camera 4 cm above it).
  export NEBIUS_CAMERA_HEIGHT_M="${NEBIUS_CAMERA_HEIGHT_M:-0.26}"
  # CHAMP calibration of the house simulation, measured headless (real_time_factor 1.0):
  # -90 deg commanded turns 91-93 deg, 1 m covers 0.97 m. Commands are timed in
  # wall-clock seconds: with real_time_factor < 1 scale both by that factor.
  export NEBIUS_TURN_EFFICIENCY="${NEBIUS_TURN_EFFICIENCY:-0.77}"
  export NEBIUS_FORWARD_EFFICIENCY="${NEBIUS_FORWARD_EFFICIENCY:-0.84}"
fi
exec node \
  "${agenticros_dir}/packages/agenticros-nebius/dist/index.js" \
  "$@"
