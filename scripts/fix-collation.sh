#!/bin/sh
# Repairs a Postgres "collation version mismatch" after a Railway OS (glibc) upgrade.
# Rebuilds user indexes, then records the new collation version so the warning stops.
# Runs on every boot but only does work when a mismatch is detected (otherwise a
# no-op). Always exits 0 so it can never block n8n startup.
set -u
log() { echo "[fix-collation] $*"; }

[ "${DB_TYPE:-}" = "postgresdb" ] || { log "DB_TYPE not postgresdb; skipping."; exit 0; }

DB="${DB_POSTGRESDB_DATABASE:-}"
HOST="${DB_POSTGRESDB_HOST:-}"
PORT="${DB_POSTGRESDB_PORT:-5432}"
USER="${DB_POSTGRESDB_USER:-}"
export PGPASSWORD="${DB_POSTGRESDB_PASSWORD:-}"

[ -n "$DB" ] && [ -n "$HOST" ] && [ -n "$USER" ] || { log "Postgres vars incomplete; skipping."; exit 0; }

PSQL="psql -X -q -h $HOST -p $PORT -U $USER -d $DB -v ON_ERROR_STOP=1"

# Recorded default-collation version vs. what the OS currently provides (PG15+).
MISMATCH=$($PSQL -tA -c \
  "SELECT count(*) FROM pg_database WHERE datname = current_database() \
   AND datcollversion IS DISTINCT FROM pg_database_collation_actual_version(oid);" 2>/dev/null) || {
    log "Could not query collation status (DB unreachable / perms); skipping."; exit 0; }

if [ "${MISMATCH:-0}" = "0" ]; then
  log "Collation version OK for \"$DB\"; nothing to do."
  exit 0
fi

log "Collation mismatch detected for \"$DB\"; reindexing concurrently..."
# REINDEX ... CONCURRENTLY must NOT run inside a transaction (psql autocommit is fine).
if $PSQL -c "REINDEX DATABASE CONCURRENTLY \"$DB\";"; then
  $PSQL -c "ALTER DATABASE \"$DB\" REFRESH COLLATION VERSION;" \
    && log "Done; collation version refreshed for \"$DB\"." \
    || log "Refresh failed; will retry next boot."
else
  log "Reindex failed; leaving version unchanged so it retries next boot."
fi
exit 0
