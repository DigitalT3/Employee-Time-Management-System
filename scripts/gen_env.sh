#!/usr/bin/env bash
# Generate missing backend/.env settings for the local PostgreSQL installation.
# Existing values are never overwritten, so the script is safe to re-run.
set -euo pipefail

source "$(dirname "$0")/_common.sh"

ENV_FILE="$REPO_ROOT/backend/.env"
PYTHON="$REPO_ROOT/backend/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

random_secret() {
  "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))'
}

random_fernet_key() {
  "$PYTHON" -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'
}

random_password() {
  "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(20))'
}

append_if_missing() {
  local key="$1"
  local value="$2"
  touch "$ENV_FILE"
  if ! grep -qE "^${key}=" "$ENV_FILE"; then
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    printf 'Added %s to backend/.env\n' "$key"
  fi
}

append_if_missing "DATABASE_URL" "postgresql+psycopg://$PGUSER_LOCAL@127.0.0.1:$PGPORT/etms_dev"
append_if_missing "TEST_DATABASE_URL" "postgresql+psycopg://$PGUSER_LOCAL@127.0.0.1:$PGPORT/etms_test"
append_if_missing "SECRET_KEY" "$(random_secret)"
append_if_missing "FERNET_KEY" "$(random_fernet_key)"
append_if_missing "APP_TIMEZONE" "Europe/Amsterdam"
append_if_missing "CORS_ORIGINS" "http://localhost:3000"
append_if_missing "APP_ENV" "dev"
append_if_missing "COOKIE_SECURE" "false"
append_if_missing "SESSION_TTL_HOURS" "12"
append_if_missing "OFFLINE_MAX_AGE_HOURS" "48"
append_if_missing "ONLINE_SKEW_SECONDS" "30"
append_if_missing "FUTURE_TOLERANCE_SECONDS" "60"
append_if_missing "LOGIN_MAX_FAILURES" "5"
append_if_missing "LOGIN_LOCK_MINUTES" "15"
append_if_missing "SEED_ADMIN_PASSWORD" "$(random_password)"
append_if_missing "SEED_SUPERVISOR_PASSWORD" "$(random_password)"
append_if_missing "SEED_HR_PASSWORD" "$(random_password)"

echo "backend/.env is ready; existing values were preserved."
