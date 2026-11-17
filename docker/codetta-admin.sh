#!/bin/sh
# Admin commands, run as the same user as Codetta so files stay readable:
#   docker exec -it codetta codetta-admin set-password
#   docker exec -it codetta codetta-admin sign-out-all
set -eu
if [ "$(id -u)" = "0" ]; then
    exec setpriv --reuid="${PUID:-1000}" --regid="${PGID:-1000}" --clear-groups env HOME=/tmp \
        python -m codetta.cli "$@"
fi
exec python -m codetta.cli "$@"
