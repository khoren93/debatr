#!/usr/bin/env bash
# Postgres backups of the Docker stack (run on the server, from cron).
#
#   scripts/backup-db.sh                # dump the database into BACKUP_DIR, prune old dumps
#   scripts/backup-db.sh --check [FILE] # restore FILE (default: the newest dump) into a scratch
#                                       # database next to the live one and compare row counts
#
# A dump is `pg_dump -Fc` (compressed, restorable table by table with pg_restore), written as
# `.partial`, checked with `pg_restore --list` and only then renamed, so a half-written file
# never looks like a backup. The dump holds emails, password hashes and the credit ledger:
# files are created 0600, and an off-site copy belongs in an encrypted place (an rclone `crypt`
# remote). Restoring for real: see CLAUDE.md ("Backups").
#
# Settings: environment, else the same names in .env.
#   BACKUP_DIR               where dumps go (default: ./backups, git-ignored)
#   BACKUP_KEEP_DAYS         local dumps older than this are deleted (default: 14)
#   BACKUP_RCLONE_REMOTE     optional rclone destination, e.g. "offsite:debatr-db"
#   BACKUP_REMOTE_KEEP_DAYS  remote dumps older than this are deleted (default: 60)
#   COMPOSE                  compose command (default: "docker compose")
set -euo pipefail
cd "$(dirname "$0")/.."

# A value from the environment, else from .env (read as text: .env is never sourced).
setting() {
  local name="$1" fallback="$2" value="${!1:-}"
  if [[ -z "$value" && -f .env ]]; then
    value="$(grep -E "^${name}=" .env | tail -n 1 | cut -d= -f2- || true)"
    value="${value%\"}" && value="${value#\"}" && value="${value%\'}" && value="${value#\'}"
  fi
  printf '%s' "${value:-$fallback}"
}

BACKUP_DIR="$(setting BACKUP_DIR ./backups)"
KEEP_DAYS="$(setting BACKUP_KEEP_DAYS 14)"
REMOTE="$(setting BACKUP_RCLONE_REMOTE '')"
REMOTE_KEEP_DAYS="$(setting BACKUP_REMOTE_KEEP_DAYS 60)"
read -r -a COMPOSE <<< "${COMPOSE:-docker compose}"

SCRATCH_DB="backup_restore_check"
# Dump files: debatr-<UTC stamp>.dump. Dumps from before the rename (ai_debates-*) are still
# pruned and checked; the new prefix sorts after the old one, so the newest stays last.
DUMP_PREFIX="debatr"
DUMP_NAMES=(-name "$DUMP_PREFIX-*.dump" -o -name "ai_debates-*.dump")
# Tables whose row counts the check compares (the money and the content).
CHECK_TABLES=(users credit_transactions api_tokens debates turns debate_participants
  debate_likes debate_votes trending_batches trending_topics)

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

# psql in the db container, as the stack's user (the credentials stay in the container's env).
db_sql() {
  local database="$1" query="$2"
  "${COMPOSE[@]}" exec -T db sh -c 'PGOPTIONS="-c client_min_messages=warning" psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "$2"' \
    sh "$database" "$query"
}

live_db() {
  "${COMPOSE[@]}" exec -T db sh -c 'printf %s "$POSTGRES_DB"'
}

backup() {
  umask 077
  mkdir -p "$BACKUP_DIR"
  local stamp file
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  file="$BACKUP_DIR/$DUMP_PREFIX-$stamp.dump"

  log "Dumping the database to $file"
  "${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' \
    > "$file.partial" || { rm -f "$file.partial"; fail "pg_dump failed"; }
  "${COMPOSE[@]}" exec -T db pg_restore --list < "$file.partial" > /dev/null \
    || { rm -f "$file.partial"; fail "the dump is not readable by pg_restore"; }
  mv "$file.partial" "$file"
  local size
  size="$(wc -c < "$file" | tr -d ' ')"
  log "Dump ready: $size bytes"

  find "$BACKUP_DIR" -maxdepth 1 \( "${DUMP_NAMES[@]}" \) -mtime "+$KEEP_DAYS" -print -delete \
    | sed 's/^/  pruned /'

  local remote_status="off"
  if [[ -n "$REMOTE" ]]; then
    command -v rclone > /dev/null || fail "BACKUP_RCLONE_REMOTE is set but rclone is not installed"
    log "Uploading to $REMOTE"
    rclone copy "$file" "$REMOTE" || fail "upload to $REMOTE failed (the local dump is kept)"
    rclone delete "$REMOTE" --min-age "${REMOTE_KEEP_DAYS}d" \
      --include "$DUMP_PREFIX-*.dump" --include 'ai_debates-*.dump' \
      || log "WARNING: could not prune old remote dumps"
    remote_status="ok"
  fi

  # For the admin console (system page, alerts): when the last good backup was made.
  local status
  status="{\"at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"file\":\"$(basename "$file")\",\"bytes\":$size,\"remote\":\"$remote_status\"}"
  "${COMPOSE[@]}" exec -T redis redis-cli SET backup:last "$status" > /dev/null \
    || log "WARNING: could not record the backup in Redis"
  log "Backup done"
}

check() {
  local file="${1:-}"
  if [[ -z "$file" ]]; then
    file="$(find "$BACKUP_DIR" -maxdepth 1 \( "${DUMP_NAMES[@]}" \) -print 2>/dev/null | sort | tail -n 1)"
  fi
  [[ -n "$file" && -f "$file" ]] || fail "no dump to check (looked in $BACKUP_DIR)"

  local live
  live="$(live_db)"
  [[ "$live" != "$SCRATCH_DB" ]] || fail "the live database is called $SCRATCH_DB"
  log "Restoring $file into the scratch database $SCRATCH_DB"
  trap 'db_sql postgres "DROP DATABASE IF EXISTS $SCRATCH_DB" > /dev/null || true' EXIT
  db_sql postgres "DROP DATABASE IF EXISTS $SCRATCH_DB" > /dev/null
  db_sql postgres "CREATE DATABASE $SCRATCH_DB" > /dev/null
  "${COMPOSE[@]}" exec -T db sh -c \
    'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --exit-on-error' sh "$SCRATCH_DB" < "$file" \
    || fail "pg_restore failed"

  local problems=0 table restored current
  printf '  %-22s %10s %10s\n' table backup live
  for table in "${CHECK_TABLES[@]}"; do
    restored="$(db_sql "$SCRATCH_DB" "SELECT count(*) FROM $table" 2>/dev/null || echo missing)"
    current="$(db_sql "$live" "SELECT count(*) FROM $table" 2>/dev/null || echo missing)"
    printf '  %-22s %10s %10s\n' "$table" "$restored" "$current"
    if [[ "$restored" == missing ]]; then
      problems=$((problems + 1))
    elif [[ "$current" =~ ^[0-9]+$ && "$restored" -gt "$current" ]]; then
      log "WARNING: $table has more rows in the backup than live (rows deleted since?)"
    fi
  done
  local revision live_revision balance live_balance
  revision="$(db_sql "$SCRATCH_DB" "SELECT version_num FROM alembic_version")"
  live_revision="$(db_sql "$live" "SELECT version_num FROM alembic_version")"
  balance="$(db_sql "$SCRATCH_DB" "SELECT coalesce(sum(credits_usd), 0) FROM users")"
  live_balance="$(db_sql "$live" "SELECT coalesce(sum(credits_usd), 0) FROM users")"
  printf '  %-22s %10s %10s\n' migration "$revision" "$live_revision"
  printf '  %-22s %10s %10s\n' "sum of balances" "$balance" "$live_balance"

  ((problems == 0)) || fail "$problems tables are missing from the backup"
  log "Restore check passed"
}

case "${1:-}" in
  --check) check "${2:-}" ;;
  "") backup ;;
  *) fail "usage: $0 [--check [FILE]]" ;;
esac
