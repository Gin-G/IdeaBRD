#!/usr/bin/env bash
set -euo pipefail

# Passthrough entrypoint. Kept as a hook for future startup steps
# (the Helm migrate Job runs `alembic upgrade head` as the container command).
exec "$@"
