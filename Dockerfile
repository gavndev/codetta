# Codetta: self-hosted music metadata editor.
#
#   docker compose up -d          (see docker-compose.yml)
#
# Two stages: "build" installs Codetta into a virtual environment; the final
# image only copies that environment, so no build leftovers ship.

# ---- Build -----------------------------------------------------------------------
FROM python:3.14-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src

# Install dependencies first (cached until pyproject.toml changes)...
COPY pyproject.toml ./
RUN mkdir -p src/codetta && touch src/codetta/__init__.py \
    && pip install . \
    && pip uninstall -y codetta

# ...then Codetta itself.
COPY src ./src
RUN pip install --no-deps .

# ---- Runtime -----------------------------------------------------------------------
FROM python:3.14-slim

LABEL org.opencontainers.image.title="Codetta" \
      org.opencontainers.image.description="Self-hosted music metadata editor for FLAC, MP3, M4A, OGG and Opus libraries"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CODETTA_MUSIC_DIR=/music \
    CODETTA_CONFIG_DIR=/config \
    CODETTA_PORT=8111 \
    PUID=1000 \
    PGID=1000

COPY --from=build /opt/venv /opt/venv
COPY docker/entrypoint.sh /usr/local/bin/codetta-entrypoint
COPY docker/codetta-admin.sh /usr/local/bin/codetta-admin
COPY docker/healthcheck.py /usr/local/bin/codetta-healthcheck
RUN chmod 755 /usr/local/bin/codetta-entrypoint /usr/local/bin/codetta-admin /usr/local/bin/codetta-healthcheck \
    && mkdir -p /music /config

EXPOSE 8111
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "/usr/local/bin/codetta-healthcheck"]

ENTRYPOINT ["codetta-entrypoint"]
