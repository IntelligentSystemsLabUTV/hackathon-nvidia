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
#   real     the real Go2 (DottorCane stack on the Jetson, rmw_zenoh_cpp);
#   sim      the simulation that looks like the real robot (default:
#            go2_sim.launch.py profile:=real): same topics, frames, middleware
#            and DUA Nav2, only the locomotion calibration differs;
#   sim-zed  the previous simulation (profile:=zed, ZED camera and depth,
#            nav:=map|slam with named places).
target="${GO2_TARGET:-sim}"
case "${target}" in
  real | sim)
    # Overrides ros2init's rmw_fastrtps_cpp: the DottorCane nodes only talk over zenoh.
    export RMW_IMPLEMENTATION=rmw_zenoh_cpp
    # The real config also in the cudev container, whose AGENTICROS_CONFIG_PATH points to the
    # sim-zed one; GO2_AGENTICROS_CONFIG overrides it (e.g. config/agenticros.local.json).
    export AGENTICROS_CONFIG_PATH="${GO2_AGENTICROS_CONFIG:-${workspace_dir}/config/agenticros.real.json}"
    # Depth from the Livox Mid-360 projected into the front camera (go2_real.launch.py).
    export NEBIUS_DEPTH_TOPIC="${NEBIUS_DEPTH_TOPIC-/dottorcane/agent/depth}"
    # Default camera: the Go2 front camera of config/agenticros.real.json, rectified,
    # HFOV from the projection matrix of dottorcane_bringup/config/go2_camera.yaml
    # (the simulated one has the same HFOV). Another camera (the USB camera): set
    # NEBIUS_CAMERA_TOPIC and NEBIUS_CAMERA_HFOV_DEG to the HFOV that lidar_camera_depth
    # prints at startup for the same camera.
    export NEBIUS_CAMERA_HFOV_DEG="${NEBIUS_CAMERA_HFOV_DEG:-94.7}"
    # Branch mapless: no pose estimate of any kind. No IMU heading (the gyroscope integrates
    # into odometry), no EKF / SLAM pose, no Nav2, no places in a map frame: the robot
    # navigates on what it sees (vision model on Nebius + instantaneous lidar).
    export NEBIUS_IMU_TOPIC="${NEBIUS_IMU_TOPIC-}"
    export AGENTICROS_POSE_TOPIC="${AGENTICROS_POSE_TOPIC-}"
    export NEBIUS_SESSION_PLACES="${NEBIUS_SESSION_PLACES:-off}"
    export NEBIUS_NAV2="${NEBIUS_NAV2:-off}"
    # Instantaneous obstacle scan of go2_real.launch.py, for the reactive drive (ros2_drive_toward).
    export NEBIUS_SCAN_TOPIC="${NEBIUS_SCAN_TOPIC-/dottorcane/agent/scan_obstacles}"
    export AGENTICROS_DEBUG_POSE_TOPIC="${AGENTICROS_DEBUG_POSE_TOPIC:-}"
    if [[ "${target}" == "real" ]]; then
      # Estimate for the standing Go2 (head camera ~4 cm above the base): measure it.
      export NEBIUS_CAMERA_HEIGHT_M="${NEBIUS_CAMERA_HEIGHT_M:-0.36}"
      # Not calibrated yet: the Unitree sport mode tracks velocity, unlike CHAMP in the
      # simulation. Measure with "ruota a destra di 90 gradi e avanza di un metro".
      export NEBIUS_TURN_EFFICIENCY="${NEBIUS_TURN_EFFICIENCY:-1.0}"
      export NEBIUS_FORWARD_EFFICIENCY="${NEBIUS_FORWARD_EFFICIENCY:-1.0}"
    else
      # CHAMP stands lower than the sport mode (base ~0.22 m, camera 4 cm above it).
      export NEBIUS_CAMERA_HEIGHT_M="${NEBIUS_CAMERA_HEIGHT_M:-0.26}"
      # CHAMP calibration of the house simulation (see the sim-zed branch below).
      export NEBIUS_TURN_EFFICIENCY="${NEBIUS_TURN_EFFICIENCY:-0.77}"
      export NEBIUS_FORWARD_EFFICIENCY="${NEBIUS_FORWARD_EFFICIENCY:-0.84}"
    fi
    exec node \
      "${agenticros_dir}/packages/agenticros-nebius/dist/index.js" \
      "$@"
    ;;
  sim-zed) ;;
  *)
    echo >&2 "Unknown GO2_TARGET '${target}': use real, sim or sim-zed"
    exit 2
    ;;
esac

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

# Defaults for the previous Go2 Gazebo simulation (ZED X camera, ~110 deg HFOV).
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
# Heading from the gyroscope of the ZED IMU (ros2_imu_yaw): rotations commanded next to low
# furniture turn far less than commanded. NEBIUS_IMU_TOPIC= (empty) keeps the commanded turns.
# In simulation the IMU has no noise model, so the integrated heading is close to ideal.
export NEBIUS_IMU_TOPIC="${NEBIUS_IMU_TOPIC-/dottorcane/slam/zed_x_driver/imu}"

# Ground-truth motion diagnostics are opt-in: they add ~6 s to every motion.
# Enable with AGENTICROS_DEBUG_POSE_TOPIC=/gz/dottorcane/pose.
export AGENTICROS_DEBUG_POSE_TOPIC="${AGENTICROS_DEBUG_POSE_TOPIC:-}"

exec node \
  "${agenticros_dir}/packages/agenticros-nebius/dist/index.js" \
  "$@"
