#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${DIR}/.."

: "${GIT_SIGNING_KEY:?GIT_SIGNING_KEY must be set in the environment}"

podman build \
    --pull=newer \
    --build-arg "GIT_SIGNING_KEY=${GIT_SIGNING_KEY}" \
    --build-arg "NEW_UID=$(id -u)" \
    --build-arg "NEW_GID=$(id -g)" \
    -t dev:latest \
    "$@" \
    -f dev-container/Containerfile .
