[← Back to the README](../README.md)

# Configuration

## Settings

All optional. Set them under `environment:` in your
`docker-compose.override.yml`.

| Variable | Default | What it does |
|---|---|---|
| `PUID` / `PGID` | `1000` | The user and group Codetta runs as. Match your music files' owner. |
| `CODETTA_PORT` | `8111` | The port inside the container. To use a different port on your server, change the `ports:` mapping instead. |
| `CODETTA_USERNAME` + `CODETTA_PASSWORD` | – | Create the account from here instead of the setup screen. The password can then only be changed here. |
| `CODETTA_AUTH` | `on` | Set to `off` to disable sign-in. **Only** do this if a reverse proxy in front of Codetta already requires a login. |
| `CODETTA_ALLOW_PUBLIC_SETUP` | `off` | The setup screen only works from home networks, Tailscale and the server itself, so nobody on the internet can claim a fresh install. Set to `on` only if you must set up over the internet. |
| `CODETTA_ALLOWED_HOSTS` | – | Comma-separated host names Codetta answers to (e.g. `music-server,192.168.1.50`). Other names are refused, which blocks DNS-rebinding attacks. Recommended if more than your own devices can reach Codetta. |
| `CODETTA_INDEX_WORKERS` | one fewer than your CPU cores, up to 4 | Helper processes that read your library the first time (or after a big import). 4 read about 3.5× faster than 1. Set `1` on a very small machine to keep memory lowest; they only run while there's a lot to read, then stop. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Behind a reverse proxy, set this to the proxy's IP so login lockouts see each visitor's real address. |

| Folder in the container | What's in it |
|---|---|
| `/music` | Your library. Codetta needs read-write access to edit it. |
| `/inbox` (optional) | Where new music lands, e.g. slskd's or your torrent client's downloads folder. The **Inbox** files albums from here into `/music`. Needs read-write access. Without Docker, set `CODETTA_INBOX_DIR` instead. |
| `/config` | Your account, sessions, profile picture, presets, connection choices, the activity log, previous album art kept for undo, and the search index (rebuilt automatically if deleted). Include it in your backups. `config-version.json` records which settings layout the folder is in: when an update changes it, Codetta first copies your settings into `backups/` (the last three are kept), and it never changes settings saved by a newer version. |

## Connections (online features)

Codetta is **fully offline unless you opt in**. Online features are called
*connections*, and they're all off until you turn them on. You can do that on
the welcome card after creating your account, any time in
**Settings → Connections**, or with these settings. Setting one locks its
switch in the app, which is handy if you manage everything from your compose file.

| Variable | Default | What it does |
|---|---|---|
| `CODETTA_OFFLINE` | `off` | Set to `on` to block every connection, whatever else is set. The app then never asks. |
| `CODETTA_MUSICBRAINZ` | chosen in the app | `on`/`off`: **Match on MusicBrainz** for album folders (official titles, credits, dates, labels, IDs) and cover art from the Cover Art Archive. Sends the album/artist names you search for and the release IDs you pick to musicbrainz.org and coverartarchive.org. |
| `CODETTA_MUSICBRAINZ_URL` | – | Use your own [MusicBrainz mirror](https://github.com/metabrainz/musicbrainz-docker) instead of musicbrainz.org, e.g. `http://musicbrainz:5000`. No rate limit, and lookups stay on your network (cover art still comes from the Cover Art Archive). |
| `CODETTA_DISCOGS` | chosen in the app | `on`/`off`: **Discogs** as an album source (Find in Discogs, `!dg`, pasted Discogs links): label, catalogue number, format, styles and credits, strong for vinyl and rare releases. Sends the names you search for and the release IDs you pick to api.discogs.com. |
| `CODETTA_DISCOGS_TOKEN` | set in the app | Your personal Discogs token (discogs.com → Settings → Developers), which searching needs. Saved tokens live in `discogs.json` in the config folder, readable by Codetta only, and are never sent back to the browser. |
| `CODETTA_ACOUSTID` | chosen in the app | `on`/`off`: **Identify by sound** in the MusicBrainz match. Codetta fingerprints each track on your server with Chromaprint's `fpcalc` (included in the Docker image) and sends only that short code and the track length to [AcoustID](https://acoustid.org). Needs the MusicBrainz connection too. |
| `CODETTA_ACOUSTID_KEY` | Codetta's key | Use your own AcoustID application key instead of the one built into Codetta. |
| `CODETTA_FPCALC` | found on `PATH` | Path to `fpcalc`, if you run Codetta outside Docker (install it with `apt install libchromaprint-tools` or `brew install chromaprint`). |
| `CODETTA_FFMPEG` | found on `PATH` | Path to `ffmpeg`, used to measure loudness for ReplayGain, if you run Codetta outside Docker (`apt install ffmpeg`, `brew install ffmpeg`, `winget install ffmpeg`). |
| `CODETTA_SLSKD` | chosen in the app | `on`/`off`: **Soulseek through slskd**: search and download from Soulseek with your own [slskd](https://github.com/slskd/slskd). Searches go to your slskd, which asks other Soulseek users. Downloads must land in Codetta's inbox, so mount slskd's downloads folder at `/inbox`. |
| `CODETTA_SLSKD_URL` | set in the app | slskd's address as Codetta sees it, e.g. `http://slskd:5030` (same Docker network) or `http://192.168.1.50:5030`. Locks the field in the app. |
| `CODETTA_LIDARR` | chosen in the app | `on`/`off`: **Lidarr**: after Codetta changes files in Lidarr's folders, Lidarr rescans them straight away, and Codetta warns about Lidarr settings that would undo your fixes. See [Using Codetta with Lidarr](lidarr.md). |
| `CODETTA_LIDARR_URL` | set in the app | Lidarr's address as Codetta sees it, e.g. `http://lidarr:8686`. Locks the field in the app. |
| `CODETTA_MEDIA_SERVER` | chosen in the app | `on`/`off`: **Music server**: after Codetta changes files, your Navidrome (or other Subsonic server), Jellyfin, Emby or Plex gets a quick scan. See [Using Codetta with your music server](media-servers.md). |
| `CODETTA_MEDIA_SERVER_KIND` | set in the app | `subsonic`, `jellyfin`, `emby` or `plex`. |
| `CODETTA_MEDIA_SERVER_URL` | set in the app | The server's address as Codetta sees it, e.g. `http://navidrome:4533`. |
| `CODETTA_MEDIA_SERVER_USER` / `CODETTA_MEDIA_SERVER_PASSWORD` | set in the app | Sign-in for Subsonic servers (Navidrome needs an admin user to start scans). |
| `CODETTA_MEDIA_SERVER_TOKEN` | set in the app | The Jellyfin/Emby API key or Plex token. Saved sign-ins live in `mediaserver.json` in the config folder, readable by Codetta only, and are never sent back to the browser. |
| `CODETTA_LIDARR_API_KEY` | set in the app | Lidarr's API key (Settings → General). Saved keys live in `lidarr.json` in the config folder, readable by Codetta only, and are never sent back to the browser. |
| `CODETTA_SLSKD_API_KEY` | set in the app | An API key from slskd's settings (`web → authentication → api_keys`, 16+ characters). Saved keys live in `slskd.json` in the config folder, readable by Codetta only, and are never sent back to the browser. |
| `CODETTA_AUDIOMUSE` | chosen in the app | `on`/`off`: **AudioMuse-AI** for Autoplay: songs that sound like the one playing, from your own [AudioMuse-AI](https://github.com/NeptuneHub/AudioMuse-AI) server. Sends the playing song's title and artist to it. See [Autoplay](autoplay.md). |
| `CODETTA_AUDIOMUSE_URL` | set in the app | AudioMuse-AI's address as Codetta sees it, e.g. `http://audiomuse-ai-flask-app:8000`. Locks the field in the app. |
| `CODETTA_AUDIOMUSE_TOKEN` | set in the app | The `API_TOKEN` set on AudioMuse-AI (only needed when its sign-in is on). Saved tokens live in `audiomuse.json` in the config folder, readable by Codetta only, and are never sent back to the browser. |
| `CODETTA_LISTENBRAINZ` | chosen in the app | `on`/`off`: **ListenBrainz** for Autoplay: artists people listen to together. Sends the playing artist's MusicBrainz ID to api.listenbrainz.org. No account needed. |
| `CODETTA_LISTENBRAINZ_TOKEN` | set in the app | Your ListenBrainz user token, for scrobbling what you play (in Codetta and your music apps). Needs the ListenBrainz connection on. Saved tokens live in `listenbrainz.json` in the config folder, readable by Codetta only, and are never sent back to the browser. |
| `CODETTA_WIKIPEDIA` | chosen in the app | `on`/`off`: **Wikipedia artist bios** at the top of an artist's folder. Needs MusicBrainz on too: MusicBrainz names the artist's Wikidata item, and Codetta asks wikidata.org and wikipedia.org for that page. |
| `CODETTA_LYRICS_LOOKUP` | chosen in the app | `on`/`off`: **Find lyrics** in the editor. Pressing it asks [lrclib.net](https://lrclib.net) for that one track (artist, title, album and length only). |
| `CODETTA_UPDATE_CHECK` | chosen in the app | `on`/`off`: twice a day, ask GitHub whether a newer release exists. Nothing about you or your library is sent. |

Choices made in the app are saved in `connections.json` in the config folder.

The provided compose file also runs the container with a read-only system
filesystem and without the ability to gain extra privileges.

## Remote access and HTTPS

Codetta serves plain HTTP on port 8111. On your home network, or over
[Tailscale](https://tailscale.com/) (which already encrypts traffic between
your devices), that's fine.

**Don't expose Codetta directly to the internet.** If you want an `https://`
address:

- **Tailscale:** run `tailscale serve --bg 8111` on the server to get
  `https://<server>.<tailnet>.ts.net`, reachable only by your devices.
- **A reverse proxy** (Caddy, Traefik, nginx…): point it at port 8111. Codetta
  marks its session cookie `Secure` when the proxy sends
  `X-Forwarded-Proto: https`. A minimal Caddy example:

  ```
  codetta.example.com {
      reverse_proxy localhost:8111
  }
  ```
