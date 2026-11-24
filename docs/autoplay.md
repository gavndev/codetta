# Autoplay

When an album or folder you're playing ends, Autoplay keeps the music going with songs
like it, **picked from your own library**. It never downloads or streams anything from
elsewhere: every suggestion is matched to a file you already have, and songs it can't
find in your library are simply skipped.

Turn it on or off with the **∞** button in the full player (tap the now-playing bar to
open it). It's on unless you turn it off, and the choice is remembered per browser. The
songs it adds appear under **Autoplay** in *Up next*, with what they're similar to and
which service picked them. Remove any of them with ×, like any queued song.

## Where the picks come from

Codetta asks these in order and uses the first that finds enough songs in your library:

| Source | What it knows | What it sends | Needs |
|---|---|---|---|
| **AudioMuse-AI** | Songs that *sound* alike: it has listened to your whole library | The playing song's title and artist, to your own AudioMuse-AI server | Your AudioMuse-AI server, connected in Settings → Listening |
| **ListenBrainz** | Artists people listen to together, and their best-known recordings | The playing artist's MusicBrainz ID, to api.listenbrainz.org | MusicBrainz IDs in your tags (Find in MusicBrainz adds them). No account |
| **Deezer** | Deezer's related artists | The playing artist's name, to api.deezer.com | Nothing. No account |
| **Your library** | The same artist's other albums, then the same genre | Nothing: works offline | Nothing |

Each online source is a connection: off until you switch it on (in the setup step or
Settings → Connections), and never used when Codetta is set to stay offline
(`CODETTA_OFFLINE`). Last.fm isn't offered: it no longer gives out free API keys.

To keep things varied, a batch never repeats a song you've played in this visit, plays
at most two songs by one artist, and never plays two songs from the same album in a row.

## Connecting AudioMuse-AI

[AudioMuse-AI](https://github.com/NeptuneHub/AudioMuse-AI) analyses your music through
your music server (Navidrome, Jellyfin and others). Once it has analysed your library:

1. In Codetta, open Settings → Listening and switch on **AudioMuse-AI**.
2. Enter its address as Codetta sees it, for example `http://192.168.1.50:8000`, or
   `http://audiomuse-ai-flask-app:8000` when both run on the same Docker network.
3. If AudioMuse-AI's sign-in is on, enter its API token: the `API_TOKEN` setting of the
   AudioMuse-AI container. Leave it empty when its sign-in is off.
4. Press **Save and test**.

AudioMuse-AI and Codetta find songs by title and artist, so they work best when both read
the same tags, which they do when your music server and Codetta share the music folder.
