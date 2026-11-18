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

# Chromaprint's fpcalc for "Identify by sound": the official static build
# (a few MB, instead of Alpine's package, which pulls in all of ffmpeg),
# checked against the SHA-256 GitHub publishes for it.
ARG TARGETARCH
ARG FPCALC_VERSION=1.6.2
RUN case "${TARGETARCH:-$(uname -m)}" in \
      amd64|x86_64) arch=x86_64; sum=c968ad4a0821592a79b158fb2e1f46cbe0a22a0a1dbc0743c67d68e75d15d2bb ;; \
      arm64|aarch64) arch=arm64; sum=3aa1498126ed272d805bc9d081c77965c9e1e1a0891bb112c13b56ef2ad47bad ;; \
      *) echo "No fpcalc build for this CPU (${TARGETARCH:-$(uname -m)})" >&2; exit 1 ;; \
    esac \
    && name="chromaprint-fpcalc-${FPCALC_VERSION}-linux-${arch}" \
    && python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/fpcalc.tgz')" \
         "https://github.com/acoustid/chromaprint/releases/download/v${FPCALC_VERSION}/${name}.tar.gz" \
    && echo "${sum}  /tmp/fpcalc.tgz" | sha256sum -c - \
    && tar -xzf /tmp/fpcalc.tgz -C /tmp \
    && install -m 755 "/tmp/${name}/fpcalc" /usr/local/bin/fpcalc

# ---- Runtime -----------------------------------------------------------------------
# Alpine keeps the image small (fits starter hardware); everything Codetta needs
# is pure Python or has musl wheels.
FROM python:3.14-alpine

LABEL org.opencontainers.image.title="Codetta" \
      org.opencontainers.image.description="Self-hosted music library manager: find music on Soulseek (via slskd), match it on MusicBrainz, fix tags and file it" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/gavndev/codetta"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CODETTA_MUSIC_DIR=/music \
    CODETTA_CONFIG_DIR=/config \
    CODETTA_INBOX_DIR=/inbox \
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
COPY --from=build /usr/local/bin/fpcalc /usr/local/bin/fpcalc
COPY docker/entrypoint.sh /usr/local/bin/codetta-entrypoint
COPY CHANGELOG.md /opt/codetta/CHANGELOG.md
COPY docker/codetta-admin.sh /usr/local/bin/codetta-admin
RUN chmod 755 /usr/local/bin/codetta-entrypoint /usr/local/bin/codetta-admin \
    && mkdir -p /music /config

EXPOSE 8111
# busybox wget: far lighter than starting Python every 30 seconds.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${CODETTA_PORT:-8111}/api/health" || exit 1

ENTRYPOINT ["codetta-entrypoint"]
