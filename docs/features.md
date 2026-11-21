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

While it's idle, the search box rolls through ideas from your own music
("Search genre: rap", "Search Frank Ocean"). Tap it for shortcuts (search by
artist, album or tag, each with an example from your library) and for
**Search elsewhere**.

<p align="center">
  <img src="media/search.webp" alt="The idle search bar rolling through ideas from the library, then searching for artist Frank Ocean and genre electronic" width="900">
</p>

### Bangs: search somewhere else from the same box

Start a search with a bang and the box turns into a coloured chip for that
service. Press <kbd>Enter</kbd> to search it:

- `!mb`: artists and releases on **MusicBrainz**, with the albums you already have marked.
- `!dz`: albums on **Deezer** (its search doesn't include release years; a small note says so).
- `!it`: albums on **iTunes** and Apple Music.
- `!slskd`: **Soulseek**, through your own slskd (see below).

Deezer and iTunes results mark what's already in your library and link to the
album there, or start a Find in slskd. Each bang only works when its connection
is switched on (Account → Connections), and only the words you type are sent.

<p align="center">
  <img src="media/bangs.webp" alt="Typing bangs in the search bar: the Deezer chip and its note about release years, Deezer and iTunes albums with the ones already in the library marked, then !mb for artists on MusicBrainz" width="900">
</p>

## Fix a whole album in one go

Fill in the album details once, drop in a cover, and **Save to folder** applies
exactly those changes to every track. You see the full list of changes before
anything is written.

<p align="center">
  <img src="media/fix-an-album.webp" alt="Adding a genre and cover art on one track of Vespertine, then saving them to all twelve tracks in the folder" width="900">
</p>

## Turn loose downloads into proper releases

**Tag Presets** are saved sets of tags with placeholders like
`{filename_title}`, `{folder}` and `{track}/{tracktotal}`. Apply one to a file,
a selection or a folder, and loose downloads become properly tagged singles or
albums. You always get a preview first, and you choose whether to only fill
empty tags or overwrite them.

<p align="center">
  <img src="media/presets.webp" alt="Previewing the Single preset on a folder of loose downloads, then applying it to five files" width="900">
</p>

## Undo anything

Every change lands in the activity log with its old and new values. Changed
your mind? Undo it right from the log, even across a whole album, and redo it
if you change it back. Files that were edited again since are left alone,
never overwritten.

<p align="center">
  <img src="media/undo.webp" alt="Changing the genre of ten tracks at once, then undoing all ten from the activity log" width="900">
</p>

## In your language

Codetta's page is in **English** and **Spanish**. It follows your browser's
language, and **Account → Language** picks one for that browser. Your music is
never translated: titles, artists and folder names show exactly as they are.
More languages are welcome: see [Translating Codetta](translating.md).

## Made for your phone too

Codetta is designed for iPhone and Android as much as for desktop: big touch
targets, a full-screen editor sheet, **Select** mode like the Photos app, and
covers straight from your photo library (HEIC included).

<p align="center">
  <img src="media/phone.webp" alt="Opening an album on a phone, editing a genre and saving" width="260">
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
- **Recently deleted.** Deleted files are kept for 30 days in your account
  menu, where you can restore them.
- **Report a problem** (in your account menu) gathers your version, setup and
  recent warnings into a GitHub issue for you to finish, so a bug report
  takes a minute. Nothing is sent until you open it on GitHub, and you can
  look it over first (log lines can include file and folder names).
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

**Editions.** An album can have dozens of editions (the original, remasters,
deluxe sets, CD, vinyl, digital, one per country). **Other editions** lists
them all so you can switch to the one that matches your copy. Under **Album
editions** in your account menu you choose which one Codetta prefers when it
matches on its own (in the inbox and Tidy up): the album's original year even
for a reissue, a format, a country, and the standard edition over deluxe ones
unless your files match. Preferences only reorder the choices; they never make
an uncertain match look certain.

**Loose songs** (a single download, a YouTube rip) are matched as songs, to the
album they came from. Junk like "(Official Audio)", "[Explicit]" or "ft. …" is
cleaned off before searching. If MusicBrainz is down or doesn't know an album
yet, Deezer and iTunes (optional connections, no account needed) step in with
details and big covers.

<p align="center">
  <img src="media/match.webp" alt="Matching Rumours on MusicBrainz, opening Other editions and switching to the recommended CD edition, with every change listed per file" width="900">
</p>

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

## Organize your files

**Organize…** renames and moves the files in a folder (or your selection) from
their tags, using a pattern such as

    {albumartist|artist}/{album}[ ({year})]/{disctrack} {title}

which gives `Kōsei Mori/Northern Signal (2021)/03 Harbour Lights.flac`
(`2-03` on multi-disc albums). `{a|b}` uses the first tag that has a value,
`[ … ]` disappears when a tag in it is empty, and `/` starts a folder. Pick a
starting pattern, tap tag buttons to build your own, and watch the live example.

You see every move before anything happens. Codetta never overwrites a file:
if a name is taken, that file is listed and left alone. Lyrics files
(`song.lrc`) follow their song, and when a whole album folder moves, its cover,
booklet, logs and scans come along. Folders left empty are removed. The whole
organize is one entry in the activity log, so **Undo** puts everything back.

## Batch tools

Every tool here works on a whole folder, your selection, or a page of search
results, shows every change before anything is written, and is one entry in
Activity that **Undo** reverses. On phones they're in the **…** menu.

- **Find & replace** in tags: "(Official Audio)" → nothing, "ft." → "feat.",
  in every text tag or just one. Turn on **Pattern** for regular expressions
  (`\d+`, and `(…)` with `\1` to keep parts).
- **Actions**: one-tap tidy-ups. Built in: **Clean up titles** (removes
  "(Official Video)", "[Explicit]", "(Lyrics)"…), **Write features as
  "feat."**, **Title Case** and **Trim spaces**.
- **Rename folder**: every file moves with it, nothing is overwritten.
- **Download as .zip**: the whole folder (subfolders, covers and lyrics files
  included) as one .zip, to back up an album or share it. Codetta builds the
  zip while it downloads, so nothing extra is written to your server, and big
  albums start downloading straight away.
- **Download** selected tracks: one track comes as it is, several come as one
  .zip (lyrics files included, folders kept as they are in your library).
- **Organize** (above) renames and moves many files and folders from their tags.
- **Edit** a selection of tracks (or **Save to folder**) to set the same tags on
  all of them, and **Tag Presets** to apply a saved set.

## Right-click (or long-press) menu

Right-click a track or folder on a computer, or press and hold it on a phone, for a
small menu of what you can do with just that item:

- **Rename** a file (its extension stays, and a lyrics file with the same name follows) or a folder.
- **Move to** another folder, picked from a short folder list.
- **Select** (starts a selection with that track), **Actions** on just that track.
- **Get info:** format, bit depth, sample rate, bitrate, size, tag type, cover size and where it is.
- **Download** (tracks): the file itself, tags and cover included. With several tracks
  selected, **Download as .zip** gets them all in one file.
- **Download as .zip** (folders): the folder and everything in it as one .zip file.
- **Find in MusicBrainz** and **Find in slskd** for that track or folder.
- **Delete**, after one confirmation. Nothing is erased: deleted files go to *Recently
  deleted* in Codetta's config folder for 30 days, and Activity can bring them back.

With several tracks selected, right-click one of them to move, run an action on, or delete them all.
Moves and renames never overwrite anything, and each one can be undone.

## Library health

A card at the top of the Library page says how many things are worth a look
("23 things to look at"). It opens one list, grouped by kind:

- **Shows up split in your player:** an album whose tracks spell the album
  name, album artist or year differently, or that has features but no album
  artist (so Navidrome shows one album as several).
- **Tracks:** missing tracks (gaps, or fewer than the album's track total),
  the same track number twice, a multi-disc album with tracks missing their
  disc number.
- **Covers:** no cover at all (embedded or a cover image in the folder), or
  one smaller than 500 pixels.
- **Tags & files:** tracks without a title, artist, album or track number, the
  same album in two folders, the same song twice, unreadable files, and lossy
  files (MP3, AAC) inside an otherwise lossless album.

Where the fix is obvious there's a button for it ("Use “Kehlani”" as the album
artist, "Number from file names", "Number from disc folders"). You see what
it will change first, and the whole fix is one entry in Activity, so one Undo
reverts it. Everything else has **Open**, and **Find in MusicBrainz** or
**Find in slskd** where they help. **Ignore** hides an issue you're happy
with, and **Checks** switches any check off (and back on).

It reads Codetta's search index, so no music file is opened and a library of
thousands of albums is checked in well under a second.

## Tidy up your library

Library health points things out; **Tidy up** fixes them for you, in the
background. Choose once (it's a setup step, and under **Tidy up** in your
account menu):

- **Leave my files alone:** Codetta won't change anything on its own.
- **Fix tags only:** each album is looked up and its tags fixed (names,
  artists, years, covers). File names and folders stay the same.
- **Fix tags, names and folders:** the tags, then files are renamed and each
  album moved with your Organize pattern. Before the first full run you see a
  preview of what the new names will look like.

It works through one album at a time, with a progress bar that shows when it
started, how far it's got and when it finished. It only writes an album when
it's sure of the match; the rest are listed for you to look at. Loose songs
are matched one by one, an album is never split across folders, and every
album is one entry in Activity, so it can be undone. Pause it any time.

<p align="center">
  <img src="media/tidy.webp" alt="Turning on Tidy up with tags, names and folders, previewing the new file names, then watching the progress bar work through the library" width="900">
</p>

## Import inbox

Point Codetta at the folder new music lands in (downloads, rips; mount it at
`/inbox`). It groups what's there into albums and loose songs, waits until
downloads have finished arriving, finds each on MusicBrainz (by tags, or by
sound with AcoustID) and files it into your library with your Organize
pattern. Confident matches can file themselves; the rest wait for a quick
review. Each item says what was found ("Ready", "Not sure", "Not found") and
whether you already have that album. Albums already in your library are never
overwritten, and **Remove** clears something you don't want.

**Import** music straight from your computer or phone with the Import button,
or drag files onto the page. They land in the inbox and take the same route.

<p align="center">
  <img src="media/inbox.webp" alt="The inbox with four downloaded songs matched to their albums, two already in the library, one not found, and Hyperballad filed into Björk/Post (1995)" width="900">
</p>

## Soulseek through slskd

If you run [slskd](https://github.com/slskd/slskd), turn on the **Soulseek
(slskd)** connection and give Codetta slskd's address and an API key. Then:

- type `!slskd` in the search bar: it turns into a little
  **slskd** chip, and whatever you type next (say `T-Pain Epiphany`) goes to
  Soulseek when you press Enter. `*` works as a wildcard for names Soulseek
  filters (`*-Pain Epiphany`). Backspace on an empty box turns the chip off.
- or press **Find in slskd** on an album: the search bar fills with the album
  artist and album (from the tags, or the folder names if it has none), ready
  to edit and send. A download found this way is an **upgrade**: importing it
  replaces the copy you have.

Codetta ranks every folder other users share by how well it matches, quality
(lossless first, then 320 kbps by default; or lossless only), free upload
slots, queue and speed, and downloads the best one into your inbox. If a
download fails or stalls, it moves on to the next. When it arrives, the
**Soulseek** sheet shows what came (format, tracks, who sent it, the
MusicBrainz match), and you choose: **Import**, **Blocklist & try next**
(deletes the download, never offers that folder again) or **Choose another**.
Turn off *Review each download* to let exact matches file themselves.

**Share a folder in slskd.** Soulseek is give-and-take: many users won't send
files to someone who shares nothing. Codetta checks and warns you if slskd
isn't sharing anything.

Replacing an album moves the old copy into Codetta's config folder
(`replaced/`), as its own entry in the activity log, so it can be undone. It's
kept there for 30 days (like "Recently Deleted"), then removed.

## Works with Lidarr

Lidarr finds and downloads albums; Codetta makes their tags right. Turn on the
**Lidarr** connection and Lidarr rescans its folders as soon as Codetta changes
something there, Codetta leaves file names to Lidarr while Lidarr's renaming is
on, and it warns you when a Lidarr setting would undo your fixes. See
[Using Codetta with Lidarr](lidarr.md).

## Works with your music server

Turn on the **Music server** connection for Navidrome (or any Subsonic
server), Jellyfin, Emby or Plex, and Codetta asks the server for a quick scan
a few seconds after it changes files, so edits show up in your player straight
away, network shares included. Jellyfin, Emby and Plex scan only their music
libraries. See [Using Codetta with your music server](media-servers.md).

## Listen

Every track has a play button at the end of its row. It streams the file
itself from your server (no conversion, nothing cached). Pressing play queues
the rest of the album (or of your search results) after it, and Codetta moves
on to the next track by itself. The now-playing pill at the bottom has play,
next and stop; lock-screen and headphone controls work too.

Tap the pill for the full player: a big cover, previous, play, next and
**shuffle**, then two tabs:

- **Up next:** what plays after this track. Tap one to jump to it, or take it
  out of the queue.
- **Lyrics:** synced lyrics (LRC) follow the song line by line, with the line
  being sung in the middle; tap a line to jump there. Plain lyrics show as
  they are. They come from the track's lyrics tag, or from a `.lrc` file with
  the same name next to it (as Navidrome reads them).

Formats your browser can't play (WMA, DSF, WavPack, TTA, Speex) don't get a
play button. Multi-disc albums show a **Disc 1**, **Disc 2** line between
discs (with the disc subtitle, if any), and pointing at a track shows its
number as "2/01".

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
- **Files only move when you ask.** Renaming, moving and deleting happen only
  through Organize, the inbox, Tidy up (if you turn on names and folders) or
  Delete, always with a preview first. Nothing is ever overwritten, and
  deleted files wait in **Recently deleted** for 30 days. Erasing them for
  good asks you to type how many files you're erasing.
- **It's tested.** Over 1,200 automated tests cover every format, including
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
