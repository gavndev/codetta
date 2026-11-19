# Privacy

Codetta is private by design. It runs on your own server, and your music, your
tags and what you do with them stay there.

## What Codetta never does

- **No tracking, no analytics, no telemetry.** Codetta doesn't count users,
  report crashes, collect usage statistics or "phone home". There is no code
  for it.
- **No ads, no accounts with us.** There is no Codetta company server to sign
  in to. The only account is the one on your own server.
- **Nothing from other sites in the page.** The web page loads only from your
  server: its fonts and icons are built in, and cover art fetched from the
  internet is passed through your server first. A strict Content Security
  Policy makes the browser refuse anything else.
- **No logs of what you do.** The Docker image runs without an access log.
  Sign-in sessions store the user name and when they expire, nothing about
  your device or address. Failed sign-ins are counted per address in memory
  only (to slow down password guessing) and forgotten on restart.

## Offline unless you opt in

Out of the box Codetta never connects to the internet. Online features are
*connections*, each off until you turn it on (on the first-run card or in
**Account → Connections**), each saying exactly what it sends:

| Connection | Sends | To |
|---|---|---|
| MusicBrainz | the album and artist names you search for, and the release IDs you pick | musicbrainz.org, coverartarchive.org |
| AcoustID | a fingerprint of each track's sound (a short code, never the audio) and its length, when you press Listen | api.acoustid.org |
| LRCLIB lyrics | a track's artist, title, album and length, when you press Find lyrics | lrclib.net |
| Soulseek (slskd) | your searches, to your own slskd (which asks other Soulseek users) | your slskd server |
| Update check | nothing about you: it asks GitHub for the latest version, twice a day | api.github.com |

`CODETTA_OFFLINE=on` blocks every connection, whatever else is set. Each
request names Codetta and its version as the user agent (MusicBrainz asks
apps to do this); nothing identifies you.

## Your data

Everything Codetta keeps lives in your config folder: your account (with a
scrypt-hashed password), sessions, the activity log, Tag Presets, the search
index, and the settings you choose. Delete the folder and it's gone.

## Security

See [SECURITY.md](SECURITY.md) for how Codetta protects your library: signed-in
access only, cross-site protection, size limits, safe writes and how to report
a problem.
