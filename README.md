# Coda

A clean, self-hosted music metadata editor for your homelab. Point it at your
music folder, open it in a browser (desktop or phone), and fix tags on FLAC,
MP3, M4A, OGG and Opus files, one track or a whole album at a time.

Built for libraries served by Navidrome and other OpenSubsonic servers: Coda
writes the tags those apps read (credits, mood, label, release type, multiple
artists…), in the same places MusicBrainz Picard does.

## Features

- **Edit tags** on one track or many at once. Mixed values show as "Multiple values" and stay untouched unless you change them.
- **Save to folder**: apply the fields you changed to every track in the album.
- **Smart suggestions**: album-level fields offer values other tracks in the folder already use; Track suggests the file's position.
- **Copy & paste tags** between tracks and folders.
- **Album art**: add, replace or remove embedded covers (JPEG/PNG), including from your phone's photo library.
- **Tag Loadouts**: saved sets of tags with placeholders (`{filename_title}`, `{folder}`, `{track}/{tracktotal}`) to turn loose downloads into properly tagged singles or albums, with a preview before anything is written.
- **Filter a folder by tag** (e.g. Label = Independent).
- **Activity log** of every change, with old → new values, kept across restarts.
- **Safe writes**: every change is written to a temporary copy, verified, then swapped in atomically. A failed write never damages the original. Symlinks, hard links, permissions and cover art are preserved.
- **Sign-in** with a hashed password, long-lived sessions and brute-force lockout.
- Light and dark themes, works great on iPhone, no internet needed (fonts are bundled).

## Quick start (Docker Compose)

1. Get the code onto your server and open `docker-compose.yml`.
2. Change `/path/to/your/music` to your music folder.
3. Set `PUID` / `PGID` to the user and group that own your music (run `id` on the server to see them).
4. Start it:

   ```sh
   docker compose up -d
   ```

5. Open `http://<your-server>:8111` and create your account.

Coda runs as `PUID:PGID`, never as root, so files it edits keep their owner and
stay readable by Navidrome and friends.

## Settings

All optional, set under `environment:` in `docker-compose.yml`:

| Variable | Default | What it does |
|---|---|---|
| `PUID` / `PGID` | `1000` | User and group Coda runs as. Match your music files' owner. |
| `CODA_PORT` | `8111` | Port inside the container. |
| `CODA_USERNAME` + `CODA_PASSWORD` | – | Set the account here instead of on the setup screen. The password can then only be changed here. |
| `CODA_AUTH` | `on` | `off` disables sign-in. **Only** use this behind a reverse proxy that already requires a login. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Behind a reverse proxy, the proxy's IP, so sign-in lockouts see real client addresses. |

Folders inside the container:

| Path | Contents |
|---|---|
| `/music` | Your library (read-write). |
| `/config` | Your account, sessions, loadouts and `activity.jsonl`. Back this up. |

## Signing in

- The first visit shows **Welcome to Coda**: choose a username and a password (8+ characters).
- Each browser stays signed in for 30 days. Change your password or sign out from the person icon in the top bar. Changing the password signs out your other devices.
- After 5 wrong passwords, that device must wait (30 s, doubling up to 15 min).

**Forgot your password?** Reset it from the server:

```sh
docker exec -it coda coda-admin set-password
```

`docker exec -it coda coda-admin sign-out-all` signs out every device.

## HTTPS

Coda serves plain HTTP. On your LAN or over Tailscale (which already encrypts
traffic between your devices) that's fine. For a real `https://` address:

- **Tailscale:** `tailscale serve --bg 8111` on the server gives you `https://<server>.<tailnet>.ts.net`.
- **Reverse proxy** (Caddy, Traefik, nginx…): point it at port 8111. Coda marks its session cookie `Secure` when the proxy sends `X-Forwarded-Proto: https`.

Don't expose Coda directly to the internet without HTTPS.

## Supported formats

FLAC, MP3, M4A (AAC/ALAC), OGG Vorbis and Opus. FLAC, OGG and Opus accept any
tag name; MP3 and M4A accept the standard set Coda lists in the editor.

## Development

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
CODA_MUSIC_DIR=~/some-test-music uvicorn coda.web.app:app --reload --port 8111
```

Use a **copy** of some music while developing. Project notes for contributors
are in `CLAUDE.md` and the roadmap is in `PLAN.md`.
