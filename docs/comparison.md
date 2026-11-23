[← README](../README.md)

# How Codetta compares

| | **Codetta** | [MusicBrainz Picard](https://picard.musicbrainz.org/) | [beets](https://beets.io/) | [Metadata Remote](https://github.com/wow-signal-dev/metadata-remote) |
|---|---|---|---|---|
| What it is | Web app on your server (or your own computer) | Desktop app | Command-line library manager | Web app on your server |
| Use it from your phone | ✅ Designed for it | ❌ | ❌ | ➖ Responsive layout |
| Runs in Docker | ✅ Official image | ➖ Community images | ➖ Community images | ✅ Official image |
| Built-in sign-in | ✅ | – (local app) | – (local app) | ❌ Use a reverse proxy |
| Edit tags by hand, one track or many | ✅ | ✅ | ➖ `beet modify` | ✅ |
| Album art | ✅ + Cover Art Archive | ✅ + Cover Art Archive | ✅ via plugin | ✅ |
| Match releases on MusicBrainz | ✅ Opt-in, incl. audio fingerprints, reviewed per file | ✅ Incl. audio fingerprints | ✅ Automatic on import | ➖ Suggestions |
| Import new music (match and file a downloads folder) | ✅ Inbox, reviewed or automatic | ❌ | ✅ `beet import` | ❌ |
| Rename / organize files | ✅ Pattern, preview, undo | ✅ | ✅ | ✅ Rename |
| Undo | ✅ Kept across restarts | ❌ | ❌ | ✅ Until restart |
| Search the whole library by tag | ✅ | ➖ | ✅ Query language | ➖ Filtering |
| Play tracks | ✅ In the browser | ➖ Basic player | ➖ Via external player | ✅ In the browser |
| Plugins | Not yet (built-in actions, plus opt-in connections) | ✅ | ✅ | ❌ |
| Formats | 18 file types | 20+ | Most common formats | 9 |
| License | AGPL-3.0 | GPL-2.0 | MIT | AGPL-3.0 |

✅ yes · ➖ partly or with extra setup · ❌ no

**Codetta takes your music from scattered files to a well-organized library in one place.** It covers the whole trip (import, match, fix, and file) right from your browser, and you can see and approve each step along the way. No terminal or desktop install is needed, and nothing changes without you seeing it first.

<sub>Compared in November 2026 from each project's documentation. Spotted something out of date? Please [open an issue](https://github.com/gavndev/codetta/issues).</sub>
