#!/usr/bin/env bash
# Run the test suite inside a container, because the TrueNAS host has no pip.
# Usage: ./scripts/test.sh [pytest args...]
#   ./scripts/test.sh                      # whole suite
#   ./scripts/test.sh tests/test_config.py -v
set -euo pipefail
cd "$(dirname "$0")/.."

docker run --rm \
  -v "$PWD":/app -w /app \
  -v acsm2kindle-pipcache:/root/.cache/pip \
  python:3.11-slim \
  bash -c 'pip install -q -r requirements.txt && python -m pytest "$@"' _ "$@"
