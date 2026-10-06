#!/usr/bin/env bash
# Dump the database (users, transcripts, scripts, embeddings, job history) to backups/, keep the
# newest 14. Recordings and generated audio live in R2, not here.
#
# Schedule it on the VPS, e.g. nightly:  0 3 * * *  cd /srv/audimax && ./scripts/backup.sh
# Copy backups/ off the VPS too (rclone to R2/another bucket), or a dead disk takes the dumps with it.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
file="backups/audimax-$(date +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T db pg_dump -U audimax --clean --if-exists audimax | gzip > "$file"
echo "wrote $file ($(du -h "$file" | cut -f1))"
ls -1t backups/audimax-*.sql.gz | tail -n +15 | while read -r old; do rm -- "$old"; done
