#!/bin/sh
set -eu

set +e
python -m ironsbot.app.docker_preflight
preflight_status=$?
set -e

if [ "$preflight_status" -eq 75 ]; then
  echo "Docker image update started; waiting for Watchtower handoff before application startup." >&2
  while :; do
    sleep 30
    echo "Still waiting for Watchtower handoff; the application has not started." >&2
  done
elif [ "$preflight_status" -ne 0 ]; then
  exit "$preflight_status"
fi

exec "$@"
