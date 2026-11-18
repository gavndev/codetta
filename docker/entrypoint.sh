#!/bin/sh
# Start Codetta as the PUID/PGID user (not root), so files it edits in your
# music library keep the right owner and stay readable by Navidrome etc.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
PORT="${CODETTA_PORT:-${CODA_PORT:-8111}}"
CONFIG="${CODETTA_CONFIG_DIR:-${CODA_CONFIG_DIR:-/config}}"

# No per-request access log: health checks and polling would grow Docker's log forever.
set -- uvicorn codetta.web.app:app --host 0.0.0.0 --port "$PORT" --no-server-header --no-access-log "$@"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$CONFIG"
    # The config folder (account, presets, activity log) must belong to the
    # user Codetta runs as. Your music folder is never touched here.
    if ! chown -R "$PUID:$PGID" "$CONFIG" 2>/dev/null; then
        echo "codetta: warning: couldn't change the owner of $CONFIG to $PUID:$PGID" >&2
    fi
    echo "codetta: starting as user $PUID:$PGID on port $PORT"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups env HOME=/tmp "$@"
fi

# Already started as a non-root user (e.g. compose "user:"): just run.
echo "codetta: starting as user $(id -u):$(id -g) on port $PORT"
exec "$@"
