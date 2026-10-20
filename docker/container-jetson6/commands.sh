#!/usr/bin/env bash

# Project-specific shell functions and commands.
#
# Roberto Masocco <r.masocco@dotxautomation.com>
#
# March 9, 2026

# Copyright 2026 dotX Automation s.r.l.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Add yours, some convenient ones are provided below.
# You can also source other files from sub-units included by this project.

# shellcheck disable=SC1090

# AgenticROS helpers. On the Jetson only the packages the real robot needs are
# built: agenticros_msgs and go2_real (the simulation and Nav2 are not available).
agenticros_setup() {
  if [[ $# -eq 0 ]]; then
    set -- --packages-up-to agenticros_msgs go2_real
  fi
  bash /home/neo/workspace/bin/setup_agenticros.sh "$@"
}

agenticros() {
  /home/neo/workspace/tools/agenticros/agenticros "$@"
}

# The DottorCane stack talks over rmw_zenoh_cpp (router on port 7447), while
# ros2init selects rmw_fastrtps_cpp: run this before ros2 CLI commands.
dottorcane_zenoh() {
  export RMW_IMPLEMENTATION=rmw_zenoh_cpp
}

# go2_control accepts cmd_vel only after the arm action (as `arm` in the
# DottorCane container). Disarm stops accepting it.
dottorcane_arm() {
  dottorcane_zenoh
  ros2 action send_goal -f /dottorcane/go2_control/arm dua_hardware_interfaces/action/Arm "{}"
}

dottorcane_disarm() {
  dottorcane_zenoh
  ros2 action send_goal -f /dottorcane/go2_control/disarm dua_hardware_interfaces/action/Disarm "{}"
}
