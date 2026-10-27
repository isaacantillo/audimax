#!/usr/bin/env bash
# Dump the database (users, transcripts, scripts, job history) to backups/, keep the newest 14, and
# copy the dump to R2 under backups/ so a dead VPS disk does not take them along. Recordings already
# live in R2. Restore: gunzip -c <dump> | docker compose -f docker-compose.yml exec -T db psql -U audimax audimax
#
# Scheduled nightly on the VPS by cron:  0 3 * * *  /srv/audimax/scripts/backup.sh >> /srv/audimax/backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
# exec only needs the service names, which the base file has; it never picks up the local dev override.
compose=(docker compose -f docker-compose.yml)
mkdir -p backups
name="audimax-$(date +%Y%m%d-%H%M%S).sql.gz"
file="backups/$name"
"${compose[@]}" exec -T db pg_dump -U audimax --clean --if-exists audimax | gzip > "$file"
echo "wrote $file ($(du -h "$file" | cut -f1))"
"${compose[@]}" exec -T app python -c '
import sys
from app import storage
from app.config import settings
if not settings.r2_configured:
    print("R2 is not configured: the dump stays on this machine only")
    sys.exit()
storage.put_bytes(sys.argv[1], sys.stdin.buffer.read(), "application/gzip")
print("copied to R2:", sys.argv[1])
' "backups/$name" < "$file"
ls -1t backups/audimax-*.sql.gz | tail -n +15 | while read -r old; do rm -- "$old"; done
