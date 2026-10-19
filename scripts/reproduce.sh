#!/usr/bin/env bash
# Offline replay of a study from the cached inputs in the api data volume, then a canonical comparison.
#
#   scripts/reproduce.sh main   # in-sample event study vs the newest docs/results/event_study_*.json
#   scripts/reproduce.sh oos    # pre-registered OOS study (prints its confirmatory verdicts)
#
# Runs inside the api image, so rebuild it first after code changes (docker compose build api), or set
# REPRO_BUILD=1 to have this script do it. The replay writes to {DATA_DIR}/snapshots/replay_*.json and never
# replaces event_study.json (the live evidence). Extra arguments are passed to the study, e.g. --allow-missing.
# Prints IDENTICAL or DIFF with the differing keys; exit code 0 only when identical (main) or the run succeeded (oos).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TARGET="${1:-main}"
shift || true
GIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
export MSYS_NO_PATHCONV=1

if [[ "${REPRO_BUILD:-0}" == "1" ]]; then
  docker compose build api
fi

run() { docker compose run --rm -T -e GIT_SHA="$GIT_SHA" api "$@"; }

case "$TARGET" in
  main)
    published="$(ls -1 docs/results/event_study_*.json 2>/dev/null | sort | tail -n 1 || true)"
    if [[ -z "$published" ]]; then
      echo "No docs/results/event_study_*.json to compare against" >&2
      exit 2
    fi
    replay=/app/data/snapshots/replay_event_study.json
    run python -m app.research.eventstudy --offline --output "$replay" "$@"
    echo "Comparing $published with the offline replay (keys added since that file was published are ignored)"
    # The published file is streamed on stdin ("-"), so no host path has to be mounted.
    run python -m app.research.snapshot compare --ignore-added - "$replay" < "$published"
    ;;
  oos)
    run python -m app.research.oos --offline --output /app/data/snapshots/replay_event_study_oos.json "$@"
    if run test -f /app/data/event_study_oos.json; then
      run python -m app.research.snapshot compare /app/data/event_study_oos.json \
        /app/data/snapshots/replay_event_study_oos.json
    else
      echo "No event_study_oos.json from an online run yet; nothing to compare the replay with"
    fi
    ;;
  *)
    echo "usage: scripts/reproduce.sh main|oos [study args]" >&2
    exit 2
    ;;
esac
