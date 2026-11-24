[← README](../README.md)

# Listen in your music apps

Codetta can serve your library to music apps that speak the **Subsonic / OpenSubsonic API**,
the same one Navidrome serves: Symfonium, Narjo, Arpeggi, Feishin, DSub, Substreamer, Eclipse
and many more. They can browse, search and play your music, show covers and lyrics, and offer
"similar songs" (from [Autoplay](autoplay.md)). They can't change your files.

**Music app support is new.** Everything below works, but every app talks to servers a little
differently: if one misbehaves, please [open an issue](https://github.com/gavndev/codetta/issues)
saying which app and what happened.

Already run Navidrome? You don't need this: Navidrome is a full music server, and Codetta keeps
its tags right. This is for libraries that only have Codetta.

## Turn it on

1. In Codetta, open **Account → Connections** and switch on **Listen in your music apps** (or
   say yes in the setup step).
2. In your app, add a **Subsonic** (or **Navidrome**) server with:
   - **Server address:** the address you open Codetta at, e.g. `http://192.168.1.50:8111`
   - **Username:** your Codetta username
   - **Password:** the **app password** Codetta shows (never your Codetta password)

The app password only works for music apps. **Make a new password** signs every app out.

## What's included

| | |
|---|---|
| Browse | Artists, albums and songs (from your tags; albums with a MusicBrainz ID stay separate even when two share a name), or your folders |
| Search | Everything, including the full-library sync some apps do |
| Play | The original files with seeking, or converted to MP3, Opus or AAC when an app asks for a lower quality (see below) |
| Covers | Sized to what the app asks for (small thumbnails for lists), cached on the server; artist pictures for artists |
| Details | ReplayGain, MusicBrainz IDs, multiple artists, genres, release types, labels, original release dates, disc titles, credits, explicit flags |
| Stars, ratings, play counts | Kept in Codetta, so every app you connect sees the same ones; "most played", "recently played", "starred" and "top rated" lists |
| Playlists | Made in any app, kept in Codetta, shared by all your apps (never written into your music folder) |
| Play queue | Saved by one app, picked up by another (stop on your phone, carry on at your desk) |
| Bookmarks | For audiobooks and long mixes: where you left off |
| Lyrics | Plain and synced, from the file's tags or a `.lrc` file next to it |
| Similar songs and artists | From [Autoplay](autoplay.md)'s sources |
| Now playing | What each app is playing right now |

Songs keep their stars, plays and playlist places when Codetta moves them (Organize, the inbox,
Move to, Rename, and undoing any of those). A song moved some other way is found again by its
title, artist, album and length.

## Smaller files on mobile data

In most apps you can pick a lower quality for mobile data (often 128 or 192 kbps). When an app
asks for that, Codetta converts the song as it plays: MP3, Opus or AAC, whichever the app asks
for (or the format you choose on the Music apps card when it only asks for a bitrate). Nothing is
written to disk, and on Wi-Fi apps get the original files. Turn it off on the card to always send
the originals.

The Docker image and the snap include an ffmpeg that can do this. Running Codetta another way?
Install ffmpeg with MP3 (LAME), Opus or AAC encoding (most systems' ffmpeg has all three).

## Scrobbling to ListenBrainz

Turn on the **ListenBrainz** connection in Account → Connections and add your user token (from
[listenbrainz.org](https://listenbrainz.org/settings/)). What you play in your music apps and in
Codetta's own player is then added to your ListenBrainz listening history, which also makes its
recommendations (and Autoplay's) better. Plays that can't be sent right away are kept and sent
later.

## How it signs in

Apps sign in on every request with the app password: the classic Subsonic token (a salted MD5
hash), the password itself, or an OpenSubsonic API key. Wrong passwords are rate-limited like
Codetta's sign-in page. It's served at `/rest/` on Codetta's usual address, and nothing else
there opens without Codetta's own sign-in. Use HTTPS (or a private network like Tailscale) when
apps connect from outside your home.
