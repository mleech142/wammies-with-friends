#!/bin/sh
# Back up a self-hosted copy (docs/self-hosting.md, Backups): run it on the server, e.g. nightly from cron.
# Saves a consistent copy of the database (taken while the app runs), the app data JSON, settings.json and
# secret_key as BACKUP_DIR/wammies-<date>.tar.gz, and deletes those older than KEEP days. The BSData and
# Wahapedia downloads aren't included: the Setup page downloads them again.
set -eu
COMPOSE_DIR=${COMPOSE_DIR:-/opt/combat-sim}  # The folder with compose.yaml
BACKUP_DIR=${BACKUP_DIR:-/var/backups/wammies-with-friends}
KEEP=${KEEP:-14}

file="wammies-$(date +%F).tar.gz"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
cd "$COMPOSE_DIR"
docker compose exec -T combat-sim python - <<'PY'
import os, sqlite3, tarfile
source, copy = sqlite3.connect('/data/combat_sim.db'), sqlite3.connect('/tmp/backup.db')
source.backup(copy)  # SQLite's own online backup: consistent even mid-game
copy.close()
source.close()
with tarfile.open('/tmp/backup.tar.gz', 'w:gz') as tar:
    tar.add('/tmp/backup.db', 'combat_sim.db')
    for name in ('app_data.json', 'settings.json', 'secret_key'):
        if os.path.exists(f'/data/{name}'):
            tar.add(f'/data/{name}', name)
os.remove('/tmp/backup.db')
PY
docker compose cp combat-sim:/tmp/backup.tar.gz "$BACKUP_DIR/$file"
docker compose exec -T combat-sim rm -f /tmp/backup.tar.gz
chmod 600 "$BACKUP_DIR/$file"
find "$BACKUP_DIR" -name 'wammies-*.tar.gz' -mtime +"$KEEP" -delete
echo "Saved $BACKUP_DIR/$file"
