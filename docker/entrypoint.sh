#!/bin/sh
# Start Coda as the PUID/PGID user (not root), so files it edits in your
# music library keep the right owner and stay readable by Navidrome etc.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
PORT="${CODA_PORT:-8111}"
CONFIG="${CODA_CONFIG_DIR:-/config}"

set -- uvicorn coda.web.app:app --host 0.0.0.0 --port "$PORT" --no-server-header "$@"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$CONFIG"
    # The config folder (account, loadouts, activity log) must belong to the
    # user Coda runs as. Your music folder is never touched here.
    if ! chown -R "$PUID:$PGID" "$CONFIG" 2>/dev/null; then
        echo "coda: warning: couldn't change the owner of $CONFIG to $PUID:$PGID" >&2
    fi
    echo "coda: starting as user $PUID:$PGID on port $PORT"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups env HOME=/tmp "$@"
fi

# Already started as a non-root user (e.g. compose "user:"): just run.
echo "coda: starting as user $(id -u):$(id -g) on port $PORT"
exec "$@"
