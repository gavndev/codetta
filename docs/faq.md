[← Back to the README](../README.md)

# FAQ

**Does it work with Jellyfin, Plex or other players?**
Yes. Codetta writes standard tags that any player reads. It's tuned for
Navidrome's extra fields, but nothing about it is Navidrome-only.

**Does it rename or move my files?**
No. Only tags and embedded album art change. File names and folders stay as
they are.

**How do I search for a tag that isn't in the list?**
Any tag name in your files works, e.g. `catalognumber: ABC-123`, or a custom
tag like `vibe: chill`. Separate several values with commas to match any of them.

**Does it need internet access?**
No. Codetta is fully offline unless you opt in. Everything, fonts included, is
served from your own server. After you create your account, Codetta asks
whether to stay offline or turn on online features ("connections"):
**Match on MusicBrainz** (with cover art), **Find lyrics** (LRCLIB) and the
**update check**. Each one says exactly what it sends and where. Change them
any time in **Account → Connections**, or lock them with environment variables;
`CODETTA_OFFLINE=on` blocks them all (see [Configuration](configuration.md)).

**How does Match on MusicBrainz work?**
Open an album folder and press **Match on MusicBrainz…**. Codetta searches with
the album and artist already in your tags (or paste a release link from
musicbrainz.org) and lists the editions it finds, best fit first: year,
country, format, label and track count, with a match score. Pick one, and
Codetta pairs your files with its tracks by disc and track number, then by
title and length. You can change any pairing, choose which fields to write,
keep values you already have, and decide about cover art. Nothing is written
until you press **Write**, and the whole match can be undone from the activity
log. Tags are stored the way MusicBrainz Picard writes them, so Navidrome and
other players pick up the MusicBrainz IDs.

**Does Codetta identify songs by how they sound (AcoustID)?**
Not yet. Matching uses your existing tags, file order and track lengths. That
works for albums with at least a rough album/artist name. Completely untagged
files need a name typed into the search first.

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
