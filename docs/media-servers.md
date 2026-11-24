[← Back to the README](../README.md)

# Using Codetta with your music server

Codetta writes standard tags, stored the way MusicBrainz Picard stores them, so
every player and server reads them: Navidrome and any Subsonic server (Gonic,
Airsonic-Advanced, Ampache), Jellyfin, Emby, Plex, and players that read
files straight from disk.

A server shows your edits only after it scans the library again. The **Music
server** connection asks for that scan for you.

## Connect your server

Open **Settings → Music apps & server** and turn on **Music server**. New installs (and
existing ones, once) are also asked "Which music server do you use?" during
setup.

| Server | Address | Signs in with |
|---|---|---|
| **Navidrome** and other Subsonic servers | the address you open it at, e.g. `http://navidrome:4533` | a username and password. Navidrome only lets **admin** users start scans. |
| **Jellyfin** | e.g. `http://jellyfin:8096` | an API key: Dashboard → API Keys → **+** |
| **Emby** | e.g. `http://emby:8096` | an API key: Settings → Advanced → API Keys |
| **Plex** | e.g. `http://plex:32400` | your Plex token (see below) |

Press **Save and test**. Codetta shows the server's name and version and which
music libraries it will scan.

### Finding your Plex token

In Plex Web, open any album, choose **⋯ → Get Info → View XML**. The address
of the page that opens ends in `X-Plex-Token=…`; that's your token.

## What the connection does

- **A quick scan after every change.** A few seconds after Codetta changes
  files (tags, covers, renames, moves, deletes, imports), it asks the server
  for a scan. A batch of edits means one scan, and Codetta asks at most once a
  minute. Servers re-read only the files that changed, so scans are quick.
- **Music only.** Jellyfin, Emby and Plex scan only their music libraries,
  never films or shows.
- **Scan now** in Settings → Music apps & server asks for a scan whenever you like.

Most servers notice changes by themselves when the music is on a local disk.
They don't on network shares (NFS, SMB), where changes never reach them, and
some servers only scan on a schedule. With the connection on, your edits show
up either way.

## How servers read Codetta's tags

Codetta's field list follows Navidrome's own tag list, and each field is
stored in each format the way Picard stores it, which is what Navidrome,
Jellyfin and Plex read:

- **Several artists**: `ARTISTS` and `ALBUMARTISTS` (a list), next to the
  display `ARTIST` and `ALBUMARTIST`. Navidrome shows each artist separately.
- **Credits** (composer, lyricist, producer, engineer, mixer, DJ mixer,
  remixer, arranger, conductor): on MP3 they go in ID3's involved-people
  frame, where Navidrome looks for them.
- **Release details**: release type, status, country, label, catalog number,
  barcode, media, original date, disc subtitle, compilation, explicit.
- **MusicBrainz IDs**: Navidrome uses the album ID to keep an album together,
  so fill it in on every track of an album (Find in MusicBrainz does).
- **Lyrics**: plain or synced (LRC) lyrics in the lyrics tag.
- **Covers**: embedded art, or `cover.jpg` in the album folder.

Library health's **Shows up split in your player** checks find what splits an
album in players: different album names, album artists or years across one
folder, or no album artist on an album full of features.

### Server settings worth checking

- **Plex**: tags win only with **Prefer local metadata** on (Settings → Agents
  for older servers; the music library's Advanced settings for newer ones).
  Otherwise Plex replaces titles and artists with its own.
- **Jellyfin and Emby**: turn off metadata downloaders that replace your tags,
  or set the music library to prefer embedded information.
- **Navidrome**: nothing to change. Its watcher picks up changes on local
  disks too; the connection covers network shares and the rest.

## Server settings (environment variables)

| Variable | What it does |
|---|---|
| `CODETTA_MEDIA_SERVER` | `on`/`off`: the Music server connection (locks the switch in the app). |
| `CODETTA_MEDIA_SERVER_KIND` | `subsonic` (Navidrome and other Subsonic servers), `jellyfin`, `emby` or `plex`. |
| `CODETTA_MEDIA_SERVER_URL` | The server's address as Codetta sees it, e.g. `http://navidrome:4533`. |
| `CODETTA_MEDIA_SERVER_USER` / `_PASSWORD` | For Subsonic servers. |
| `CODETTA_MEDIA_SERVER_TOKEN` | The Jellyfin/Emby API key or the Plex token. |

Each one set this way is locked in the app. What you type in the app is saved
in `mediaserver.json` in the config folder, readable by Codetta only, and is
never sent back to the browser. Subsonic servers get a token made from the
password, never the password itself (unless the server can't use tokens).
