#!/bin/sh
# Admin commands, run as the same user as Coda so files stay readable:
#   docker exec -it coda coda-admin set-password
#   docker exec -it coda coda-admin sign-out-all
set -eu
if [ "$(id -u)" = "0" ]; then
    exec setpriv --reuid="${PUID:-1000}" --regid="${PGID:-1000}" --clear-groups env HOME=/tmp \
        python -m coda.cli "$@"
fi
exec python -m coda.cli "$@"
