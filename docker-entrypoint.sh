#!/bin/sh
set -eu

set +e
python -m ironsbot.app.docker_preflight
preflight_status=$?
set -e

if [ "$preflight_status" -eq 75 ]; then
  echo "Docker image update started; waiting for Watchtower handoff." >&2
  sleep 30
elif [ "$preflight_status" -ne 0 ]; then
  exit "$preflight_status"
fi

exec "$@"
