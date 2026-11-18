[← Back to the README](../README.md)

# FAQ

**Does it work with Jellyfin, Plex or other players?**
Yes. Codetta writes standard tags that any player reads. It's tuned for
Navidrome's extra fields, but nothing about it is Navidrome-only.

**Does it rename or move my files?**
Only when you ask. Editing changes tags and embedded album art, nothing else.
**Organize** and the **inbox** do rename and move files, but you see every
move first, nothing is ever overwritten, and the activity log can undo it.

**Do I need slskd for Soulseek?**
Yes. Codetta doesn't speak the Soulseek protocol itself; it asks your own
[slskd](https://github.com/slskd/slskd) to search and download, over slskd's
API. Mount slskd's downloads folder into Codetta at `/inbox` so the downloads
arrive in the inbox, and share a folder in slskd: many Soulseek users won't
send files to someone who shares nothing.

**Is downloading from Soulseek OK?**
That's up to you and where you live. Soulseek is a peer-to-peer network, and
what you download (and share) is your responsibility. Codetta only automates
what you'd otherwise do in slskd's own web page.

**How do I search for a tag that isn't in the list?**
Any tag name in your files works, e.g. `catalognumber: ABC-123`, or a custom
tag like `vibe: chill`. Separate several values with commas to match any of them.

**Does it need internet access?**
No. Codetta is fully offline unless you opt in. Everything, fonts included, is
served from your own server. After you create your account, Codetta asks
whether to stay offline or turn on online features ("connections"):
**Match on MusicBrainz** (with cover art), **Identify by sound** (AcoustID),
**Find lyrics** (LRCLIB) and the **update check**. Each one says exactly what it sends and where. Change them
any time in **Account → Connections**, or lock them with environment variables;
`CODETTA_OFFLINE=on` blocks them all (see [Configuration](configuration.md)).

**How does Find in MusicBrainz work?**
Open an album folder and press **Find in MusicBrainz**. Codetta searches with
the album and artist already in your tags (or paste a release link from
musicbrainz.org) and lists the editions it finds, best fit first: year,
country, format, label and track count, with a match score. Pick one, and
Codetta pairs your files with its tracks by disc and track number, then by
title and length. You can change any pairing, choose which fields to write,
keep values you already have, and decide about cover art. Nothing is written
until you press **Write**, and the whole match can be undone from the activity
log. Tags are stored the way MusicBrainz Picard writes them, so Navidrome and
other players pick up the MusicBrainz IDs.

**Can it recognise untagged files by how they sound?**
Yes, with the **AcoustID** connection turned on (alongside MusicBrainz). In
**Find in MusicBrainz**, press **Listen**: Codetta makes a fingerprint of
each track on your server (a short code describing the sound, never the audio
itself) and asks AcoustID which recordings they are. Releases holding most of
your tracks come first, and each file is paired with its exact recording, so
wrong track numbers and missing titles don't matter. Tracks AcoustID doesn't
know are listed, and fall back to pairing by title and length. AcoustID is
free for non-commercial use.

**How do I add Codetta to my dashboard (Homepage, Homarr, Dashy…)?**
Codetta serves its icon in three versions, without needing sign-in, so any
dashboard can load it straight from your server:

| Icon | Use it on | Address |
|---|---|---|
| Full colour (teal square) | Any background | `http://your-server:8111/static/icons/codetta.png` |
| Light ("c." in white) | Dark dashboards | `http://your-server:8111/static/icons/codetta-light.png` |
| Dark ("c." in ink) | Light dashboards | `http://your-server:8111/static/icons/codetta-dark.png` |

Each also comes as `.svg` and `.webp`. They're in the repository under
`src/codetta/web/static/icons/` too. For example, in Homepage:

```yaml
- Codetta:
    icon: http://music-server:8111/static/icons/codetta.png
    href: http://music-server:8111
    description: Music tags
```

**Can several people use it?**
There's one account per Codetta instance for now. You can stay signed in on as
many devices as you like.

**My music app doesn't show the change yet.**
Most servers only notice changes on their next library scan. Start a scan in
your music app, or wait for the scheduled one.

**What if something goes wrong during a save?**
The original file is only replaced after the edited copy has been checked, so
an interrupted save leaves the original as it was. You can also undo any
change from the activity log.

## Known limitations

- One account per Codetta instance.
- Raw `.aac`, Monkey's Audio (`.ape`) and Musepack (`.mpc`) files aren't supported yet.
- Custom tag names (beyond Codetta's field list) work in FLAC, Ogg, Opus, WavPack and WMA files, not in ID3 or MP4 formats.
