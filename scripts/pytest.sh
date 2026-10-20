#!/usr/bin/env bash
# Run backend tests against the CURRENT source without rebuilding the api image.
#
#   scripts/pytest.sh                      # whole suite
#   scripts/pytest.sh tests/test_halts.py  # one module's tests
#
# Mounts backend/ over /app in a dependency image (undertow-api-test), so several agents
# can run tests at the same time. Only `docker compose build api` is an exclusive resource;
# this script never touches it. Rebuild the dependency image only when requirements change:
#   docker build -q -t undertow-api-test backend
# The repo root is also mounted read-only at /repo, so tests that compare backend code with docs/ or
# frontend/ (tests/test_paper_numbers.py) can see them. Both mounts are per-container, so parallel runs are safe.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST_PATH="$ROOT"
if command -v cygpath >/dev/null 2>&1; then
  HOST_PATH="$(cygpath -m "$ROOT")"
  # The Claude desktop app's folders are virtualized by Windows: Docker sees the real
  # location under AppData/Local/Packages/<app>/LocalCache/Roaming instead of AppData/Roaming.
  if [[ "$HOST_PATH" == */AppData/Roaming/Claude/* ]]; then
    for pkg in "${LOCALAPPDATA:-$HOME/AppData/Local}"/Packages/Claude_*/LocalCache/Roaming; do
      candidate="$(cygpath -m "$pkg")/${HOST_PATH#*/AppData/Roaming/}"
      if [[ -d "$candidate/backend" ]]; then HOST_PATH="$candidate"; break; fi
    done
  fi
fi

if ! docker image inspect undertow-api-test >/dev/null 2>&1; then
  docker build -q -t undertow-api-test "$ROOT/backend" >/dev/null
fi

MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$HOST_PATH/backend:/app" \
  -v "$HOST_PATH:/repo:ro" \
  -w /app undertow-api-test pytest -q "$@"
