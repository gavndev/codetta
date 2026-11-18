[← Back to the README](../README.md)

# Features

Everything Codetta does, in detail.

## Search your whole library

Type in the search box and press <kbd>Enter</kbd> to search every track you
own. Search by tag, and combine as much as you like:

| Type | Finds |
|---|---|
| `genre: rap, hip-hop` | tracks whose genre is Rap **or** Hip-Hop (but not "Trap") |
| `artist: drake` | everything by Drake, including features ("Drake & Future") |
| `genre: rap year: 2024` | both at once |
| `night drive` | those words in the title, artist, album or file name |

It ignores case and accents ("beyonce" finds "Beyoncé"). Results work like a
folder, so you can select them and edit them all at once. You can also start a
search from the filter button: pick a tag and a value, then **Search library**.

<p align="center">
  <img src="media/search.gif" alt="Searching the library for genre synthwave or jazz, then for artist kosei, which finds Kōsei Mori" width="900">
</p>

## Fix a whole album in one go

Fill in the album details once, drop in a cover, and **Save to folder** applies
exactly those changes to every track. You see the full list of changes before
anything is written.

<p align="center">
  <img src="media/fix-an-album.gif" alt="Filling in album, album artist, date, genre and cover art on one track, then saving them to all five tracks in the folder" width="900">
</p>

## Turn loose downloads into proper releases

**Tag Loadouts** are saved sets of tags with placeholders like
`{filename_title}`, `{folder}` and `{track}/{tracktotal}`. Apply one to a file,
a selection or a folder, and loose downloads become properly tagged singles or
albums. You always get a preview first, and you choose whether to only fill
empty tags or overwrite them.

<p align="center">
  <img src="media/loadouts.gif" alt="Previewing the Single loadout on a folder of loose downloads, then applying it to five files" width="900">
</p>

## Undo anything

Every change lands in the activity log with its old and new values. Changed
your mind? Undo it right from the log, even across a whole album, and redo it
if you change it back. Files that were edited again since are left alone,
never overwritten.

<p align="center">
  <img src="media/undo.gif" alt="Changing the genre of ten tracks at once, then undoing all ten from the activity log" width="900">
</p>

## Made for your phone too

Codetta is designed for iPhone and Android as much as for desktop: big touch
targets, a full-screen editor sheet, **Select** mode like the Photos app, and
covers straight from your photo library (HEIC included).

<p align="center">
  <img src="media/phone.gif" alt="Opening an album on a phone, editing a genre and saving" width="260">
  &nbsp;
  <img src="screenshots/phone-album.png" alt="Album view on a phone" width="260">
  &nbsp;
  <img src="screenshots/phone-editor.png" alt="Track editor on a phone" width="260">
</p>

## And the rest

- **Edit one track or many.** Select several tracks and change only the fields
  you need. Fields that differ show as *Multiple values* and are left alone
  unless you touch them.
- **Smart suggestions.** Album-level fields suggest values the other tracks in
  the folder already use, and Track suggests the file's position (`2/6`).
- **Copy & paste tags** between tracks and folders.
- **Album art everywhere.** A thumbnail on every track, and covers you can
  add, replace or remove as part of a normal save.
- **Filter a folder by tag**, e.g. *Label: Independent*.
- **Fast on big libraries.** Folders load one at a time, and search uses a
  small index that Codetta keeps up to date in the background, so even tens
  of thousands of tracks stay quick.
- **Any language, any script.** Japanese, Hindi, Korean, Thai, Arabic, accented
  names and emoji are saved exactly as typed. Search ignores accents
  ("beyonce" finds "Beyoncé") and right-to-left names display correctly.
- **Light and dark themes** that follow your device, with smooth, subtle
  animations (off when your system asks for reduced motion).
- **Offline unless you opt in.** No CDNs, no tracking, fonts bundled. Online
  features (MusicBrainz, identify by sound, lyrics, the update check) stay off until you turn them
  on, and each one tells you exactly what it sends and where.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="screenshots/editor-dark.png">
    <img src="screenshots/editor-light.png" alt="Codetta's track editor next to an album" width="900">
  </picture>
</p>

## Match albums on MusicBrainz

Turn on the MusicBrainz connection, open an album folder and press **Find in
MusicBrainz**. Codetta lists the editions that fit (year, country, format,
label, catalog number, track count and a match score). Already-tagged albums
offer their own release first, and you can paste any musicbrainz.org release
link instead of searching.

Pick a release, and the review screen shows every file next to the track it was
paired with. Pairing uses disc and track numbers first, then title and length,
and flags anything that looks off. You can choose:

- **Which fields**: titles and numbering, credits (composer, lyricist,
  producer, engineer, mixer, arranger, conductor), release details (original
  date, type, status, country, label, catalog number, barcode, media), sort
  names, MusicBrainz IDs and ISRCs, and community genres (off by default).
- **Replace or only fill empty** tags.
- **Cover art** from the Cover Art Archive: where missing, replace all, or leave.
- **Which track each file gets**, or leave a file alone.

Each file shows its old → new values before anything is written, and the
whole match is one undoable entry in the activity log. Tags are stored the way
MusicBrainz Picard writes them.

**Untagged or mystery files?** Turn on the AcoustID connection and press
**Listen** in the match dialog. Codetta fingerprints each track on your server
(only that short code and the length go to [AcoustID](https://acoustid.org)),
finds the releases holding most of them, and pairs every file with its exact
recording, whatever its name or track number says.

Running your own MusicBrainz mirror? Point `CODETTA_MUSICBRAINZ_URL` at it and
lookups stay on your network with no rate limit.

## Lyrics

Plain or synced (LRC) lyrics, in a roomy editor box that tells you which kind
you have. **Find lyrics** looks the track up on [LRCLIB](https://lrclib.net), a
free, open lyrics database, and shows a preview; choose synced or plain, review,
then Save. Navidrome and most players read synced lyrics straight from the tag.

## Advanced mode

Turn on **Advanced mode** in the account menu to see a **Raw tags** section in
the editor: every field exactly as the file stores it (ID3 frames, MP4 atoms,
Vorbis comments, APEv2 items, WMA attributes and embedded pictures).

## Sorting and classical music

Sort names (title, artist, album, album artist, composer) and classical fields
(work, movement, movement number and count, show movement) are stored where
MusicBrainz Picard puts them, so players that understand them pick them up.

## How Codetta keeps your files safe

Your library matters, so Codetta is careful with it:

- **The original is never touched until the change is verified.** Each save
  goes to a temporary copy, which is read back to check that every tag landed
  correctly, then swapped in with a single atomic step. If anything goes wrong
  (a full disk, a crash, a power cut), the original file is left exactly as it
  was.
- **Nothing else changes.** Tags you didn't edit, embedded art, permissions
  and ownership are preserved. Symlinks are followed, not replaced, and
  hard-linked copies (say, a torrent that's still seeding) keep their
  original bytes.
- **Codetta only writes when you ask.** Browsing never modifies a file. Bulk
  actions ask you to confirm first, and everything can be undone.
- **It doesn't rename, move or delete files.** Only tags and embedded art
  change.
- **It's tested.** Over 500 automated tests cover every format, including
  corrupt, truncated and mislabelled files, every script and emoji, read-only
  folders, interrupted writes, simultaneous saves and attack attempts.

## Supported formats

| Format | Extensions | Tags | Custom tag names |
|---|---|---|---|
| FLAC | `.flac` | Vorbis comments | ✅ |
| Ogg Vorbis, Opus, Ogg FLAC, Speex | `.ogg` `.opus` `.oga` `.spx` | Vorbis comments | ✅ |
| WavPack | `.wv` | APEv2 | ✅ |
| WMA | `.wma` | ASF attributes | ✅ |
| MP3, MP2 | `.mp3` `.mp2` | ID3v2.4 | Codetta's field list |
| WAV, AIFF | `.wav` `.aif` `.aiff` `.aifc` | ID3v2.4 (as Picard and Navidrome use) | Codetta's field list |
| DSF (DSD) | `.dsf` | ID3v2.4 | Codetta's field list |
| TrueAudio | `.tta` | ID3v2.4 | Codetta's field list |
| AAC / ALAC, audiobooks | `.m4a` `.m4b` | MP4 atoms | Codetta's field list |

Every format supports album art and every field in the editor. Codetta detects
the real format from each file's contents, so a mislabelled file still opens
correctly. Monkey's Audio (`.ape`), Musepack (`.mpc`) and other APEv2 formats
are planned once we have sample files to test against.
