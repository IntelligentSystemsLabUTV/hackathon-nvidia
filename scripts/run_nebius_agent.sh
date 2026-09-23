#!/usr/bin/env bash
set -euo pipefail

workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
agenticros_dir="${workspace_dir}/tools/agenticros"

export AGENTICROS_CONFIG_PATH="${AGENTICROS_CONFIG_PATH:-${workspace_dir}/config/agenticros.json}"
export AGENTICROS_DEBUG_POSE_TOPIC="${AGENTICROS_DEBUG_POSE_TOPIC-/gz/dottorcane/pose}"

exec node \
  --env-file="${workspace_dir}/.env" \
  "${agenticros_dir}/packages/agenticros-nebius/dist/index.js" \
  "$@"
