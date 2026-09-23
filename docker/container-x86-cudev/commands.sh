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

# AgenticROS helpers. The source stays in a Git submodule while its ROS
# packages are built as part of the main DUA workspace through src/agenticros.
agenticros_setup() {
  bash /home/neo/workspace/bin/setup_agenticros.sh "$@"
}

agenticros_build_ros() {
  (
    cd /home/neo/workspace || return 1
    colcon build \
      --event-handlers console_direct+ \
      --symlink-install \
      --continue-on-error \
      --packages-up-to \
      agenticros_agent \
      agenticros_arm_moveit_config \
      agenticros_bringup \
      agenticros_discovery \
      agenticros_explore \
      agenticros_follow_me \
      agenticros_msgs \
      agenticros_sim
  )
}

agenticros() {
  /home/neo/workspace/tools/agenticros/agenticros "$@"
}
