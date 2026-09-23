#!/usr/bin/env bash

# Prepare AgenticROS inside the hackathon-nvidia DUA container.
# The ROS packages are exposed through src/agenticros and built in the main
# workspace. A compatibility link lets upstream AgenticROS scripts find that
# same install space at ros2_ws/install.

set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTICROS_ROOT="$WORKSPACE_ROOT/tools/agenticros"
ROS_SOURCE_LINK="$WORKSPACE_ROOT/src/agenticros"
EXPECTED_ROS_SOURCE="../tools/agenticros/ros2_ws/src"

if [[ ! -f "$AGENTICROS_ROOT/package.json" ]]; then
  echo >&2 "AgenticROS submodule is missing. Run: git submodule update --init --recursive"
  exit 1
fi

if [[ ! -L "$ROS_SOURCE_LINK" ]] || [[ "$(readlink "$ROS_SOURCE_LINK")" != "$EXPECTED_ROS_SOURCE" ]]; then
  echo >&2 "Expected $ROS_SOURCE_LINK -> $EXPECTED_ROS_SOURCE"
  exit 1
fi

# ROS setup files legitimately inspect unset variables, so disable nounset only
# while sourcing them and restore strict mode immediately afterwards.
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
set -u

cd "$WORKSPACE_ROOT"
# Same command used by the DUA `cbuild` alias. Spell it out because aliases are
# not expanded reliably from a non-interactive postCreateCommand.
colcon build \
  --event-handlers console_direct+ \
  --symlink-install \
  --continue-on-error

AGENTICROS_INSTALL_COMPAT="$AGENTICROS_ROOT/ros2_ws/install"
if [[ -L "$AGENTICROS_INSTALL_COMPAT" ]]; then
  unlink "$AGENTICROS_INSTALL_COMPAT"
fi
mkdir -p "$AGENTICROS_INSTALL_COMPAT"

# Keep the generated compatibility tree inside an ignored directory. Linking
# ros2_ws/install itself would leave the Git submodule permanently dirty,
# because Git does not apply a trailing-slash ignore rule to a symlink.
for install_entry in "$WORKSPACE_ROOT"/install/*; do
  entry_name="$(basename "$install_entry")"
  compat_entry="$AGENTICROS_INSTALL_COMPAT/$entry_name"
  if [[ -e "$compat_entry" && ! -L "$compat_entry" ]]; then
    echo >&2 "$compat_entry exists and is not a symlink; refusing to replace it"
    exit 1
  fi
  ln -sfn "../../../../install/$entry_name" "$compat_entry"
done

CLI_VERSION="$(node -p "require('$AGENTICROS_ROOT/packages/agenticros-cli/package.json').version")"
printf '%s\n' "$CLI_VERSION" > "$AGENTICROS_ROOT/ros2_ws/.agenticros-cli-build-stamp"

# Make custom AgenticROS interfaces visible while native Node dependencies
# (notably rclnodejs) are installed and compiled.
set +u
# shellcheck disable=SC1091
source "$WORKSPACE_ROOT/install/setup.bash"
set -u

cd "$AGENTICROS_ROOT"
pnpm install --frozen-lockfile
pnpm build

echo "AgenticROS is ready. Run: agenticros doctor"
