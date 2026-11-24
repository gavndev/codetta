"""A protective layer in front of every request.

* **Size limits.** Request bodies are capped per endpoint *before* they're
  read, so nobody (signed in or not) can exhaust the server's memory.
* **Cross-site protection.** Requests that change something must come from
  Codetta's own page. Browsers label requests with ``Sec-Fetch-Site``; for
  older ones we compare ``Origin`` with the host. This also blocks other apps
  on the same server (other ports count as the "same site" for cookies).
* **Allowed hosts** (optional). With ``CODETTA_ALLOWED_HOSTS`` set, requests
  for any other host name are refused, which stops DNS-rebinding attacks.
* **Security headers** on every response: a strict Content Security Policy
  (scripts only from Codetta itself), no framing, no MIME sniffing.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from codetta.core.artwork import MAX_ART_BYTES
from codetta.core.avatar import MAX_AVATAR_BYTES
from codetta.core.importer import MAX_IMPORT_BYTES

KB = 1024
MB = 1024 * KB

# Largest request body accepted, by path (the image limits come from the core
# modules, so there's one source of truth). Everything else gets DEFAULT_LIMIT.
BODY_LIMITS = {
    "/api/art": MAX_ART_BYTES,
    "/api/account/avatar": MAX_AVATAR_BYTES,
    "/api/import": MAX_IMPORT_BYTES,  # one music file per request, streamed to disk
}
DEFAULT_LIMIT = 1 * MB  # JSON: tag edits, presets, sign-in...
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",  # style="" attributes on a few elements
    "img-src 'self' blob: data:",  # blob: previews of pending art / avatars
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
]
# The interactive API docs load Swagger UI from a CDN, so they get no CSP.
NO_CSP_PATHS = ("/docs", "/openapi.json")


def _first(value: str) -> str:
    """X-Forwarded-Host can be a list ("a.example, b.internal"); the first is the client's."""
    return value.split(",")[0].strip()


def _host_only(host: str) -> str:
    """ "Example.com:8111" -> "example.com", "[::1]:8111" -> "::1"."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class GuardMiddleware:
    """Pure ASGI middleware (runs before FastAPI reads anything)."""

    def __init__(self, app, allowed_hosts: set[str] | None = None) -> None:
        self.app = app
        self.allowed_hosts = {h.strip().lower() for h in allowed_hosts or set() if h.strip()}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method = scope["method"].upper()
        path = scope["path"]
        # The names this request was addressed to: Host, and behind a reverse
        # proxy the original one it forwards. (A web page can't set
        # X-Forwarded-Host on a cross-site request, so trusting it is safe.)
        hosts = [h for h in (headers.get("host", ""), _first(headers.get("x-forwarded-host", ""))) if h]

        if self.allowed_hosts and not any(_host_only(h) in self.allowed_hosts for h in hosts):
            return await _reject(send, 421, "This server doesn't answer to that host name.")

        # /rest/ (music apps) never uses the session cookie (every request carries the app's own
        # sign-in), so a web player on another site can't ride on anyone's session: the
        # cross-site check, which protects the cookie, doesn't apply there.
        if method not in SAFE_METHODS and not path.startswith("/rest/"):
            site = headers.get("sec-fetch-site")
            if site is not None:
                if site not in ("same-origin", "none"):
                    return await _reject(send, 403, "Cross-site request blocked.")
            else:
                origin = headers.get("origin")
                if origin is not None:
                    # "null" comes from sandboxed frames and cross-site redirects: never ours.
                    netloc = urlsplit(origin).netloc.lower() if origin != "null" else None
                    if netloc not in {h.lower() for h in hosts}:
                        return await _reject(send, 403, "Cross-site request blocked.")

        if method not in SAFE_METHODS:  # size limits apply everywhere, /rest/ included
            limit = BODY_LIMITS.get(path, DEFAULT_LIMIT)
            length = headers.get("content-length")
            if length is None:
                if "chunked" in headers.get("transfer-encoding", "").lower():
                    return await _reject(send, 411, "Send a Content-Length header.")
            else:
                try:
                    if int(length) > limit:
                        return await _reject(send, 413, f"Request too large (max {limit // MB or 1} MB).")
                except ValueError:
                    return await _reject(send, 400, "Invalid Content-Length.")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = list(SECURITY_HEADERS)
                if path.startswith("/static/") and path.endswith((".js", ".css")):
                    # Always check with the server (a tiny 304 when unchanged), so an update is
                    # picked up on the next load instead of whenever the browser feels like it.
                    extra.append((b"cache-control", b"no-cache"))
                if not path.startswith(NO_CSP_PATHS):
                    extra.append((b"content-security-policy", CSP.encode()))
                existing = {k.lower() for k, _ in message.get("headers", [])}
                message = {**message, "headers": [*message.get("headers", []),
                                                  *[(k, v) for k, v in extra if k not in existing]]}
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Already compressed (images, fonts) or must stay byte-exact for seeking (audio): never gzipped.
NO_GZIP_PATHS = ("/api/stream", "/api/art", "/api/account/avatar", "/api/musicbrainz/cover", "/api/import")
GZIP_STATIC = (".js", ".css", ".svg", ".html", ".json", ".txt", ".webmanifest")


def gzip_worthy(path: str) -> bool:
    """Text Codetta sends (the page, its script and styles, API answers) shrinks to a
    quarter with gzip, which matters on a phone; media doesn't shrink at all."""
    if path == "/":
        return True
    if path.startswith("/static/"):
        return path.lower().endswith(GZIP_STATIC)
    return path.startswith("/api/") and not path.startswith(NO_GZIP_PATHS)


class SelectiveGZip:
    """Starlette's GZipMiddleware, only for responses that are worth it."""

    def __init__(self, app, minimum_size: int = 1400) -> None:
        from starlette.middleware.gzip import GZipMiddleware
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size, compresslevel=6)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and gzip_worthy(scope["path"]):
            return await self.gzip(scope, receive, send)
        return await self.app(scope, receive, send)


async def _reject(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
        *SECURITY_HEADERS,
    ]})
    await send({"type": "http.response.body", "body": body})
