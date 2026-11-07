#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ -f .env ]; then
  echo '.env already exists; leaving your credentials and AI settings untouched.'
  exit 0
fi
umask 077
APP_PASSWORD="$(python3 -c 'import secrets;print(secrets.token_urlsafe(30))')"
cp .env.example .env
python3 - "$APP_PASSWORD" <<'PY'
import pathlib,sys
f=pathlib.Path('.env')
f.write_text(f.read_text().replace('replace-with-long-random-password',sys.argv[1]))
PY
echo 'Created .env with a unique password. KEEP THIS PASSWORD PRIVATE.'
echo "Login username: admin"
echo "Login password: ${APP_PASSWORD}"
echo 'The password is also stored in .env. Do not commit that file.'
