# Codetta: self-hosted music metadata editor.
#
#   docker compose up -d          (see docker-compose.yml)
#
# Two stages: "build" installs Codetta into a virtual environment; the final
# image only copies that environment, so no build leftovers ship.

# ---- Build -----------------------------------------------------------------------
FROM python:3.14-alpine AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
# The app's environment has no pip of its own: it's installed into from outside.
RUN python -m venv --without-pip /opt/venv
WORKDIR /src

# Install dependencies first (cached until pyproject.toml changes)...
COPY pyproject.toml ./
RUN mkdir -p src/codetta && touch src/codetta/__init__.py \
    && pip --python /opt/venv/bin/python install . \
    && pip --python /opt/venv/bin/python uninstall -y codetta

# ...then Codetta itself.
COPY src ./src
RUN pip --python /opt/venv/bin/python install --no-deps . \
    && find /opt/venv -name "*.dist-info" -prune -o -type d -name tests -prune -exec rm -rf {} +

# ---- Runtime -----------------------------------------------------------------------
# Alpine keeps the image small (fits starter hardware); everything Codetta needs
# is pure Python or has musl wheels.
FROM python:3.14-alpine

LABEL org.opencontainers.image.title="Codetta" \
      org.opencontainers.image.description="Self-hosted music metadata editor for FLAC, MP3, M4A, OGG and Opus libraries" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/gavndev/codetta"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CODETTA_MUSIC_DIR=/music \
    CODETTA_CONFIG_DIR=/config \
    CODETTA_PORT=8111 \
    PUID=1000 \
    PGID=1000

# setpriv drops root to PUID:PGID. Then remove what a running app never uses:
# pip and the interpreter's developer tools.
RUN apk add --no-cache setpriv \
    && rm -rf /usr/local/lib/python3.14/site-packages/pip* /usr/local/lib/python3.14/ensurepip \
              /usr/local/lib/python3.14/idlelib /usr/local/lib/python3.14/turtledemo \
              /usr/local/lib/python3.14/tkinter /usr/local/lib/python3.14/pydoc_data \
              /usr/local/bin/pip* /usr/local/bin/idle* /usr/local/bin/pydoc*

COPY --from=build /opt/venv /opt/venv
COPY docker/entrypoint.sh /usr/local/bin/codetta-entrypoint
COPY docker/codetta-admin.sh /usr/local/bin/codetta-admin
RUN chmod 755 /usr/local/bin/codetta-entrypoint /usr/local/bin/codetta-admin \
    && mkdir -p /music /config

EXPOSE 8111
# busybox wget: far lighter than starting Python every 30 seconds.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${CODETTA_PORT:-8111}/api/health" || exit 1

ENTRYPOINT ["codetta-entrypoint"]
