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
No. Everything, fonts included, is served from your own server. The optional
update check is the only outgoing request, and you can turn it off.

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
- WAV, AIFF, WMA and raw `.aac` files aren't supported.
- Custom tag names (beyond Codetta's field list) only work in FLAC, Ogg and Opus files.
