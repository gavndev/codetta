# Changelog

All notable changes to Codetta. Versions follow [Semantic Versioning](https://semver.org/).

## 0.1.0 (unreleased)

First release.

- Edit tags on FLAC, MP3, M4A, OGG Vorbis and Opus files, one track or many at once.
- Navidrome / OpenSubsonic tag set (credits, mood, label, release type, multiple artists…), stored the way MusicBrainz Picard does.
- Save to folder, copy & paste tags, smart suggestions from the folder, and hints for dates and multi-value fields.
- Album art: add, replace or remove embedded covers.
- Tag Loadouts with placeholders and a preview before writing.
- Filter a folder by tag; folders as a list (default) or grid.
- Activity log of every change, with old and new values, and undo/redo straight from the log (files edited again since are left alone).
- Safe writes: temporary copy, verify, atomic swap; symlinks, hard links, permissions and cover art preserved.
- Sign-in with hashed passwords, 30-day sessions, lockout and password reset from the server.
- Version shown on the sign-in screen and account menu, with a check for new releases.
- Docker image that runs as your user, with a health check and read-only filesystem.
