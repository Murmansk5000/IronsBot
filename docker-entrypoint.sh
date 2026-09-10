#!/bin/sh
set -eu

run_preflight() {
  set +e
  python -m ironsbot.app.docker_preflight
  preflight_status=$?
  set -e
}

run_preflight
while [ "$preflight_status" -eq 75 ]; do
  echo "Docker image update started; waiting for Watchtower handoff before application startup." >&2
  sleep 5
  run_preflight
done

if [ "$preflight_status" -ne 0 ]; then
  exit "$preflight_status"
fi

exec "$@"
