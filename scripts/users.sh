#!/usr/bin/env bash
# Manage users in the running stack (on the server or locally). The password is random and printed once.
#   ./scripts/users.sh add <username>
#   ./scripts/users.sh reset <username>   # also logs them out of every browser
#   ./scripts/users.sh list
set -euo pipefail
cd "$(dirname "$0")/.."
# exec only needs the service names, which the base file has.
docker compose -f docker-compose.yml exec -T app python -m app.manage_users "$@"
