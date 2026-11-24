# Changelog

All notable changes to Codetta. Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- **Covers of every shape:** a Japanese CD with its obi, a cassette J-card, a long soundtrack sleeve. The album page now shows a cover at its own shape, and the folder grid, the player and the editor show the whole cover (over a soft blur of itself) instead of cropping it square.
- **Choose which cover when matching:** when the Cover Art Archive has more than one front for a release, such as with and without the obi, the MusicBrainz review shows them all under **Which cover** so you can pick the one written to your files.
- **Your music:** favourites, most played, recently played and your playlists, in the page (the heart in the top bar). They're the same ones your music apps see, so a song starred in Symfonium is a favourite here too. Select songs anywhere and use **Add to…** to add them to favourites or a playlist, or make a new one; rename, delete and take songs out of playlists right there.
- **A pill at the bottom of your phone:** Library, Your music and the inbox now sit in an iPhone-style bar at the bottom of the screen, so the top bar is no longer crowded. It steps aside while you select songs or edit.
- **Artist pages:** an artist's folder now opens with their picture, a short bio and similar artists, a little like Last.fm. Similar artists you have come first and open their folder. The bio is from Wikipedia, in your language when there's a page in it: turn on the new **Wikipedia artist bios** connection (it works with MusicBrainz, which points to the right page). Similar artists come from Deezer.
- **Open in Harmony:** for albums MusicBrainz doesn't have yet, the Find in MusicBrainz drop-down opens [Harmony](https://harmony.pulsewidth.org.uk/) with the album already looked up, by its barcode or its Deezer or iTunes page, ready to add to MusicBrainz.
- **Fix: you can type in the Soulseek search box while a search runs.** The window refreshes itself every couple of seconds while it works, and that used to empty the box (and close any open file list). Both now stay as they are.
- **Soulseek, more like slskd's own:** **View all files in the folder** shows every file a source has in that folder (a search only lists the ones that matched your words), tick boxes choose which tracks to download (the button says "Download 3 of 12"), and **Load more sources** shows the rest of what the search found instead of the first 8.
- **Fix: some windows couldn't be closed.** Save covers as files, Paste a tracklist, Tags from file names and ReplayGain ignored their X and Cancel buttons (only Escape worked). Every window now closes from its buttons or a click outside it.
- **Settings sits in the middle of big screens:** on a wide or ultrawide monitor, Settings opens as a centred window instead of stretching from edge to edge.
- **Tidier Settings:** each online service's switch now sits right above its own settings, and they're grouped by what they're for. ListenBrainz and AudioMuse-AI are under Listening, your music server (Navidrome, Jellyfin, Emby, Plex) is next to the music apps in **Music apps & server**, and Connections is split into tags, covers and lyrics; getting music; and Codetta itself.
- **Match album tags:** select the tracks that won't group with their album (a bonus track, a physical-only song) and press **Match album…**. They get the same album tags as the rest of the album, from what the folder's other tracks share or from one track you pick, while their own title, artist, numbers, lyrics and IDs stay. You see every change first, and Activity can undo it.
- **Compare tags:** select 2 to 4 tracks and press **Compare** to see their tags side by side. Codetta points out the album tags that differ, the ones that make players split an album.
- **Copy and paste in the selection bar:** Copy lets you pick which tags to copy (album tags are ticked for you), and Paste puts them on the tracks you select next. Every button in the bar now has a small icon, and on smaller screens the quieter ones show just the icon.
- **Wipe all tags:** a folder's **More** menu has a red **Wipe all tags**, which removes every tag from its tracks and keeps the audio and the cover. It asks twice, in the middle of the screen, and Activity can undo it.

## 0.14.0 (2026-11-24)

One Settings page for everything Codetta lets you change.

- **All settings in one place:** a new **Settings** page (person icon → Settings) has every setting Codetta has, in plain sections: General, Library, Inbox, Listening, Music apps, Connections and About. Search finds any setting by name, so the file naming pattern is one "naming" away. On a phone it works like your phone's own settings. The account menu is now just quick switches, and the Settings buttons in the inbox, Tidy up and Library health open the right part of the page.
- **New switch:** whether the inbox moves filed albums into your library or only tags them (Settings → Inbox).

## 0.13.1 (2026-11-24)

- **The snap is back up to date:** 0.13.0's snap couldn't be built, so snap installs now get everything from 0.13.0 (music apps in full, the "how sure Codetta must be" setting) with this release.

## 0.13.0 (2026-11-24)

Music apps in full: stars, ratings, play counts, playlists and your play queue are kept and shared by every app, songs convert for mobile data, covers come at the right size, and plays can be scrobbled to ListenBrainz. Plus a setting for how sure Codetta must be before filing on its own, and fixes from two careful reviews.

- **Music apps, the full set:** stars, ratings and play counts are now kept (and shared by every app you connect), with "most played", "recently played", "starred" and "top rated" lists; **playlists** made in any app are kept in Codetta; your **play queue** follows you from one app to another; **bookmarks** for audiobooks and long mixes; artist pictures and similar artists; and richer details apps can show (ReplayGain, MusicBrainz IDs, multiple artists, release types, labels, original dates, disc titles, credits).
- **Smaller files on mobile data:** when an app asks for a lower quality, Codetta converts songs to MP3, Opus or AAC as they play. The Docker image and the snap now include the encoders for it. Covers are sized to what the app asks for, so lists load quickly.
- **Scrobbling to ListenBrainz:** add your ListenBrainz token (Account → Connections → ListenBrainz) and what you play in your music apps and Codetta's own player is added to your listening history.
- **Choose how sure Codetta must be:** the inbox's automatic filing and Tidy up can work with **Strict** (85% match, as before), **Balanced** (75%) or **Relaxed** (65%) matches, set in either place. Whatever the level, every track still has to line up with the album before anything is written, and everything can be undone in Activity. Handy for working through a big library with little to review.
- **Fixes for music apps:** apps that send form posts work, folder browsing can go back up from a top-level folder, web players hosted on other sites can connect, an app's "scan library" button really rescans, and albums with a MusicBrainz ID no longer merge with another album of the same name.
- **Safer picture links for music apps:** artist and album picture links carry a signature that opens only that picture, never your app password, and follow HTTPS behind a reverse proxy. Stars and play counts can't be overwritten when the same song shows up twice (say, a re-download in the inbox); they're added together instead.
- **Other fixes:** turning Autoplay off while it's finding songs no longer queues them anyway; a busy Deezer no longer leaves artists without their picture for a week; a damaged cached artist picture can no longer hang the page; artist folders whose names start with "@" get their pictures and links; and the Docker image's clean-up of tools it doesn't need works again.

## 0.12.0 (2026-11-24)

Listen in your music apps: Symfonium, Narjo, Arpeggi, Feishin, Eclipse and other Subsonic apps can now play your library straight from Codetta.

- **Listen in your music apps:** Codetta can now serve your library over the Subsonic / OpenSubsonic API, so Symfonium, Narjo, Arpeggi, Feishin, DSub, Eclipse and other Subsonic apps can browse, search and play it, with covers, lyrics and similar songs. It's off until you switch it on (Account → Connections, or the new setup step), apps sign in with their own app password, and they can't change your files. See [Listen in your music apps](docs/music-apps.md).

## 0.11.2 (2026-11-23)

Two fixes from your reports: folders whose names start with "@", and an Inbox that could get stuck loading.

- **Folders whose names start with "@" work** ([#5](https://github.com/gavndev/codetta/issues/5)): a folder like `@` or `@Live Sets` at the top of your music folder used to stop the whole library from showing ("Unknown folder: @"). Only Codetta's own areas (the inbox and Recently deleted) are special now, and NAS system folders like Synology's `@eaDir` and `#recycle` are skipped like hidden ones. Thanks to u/Business_Ad_5983 on Reddit for finding it.
- **The Inbox always opens** ([#4](https://github.com/gavndev/codetta/issues/4)): an album filed with another edition than the one Codetta suggested was saved with only its ID, and the Inbox screen then got stuck on "Looking in your inbox…". The full edition details are kept now, an entry with missing details still shows, and one entry that can't be drawn no longer hides the rest. Thanks to BernoldM for tracking it down to the exact line.

## 0.11.1 (2026-11-23)

A tidier Find in MusicBrainz button.

- **A cleaner Find in MusicBrainz button:** its gradient edge no longer clips the inside at the corners, and the ∨ part fills the whole height (it was shorter on phones). Easier to tap on phones too.

## 0.11.0 (2026-11-23)

Autoplay: when an album ends, similar songs from your own library keep playing, picked by your AudioMuse-AI server, ListenBrainz or Deezer. Plus tappable artist names with artist pictures, tidier folder buttons, file names at a glance, and a Library health check that tells a real duplicate from a namesake.

- **Tidier folder buttons:** on computers a folder now shows **Apply preset**, **Organize** and **Find & replace** with their names, and everything else in a **More** menu sorted into *Fix tags* and *Folder*. Phones keep one "…" menu, with the same groups.
- **File names at a glance:** each track shows its file name in small italics under its title (and under the artist on phones).
- **Tap an artist's name** in an album's header, the Artist column or the player to go to that artist: their folder when there is one, otherwise every song they're on. When the credit names several (“Justice & Michael McDonald”, “Yung Lean, Metro Boomin & Future”, “X feat. Y”), a menu lists them all with their pictures. Names that contain an “&” or a comma, like “Simon & Garfunkel” or “Tyler, The Creator”, stay whole.
- **Artist pictures** next to the artist in an album's header and the player, and in the artist menu: an `artist.jpg` in the artist's folder (as Navidrome, Jellyfin and Kodi use), or the artist's picture from Deezer while that connection is on (downloaded once and kept on your server). Without either, the artist's initials.
- **Autoplay:** when an album or folder ends, similar songs from your own library keep playing, listed under **Autoplay** in the player's *Up next*. Turn it on or off with the new ∞ button in the player. Picks come from your own **AudioMuse-AI** server (songs that sound alike), **ListenBrainz** (artists people listen to together, no account) or **Deezer** when you connect them in Account → Connections, and from your library alone when you don't: same artist, then same genre. It only ever plays music you already have. A setup step introduces it. See [Autoplay](docs/autoplay.md).
- **Library health knows a duplicate from a namesake:** "Same song twice" now compares the audio itself in FLAC files. Two tracks with identical audio are flagged even when their titles differ (a download with one remix twice under two names), and the message says one is probably the wrong file. Two versions that only share a name, like a remix with a different guest, are no longer flagged. An MP3 next to its FLAC is still caught.

## 0.10.0 (2026-11-22)

Discogs as a fourth album source, a set of tag tools (change case, fix garbled text, split and join values, tags from file names, paste a tracklist), covers saved as files for Plex and Jellyfin, and three more formats: Monkey's Audio, Musepack and DSDIFF.

- **Discogs:** a fourth album source next to MusicBrainz, Deezer and iTunes, and the one for vinyl, electronic music, white labels and regional pressings. Use **Find in Discogs** (the chevron next to Find in MusicBrainz), type `!dg` in the search bar, or paste a Discogs release or album link into the Find dialog. It brings the label, catalogue number, barcode, country, format, year, styles and per-track credits (producer, mixer, engineer, composer, lyricist, arranger, remixer), with the usual review before anything is written. Pasting a link works as it is; searching needs a free Discogs token, added in Account → Connections → Discogs (it stays on your server and is never shown again).
- **Three more formats:** Monkey's Audio (`.ape`), Musepack (`.mpc`) and DSDIFF (`.dff`, the other DSD format next to `.dsf`), with tags, covers, matching, Organize, ReplayGain and everything else, for 18 file types in all. The Docker image's ffmpeg reads them too.
- **A clearer reason for one odd genre:** MP3, WAV, AIFF and other ID3 files can't store a genre starting with “((” or a bracketed number like “(1)Rock” (ID3 reads those as its old numbered genres). Codetta already refused to save them so nothing changed; now it says why.
- **Save covers as files:** saves each album's embedded cover as `cover.jpg` (or `folder.jpg` / `front.jpg`) in its folder, for Plex, Jellyfin, Kodi and other apps that look for an image file. A PNG cover stays PNG, disc folders count as part of their album, an image of that name already there is kept unless you choose to replace it, and Activity can undo it, putting a replaced file back exactly as it was. In a folder's tools and the folder right-click menu.
- **Paste a tracklist:** copy a tracklist from Discogs, Bandcamp, Wikipedia or a text file and Codetta fills in the titles (and track numbers, discs and artists when the list has them), pairing each line with a file by number or in order. It reads vinyl sides (A1, B2), "Disc 2" headings, "1-03" positions, Wikipedia's quoted titles and Discogs' artist column, works out when lines start with the artist, and skips header rows and totals without catching songs called "Time" or "Total Eclipse of the Heart". When the counts differ or a pair's lengths are far apart, it says so before anything is written. In a folder's tools, the right-click menu and the selection's … menu.
- **Tags from file names:** for downloads with good names and empty tags. Describe how the files are named (`{track} - {artist} - {title}`, or `{artist}/{album} ({year})/{track} - {title}` to read the folders too) and Codetta fills in the tags. It suggests the pattern that fits your files best, shows every change first, keeps tags that already have a value (unless you say otherwise), can treat underscores as spaces, and leaves alone any file that doesn't fit. In a folder's tools, the selection's … menu and the right-click menu.
- **Translations pick the right sentence:** a Spanish message that starts like a shorter one is no longer half-translated.
- **New Actions (Tag tools):** **Change case** (UPPER, lower, Title or Sentence case, on titles, artists, albums, genres or every text tag), **Fix garbled text** (“BeyoncÃ©” → “Beyoncé”, plus Cyrillic, Japanese, Chinese and Korean from old Windows rips; only clear cases change, correct names are left alone), **Split into separate values** and **Join into one value** (“Rock; Pop” ↔ two genres, with the separator you pick), **Remove duplicate values**, and **Keep only the essentials** (removes leftover tags; covers, lyrics and ReplayGain always stay). Like every Action, you see each change first and Activity can undo it.
- **Actions can ask for choices:** some Actions now show a dropdown or two (which tags, which case, which separator), and the preview updates as you change them. Plugins can use this too.
- **Choose the iTunes store:** Account → Album editions has an **iTunes store** setting, for when the store you want to search isn't your preferred edition country. It follows the preferred country by default, and falls back to the US store when the chosen one has nothing. (The rest of [#3](https://github.com/gavndev/codetta/issues/3)'s suggestions arrived in 0.9.6.)
- **Paste an iTunes ID:** besides Apple Music, Deezer and MusicBrainz links, the Find dialog's paste box takes a bare iTunes collection ID (`296393419` or `id296393419`).
- **Spanish:** sentences that count things ("1 pista de 5 cambiaría", "3 archivos no tienen etiqueta…") are now grammatical, with no English words left in them, and the summaries in Find, Tag Presets and Organize are translated in full.
- **Off really means off:** with a connection switched off, or `CODETTA_OFFLINE` on, saving or testing slskd, Lidarr, music server or Discogs settings no longer contacts them. A new test checks that no route reaches the network while connections are off.
- **Clearer Activity entries:** bulk changes (Tag tools, Find & replace, Paste a tracklist, Tags from file names, ReplayGain) now show the values before and after in plain words, instead of things like `None` or `['Rock']`.
- **Errors name files the way you see them:** a failed save says `Artist/Album/01.flac`, not the server's own `/music/...` path.

## 0.9.6 (2026-11-22)

ReplayGain: one volume for every album, measured the EBU R128 way. Plus Find in iTunes that finds the right album, and a sweep for leaks and weak spots.

- **Find in iTunes finds the right album** ([#3](https://github.com/gavndev/codetta/issues/3)): Apple's search stumbles on names like "M.I.A." and fell back to popular albums, so looking for *Kala* showed Fleetwood Mac and Mariah Carey. Codetta now finds the artist first and looks through their albums, and only shows albums that really match: other artists' albums that just share the title stay out when the artist's own is found. Find in Deezer got the same treatment. Thanks to BernoldM for the detailed report.
- **iTunes uses your country's store:** with a preferred edition country set (Account → Album editions), iTunes is searched in that country's store, where some albums only exist, and falls back to the US store.
- **Paste an Apple Music or Deezer link** in Find in MusicBrainz's "Or paste a release link" box to go straight to that album.
- **Search right after an edit** never shows the old tags any more (a rare race when the background indexer was saving the change at the same moment).

- **ReplayGain:** even out the volume, so a quiet album and a loud one play at the same level in Navidrome, Plex, Jellyfin and most players. Open **ReplayGain** on a folder (or right-click a folder or tracks): Codetta measures each track's loudness the EBU R128 way (ReplayGain 2.0), shows the gain every track and album gets, and writes the tags only when you say so. **As albums** keeps an album's quiet and loud songs as the artist meant; **Each track on its own** levels everything. Opus files get the R128 tags Opus players read, and it can all be undone in Activity. The Docker image and the snap now include a small ffmpeg for it; other installs need ffmpeg installed.
- **ReplayGain tags on MP3 and M4A** are now saved where players read them (TXXX and iTunes-style tags, as Picard writes them), not in the old RVA2 frame few players understand.

## 0.9.5 (2026-11-21)

Codetta speaks Spanish, and tracks download one at a time or many as a .zip.

- **Codetta speaks Spanish:** the whole page (menus, dialogs, messages, the setup steps and the server's own messages) is now in Spanish for browsers set to Spanish, and **Account → Language** picks English or Español for each browser. Your music is never translated: titles, artists and folder names always show as they are. Want Codetta in your language? See [Translating Codetta](docs/translating.md).
- **Download tracks:** right-click (or long-press) a track and choose **Download** to get the file itself, tags and cover included. Select several tracks and press **Download** in the selection bar (or the … menu on phones) to get them as one .zip, with their lyrics files and the album's folder layout kept.
- **Phone menus stay on screen:** the selection bar's … menu now opens upwards instead of below the bottom of the screen.

## 0.9.4 (2026-11-21)

Works with your stack: Lidarr and your music server (Navidrome or any Subsonic server, Jellyfin, Emby, Plex) now hear about Codetta's changes straight away. Plus folders as a .zip, cleaner MusicBrainz results and two tag fixes for players.

- **Download a folder as a .zip:** right-click (or long-press) a folder, or use the new download button on a folder's page, to get the folder and everything in it (subfolders, covers, lyrics) as one .zip. It's built while it downloads, so nothing extra is saved on your server and big albums start right away.
- **Works with your music server:** a new Music server connection (Account → Connections, and a setup step) for Navidrome and any Subsonic server, Jellyfin, Emby and Plex. A few seconds after Codetta changes files, the server gets a quick scan, so your edits show up in your player straight away, even on network shares where servers don't notice changes by themselves. Jellyfin, Emby and Plex scan only their music libraries, and **Scan now** asks for one whenever you like.
- **Credits land where players look:** on MP3, the arranger was saved where Navidrome and Picard read the remixer. It now goes with the other credits, and there's a new **Remixer** field (filled in by Find in MusicBrainz too). Arrangers saved by older versions show up as remixers; move them back if needed.
- **Release country on M4A** is saved under the name Picard uses and Navidrome reads. Files saved by older versions still read fine and switch over on their next save.
- **Works with Lidarr:** a new Lidarr connection (Account → Connections, and a setup step) keeps the two in step. After Codetta changes files in Lidarr's folders, Lidarr rescans them straight away, so nothing looks missing or gets downloaded twice. While Lidarr's renaming is on, Organize and Tidy up leave its file names alone and fix tags only. Codetta also warns when Lidarr is set to rewrite tags on all files, which would undo your fixes. Codetta finds Lidarr's folders by itself, even when the two apps call the music folder different things.
- **Plugins are paused:** Codetta no longer loads plugins from `config/plugins/`, and Account → Plugins is gone, until the plugin system can do more. The built-in actions (Remove "feat.", Title Case, Trim spaces) work as before.
- **Cleaner MusicBrainz results:** an artist's page in `!mb` now lists what MusicBrainz's own page does, leaving out release groups made only of bootlegs, promos or fan uploads (fake covers, slowed remixes, stray singles). Search results drop bootleg-only releases too.
- **Easier to read Deezer chip:** the pink end of the Deezer bang chip is a little deeper, so its white text stands out clearly.

## 0.9.3 (2026-11-21)

More than MusicBrainz: search and match with Deezer and iTunes too. Plus a measured efficiency pass, so saving, undo and matching are faster on real disks.

- **Find in Deezer and Find in iTunes:** the Find in MusicBrainz button has a chevron (when Deezer or iTunes is on) that searches just that service, with the same review before anything is written. Handy when MusicBrainz doesn't have an album, or has it with less detail.
- **Bang chips for Deezer and iTunes** look like MusicBrainz's and slskd's: their own colours, with a white mark next to the name. `!dz` also shows a small note that Deezer's search doesn't include release years.
- **Tidy up: Run again** goes through your whole library once more (dismissed albums stay dismissed), and the "Need you" list has a clear heading with a count.
- **A tidier account sheet:** settings are grouped into Library, Online and Account & help, instead of a long run of separate rows.
- **Search Deezer and iTunes from the search bar:** type `!dz` or `!it` and an artist or album. Results show each album's cover, year and track count, mark the ones already in your library, and link to Deezer or Apple Music (or Find in slskd). Each needs its connection switched on.
- **Faster, lighter saving:** matching an album writes each file's tags and cover in one safe write instead of two, and saves an album's files a few at once, so the inbox, Tidy up and Find in MusicBrainz copy half as much and finish sooner on big FLACs. Undo is about three times faster, and batch edits about a quarter faster on real disks. Every file is still synced to disk before it replaces the original.
- **Imports no longer hold up the rest of Codetta:** while a big file is saved, other screens stay responsive.
- **Quicker start-up over the network:** the page asks for all its pieces at once instead of one after another.

## 0.9.2 (2026-11-20)

Quick wins from using the beta: ways to clear lists you're done with, a New folder button, and covers for brand-new releases.

- **New folder:** make a folder from any folder's tools (on phones, under More), or right inside **Move to**, so you can make a folder and move things into it in one go. Activity can undo it while it's still empty.
- **Inbox: Dismiss and Dismiss all** take filed albums off the list. The albums stay in your library; nothing on disk changes.
- **Tidy up: Dismiss and Dismiss all** for albums that need you. A dismissed album is left alone for good (even if you change what Tidy up does) and waits under Dismissed, where Show again brings it back.
- **Library health: Ignore all** ignores every issue on the list you're looking at (all of them, or one kind).
- **Covers in the match review and the inbox:** when MusicBrainz has no cover for a release yet (new releases often don't), Codetta uses the album's other editions, then Deezer or iTunes when they're on, then the cover already in your files.

## 0.9.1 (2026-11-20)

A round of fixes for the beta, most importantly for albums stuck on "Still arriving" in the inbox, and safer updates from here on.

- **Fixed:** an album in the inbox could stay "Still arriving" for ever, even with slskd showing the download at 100%. Codetta judged only by file times, and some setups keep those looking fresh (or put them in the future). Now an album has arrived as soon as slskd says every file is done, or once its files have stayed exactly the same for two minutes, and times in the future are ignored.
- **Fixed:** Tidy up never filed a folder of loose songs (a Downloads folder, say). It matched each song to its album, then refused to move them because they'd land in different folders, a rule meant for albums. Loose songs now go to their own albums, and songs that share an album still never split.
- **Fixed:** Organize, Tidy up and the inbox could put a song next to the same song in another format ("02 Dreams.mp3" beside the album's "02 Dreams.flac"). That file now stays where it is, with the reason, even when the two are numbered differently.
- **Fixed:** with the default settings, a song could be matched to a CD-R edition (usually a promo or bootleg), like "nights" on a CD-R of Blond. CD-R-only editions are now never preferred over a real release.
- **Polish:** sheets have the same breathing room between their message and what follows (Album editions and Report a problem were cramped on phones), Recently deleted has one Done button instead of Close and Done, and Report a problem names the install type plainly (Docker, snap, pipx, pip or a source checkout).
- **Tidy up:** when an album isn't moved because its songs would land in different folders, the note now names those folders (for example "Rumours (1977)" and "Rumours (2004 Remaster) (1977)"), so the odd song out is easy to find.
- **Fixed:** importing a file with a very long name cut off its extension, so it no longer counted as music. Long names are now shortened before the extension.
- **Fixed:** after an import, files that stayed in the Imported folder were always said to have "not enough tags", even when the real reason was that the same song is already in your library. The message now gives the right reason.
- **Import:** files over 2 GB are skipped up front with a clear message, and a dropped connection says so instead of "Failed to fetch".
- **Fixed:** renaming a folder or file to a blank name (just spaces or dots) quietly named it "_". Codetta now asks for a name.
- **Fixed:** the inbox and the !mb explorer shared one cache by mistake, so after the inbox had looked at 500 albums, the next !mb search could fail.
- **Clearer message for numbered genres in MP3, AIFF and WAV:** these formats read a genre that's only a number as one of the old numbered genres ("0" is Blues), so Codetta refuses to save it and now says why, instead of a puzzling "didn't save correctly".
- **Safer updates:** the config folder now records which settings layout it's in. When an update needs to change your settings, Codetta copies them into `backups/` in the config folder first (the last three are kept), and if anything goes wrong it puts them back and says so instead of starting with half-changed settings. Going back to an older version no longer risks your settings: Codetta leaves settings from a newer version untouched and shows a notice.

## 0.9.0 (2026-11-20)

Codetta is now in **beta**.

- **Already in your library:** albums in the inbox that you already have (the same release, or the same album and artist) get a label that opens the copy you have, so a duplicate download is easy to spot and remove.
- **Remove from the inbox:** any album in the inbox can be removed (its files go to Recently deleted), so leftovers never need a trip to the server.
- **Recently deleted** (account menu): see what you deleted, how big it is and how long it's kept, then **Put back** (never over a file that took its place) or **Delete now**. Deleting for good is the one thing that can't be undone, so you type the number of files to confirm; it's also checked on the server and can only ever touch Recently deleted.
- **Import music:** an Import button in the Inbox (and drag-and-drop anywhere on a computer) adds files or whole folders from your computer or phone. They go to your inbox to be matched and filed like any new music, or, without an inbox, to "Imported" in your library, placed with your folder pattern. Files that aren't music get a warning, not a refusal. Big files stream straight to disk, nothing is ever overwritten, and Activity can undo the whole import.
- **Inbox:** a green or red line under the inbox folder says whether Codetta can see it, and where to send new music.
- **Album editions:** a new setting (account menu → Album editions) for which edition Codetta picks when it matches on its own: the album's **original year** (on by default, so a 2011 reissue of a 1977 album is filed as 1977), a preferred format (digital, CD, vinyl) and country, and the standard edition over deluxe ones. When you match an album yourself, **Other editions** lists every edition of it, with the one your settings like best marked Recommended.
- **Tidy up shows you first:** before the first "Fix tags, names and folders" run, you see how a few of your albums would be renamed and moved, and choose Start or Not yet.
- **Report a problem** (account menu): the details a bug report needs (version, how it's installed, recent warnings), ready to copy, and a GitHub issue that opens filled in.
- **Search, with some flair:** while it's idle, the search bar rolls through ideas from your own library ("Search genre: rock", "Search Frank Ocean", "Search album: Blonde"), and goes back to normal the moment you tap it. Tapping it now also offers **Search your library**: artist, album or tag, each with a real example from your music, next to "Search elsewhere" (MusicBrainz, Soulseek).
- **Better matches for single songs:** a loose song with no album tag (a single download, a YouTube rip) is now looked up as a song, with junk like "(Official Audio)", "[Explicit]" or "ft. …" cleaned off, and matched to the album it originally came from (the first edition, not a compilation, live recording or reissue). A song is only filed by itself when it fits closely.
- **Tidy up:** a new setup step (shown once to everyone) asks how Codetta should look after the music you already have: leave it as it is, fix tags only (names stay), or tags plus file names and folders. Codetta then works through your albums one at a time in the background, writes only confident matches, renames only after a confident match, and lists the rest under "needs a look". Every album is its own undoable change. A card on the Library page shows a progress bar and when it started and finished, with Pause, Resume and Change (also in the account menu). It never splits an album across folders, and folders of loose songs are matched song by song.
- **Safer file names in Organize and the inbox:** stand-in tags like "[unknown]", "Unknown" or "Untitled" no longer become names; a file with no title keeps its own name (no more "03 03 - Song"); and a file with no artist or album tags at all stays where it is (marked in the preview) instead of landing in "Unknown Artist / Unknown Album".
- **Deezer and iTunes as album sources:** two new opt-in connections (no account needed) for album details and big covers. They step in when MusicBrainz is off, down, or has nothing that fits (new releases often reach Deezer and iTunes first), in the same Find screen with the same per-file review and undo, and the inbox uses them too. Covers the Cover Art Archive doesn't have now come from them as well. Only the album and artist names you search for are sent, and nothing from them is written as a MusicBrainz ID.
- **Soulseek: pick the source first.** After a search, Codetta lists the best sources with who's sharing, a free slot or their queue, their speed, the quality and every file, and waits for you to choose. Switch it off in Soulseek's settings to let the best source download by itself.
- **Soulseek: lighter on slskd.** One request checks every download at once (instead of one per download), the same search twice shares one request, and if slskd stops answering Codetta waits a little longer each time instead of asking again and again.
- **Soulseek: no more half albums in the inbox.** When a download gives up on one source and moves to another, or you cancel it, the files that already arrived go to Recently deleted instead of staying behind as a second, partial album. Blocklisting a download also sets its files aside there instead of erasing them.
- **Fixed:** a loose song could land on an odd edition of the right album (Björk's "Hyperballad" on a DualDisc's DVD side instead of the CD), because a song search only shows a few editions of each album. Codetta now looks through all of the album's editions for the one your settings prefer that has your song at your file's length. Video-only editions (DVD-Video, Blu-ray, VHS) are no longer preferred, and preferring CDs no longer picks a promo CD-R.
- **Fixed:** in the match screen, a file marked "check this" was squeezed onto one line with its note; the note now sits under the file, in orange.
- **Inbox:** the count at the top says "4 songs" or "2 albums and 3 songs" instead of calling every loose song an album.
- **Fixed:** matching on MusicBrainz could rename real songs to "[unknown]". MusicBrainz lists songs it doesn't know yet (often unreleased tracks on a new soundtrack) as "[unknown]" by "[unknown]", and Codetta copied that over the file's own title and artist. Those placeholders are now ignored, so the file keeps its real names.

## 0.8.5 (2026-11-19)

- **Right-click menu (long press on phones):** for any track or folder: Rename, Move to, Select, Actions, Get info, Find in MusicBrainz, Find in slskd and Delete. It's small and quick, opens right where you clicked, and works on a selection too.
  - **Get info** shows what the tags don't: format, bit depth, sample rate, bitrate, file size, tag type, cover size and location.
  - **Delete** asks once, then moves things to *Recently deleted* for 30 days instead of erasing them, and Activity can bring them back.
  - The MusicBrainz and slskd entries keep their colours.
  - **Move to** and **Rename** work like Organize: nothing is ever overwritten, lyrics files follow their song, and one tap undoes it.
- **Advanced mode, deeper:** switch it on in the account menu for a closer look at your files.
  - Every field in the editor shows how this file actually stores it, in a code font: `TPE1` in an MP3, `©ART` in an M4A, `ARTIST` in a FLAC, or "not in WMA" when the format can't hold it.
  - **Get info** adds the encoder, how many of Codetta's fields the format can store, and the file's full location on the server.
  - **Server log:** a live view of Codetta's own log (what `docker logs` shows) at the bottom of the account menu. It's kept in memory only, only you can see it, it never includes who visited, and anything that looks like a key or password is masked.
- **Fixed:** the raw tag view in Advanced mode failed on M4A files marked as a compilation, and showed production credits in MP3s as unreadable code.
- **Privacy:** a failed sign-in no longer writes the typed username to the log (people sometimes type their password there by mistake).
- **Explicit and Clean presets:** mark a folder or a selection as explicit or clean in one go. They set the advisory tag Navidrome and Apple Music read (1 = explicit, 2 = clean), in every format, including Apple's own field in M4A files. The tag also shows in the editor as **Explicit**, under Release.

## 0.8.4 (2026-11-19)

- **Covers in the grid view:** switch the Library to the grid and every folder shows the cover of an album inside it, artists included. Nothing extra is read from your disk: the covers come from the search index.
- **Easier to tap on phones:** every button, field and toggle is now at least 44 points tall, as Apple recommends. The search bar responds anywhere you tap it, not just on a thin strip in the middle.
- **Selecting tracks on a phone:** the bar at the bottom no longer runs off the screen. Preset, Replace and Actions now share a "…" menu next to Edit.
- **Safer moves:** Organize, Rename folder and the inbox now move a file in a way that can never replace another file that appears at the same name at the last moment (say, a download finishing). Very long file names also move between disks correctly now.
- **Saves survive power cuts better:** after a file is safely swapped in, its folder is flushed to disk too.
- **Fixed:** filing the same inbox album twice at once (a double tap, or "File all" while it was filing itself) could mark a successfully filed album as failed. A second request is now turned away.
- **Fixed:** a double tap on Undo could run the same undo twice, and undoing a move whose folder no longer exists showed a server error instead of saying why.
- **Fixed:** after saving, going back to a search or a grid could still show the old tags or cover until you reloaded.
- **Fixed:** a MusicBrainz match that saved the tags but not the cover left search and Library health showing the old tags.
- **Fixed:** pressing Ctrl/Cmd+S twice quickly saved everything twice (and logged it twice). A save already under way now just carries on.
- The "/" shortcut for search no longer jumps behind an open dialog.
- **Fixed:** applying a Tag Preset to a folder stopped part-way if one file couldn't be opened (say, a permissions problem), and the files it had already changed weren't in Activity, so they couldn't be undone. Now that one file is reported and the rest carry on, all undoable.
- **Library health's one-tap fixes** check the album again first if anything changed since the list was made.
- **What's new** shows its links properly (they opened as plain text before) and they now open on GitHub.

## 0.8.3 (2026-11-19)

(0.8.2 was tagged but never released: our tests caught the Library health bug below just in time.)

- **Snap:** `sudo snap install codetta` on Ubuntu and other Linux systems, for Intel/AMD and ARM. It updates itself. See [On your own computer](docs/install.md#on-your-own-computer).
- **MusicBrainz, more patient:** when it's busy or slow, Codetta now waits longer (20 seconds instead of 8), tries up to three times with a growing pause, and waits as long as MusicBrainz asks. Fewer "busy" and "couldn't reach" errors.
- **Fixed:** Library health said every album "isn't matched on MusicBrainz yet", even matched ones. Your search index is rebuilt once after updating so it can tell them apart.
- **Fixed:** right after Codetta first reads your library, Library health could briefly show an incomplete list from part-way through. It now waits for the full answer.
- New screenshots and an animated README header, with real albums.

## 0.8.1 (2026-11-19)

- **Run it on your own computer:** no server or Docker needed. `pipx install codetta`, then `codetta` opens your Music folder in the browser (Linux and macOS; Windows support is coming). `codetta set-password` and `codetta sign-out-all` work there too. See [On your own computer](docs/install.md#on-your-own-computer).
- **Fixed:** an album now lists its tracks by track number, not file name, so after a MusicBrainz match renumbers them they're in the right order straight away.

## 0.8.0 (2026-11-18)

- **Big libraries, much faster** (measured on 105,000 tracks):
  - Reading your library the first time is about **4× faster** (139 → 34 seconds): helper processes share the work, then stop. `CODETTA_INDEX_WORKERS` sets how many.
  - A folder of **5,000 tracks opens in a quarter of a second** on the server (was 6.5 s) and draws on screen without freezing: the first screenful at once, the rest a batch at a time.
  - The Library page with 2,000 folders draws in a quarter of a second, without a freeze.
  - **Search** of everything: 1.5 s → 0.26 s; tag searches like `genre: jazz` 0.27 → 0.07 s.
  - **Library health** checks 10,000 albums in under 4 seconds (was 7), then shows its last answer instantly and re-checks in the background after changes. Long lists load 200 at a time with **Show more**.
  - **Changing a tag on 1,000 files** at once: 10.7 → 5.6 seconds, still one safe write per file and one undo.
  - **Memory** on a 100,000-track library: about 130 MB (was up to 500 MB).
- **Find & replace** in tags, for a folder, a selection or search results: remove "(Official Audio)" from every title, turn "ft." into "feat." Pick one tag or all text tags, match case, or use a pattern (regex). You see every change first, and Activity can undo it.
- **Actions:** one-tap tidy-ups with a preview: **Clean up titles** (removes "(Official Video)", "[Explicit]", "(Lyrics)", "(Free DL)"…), **Write features as "feat."**, **Title Case** and **Trim spaces**.
- **Plugins:** add your own actions, or ones other people wrote. Put a plugin's folder in `config/plugins/` and turn it on in **Account → Plugins** (they're off until you do). The built-in actions are written the same way. See the [plugin guide](docs/plugins.md).
- **Rename folder:** every file moves with it, nothing is overwritten, and it's one undo.
- On phones, Organize, Find & replace, Actions and Rename folder are in a **…** menu next to the album's other buttons.
- **Privacy, written down:** [PRIVACY.md](PRIVACY.md) says what Codetta keeps and what it sends (nothing, until you turn a connection on). No tracking, analytics or telemetry of any kind, and tests now check that it stays that way.
- **Glass, grounded:** menus and the search suggestions have more body, so what's behind them is a soft hint instead of readable text.
- Your search index is rebuilt once after updating (it now keeps a sort order, so results come back in library order without extra work).

## 0.7.1 (2026-11-18)

- **Frosted glass:** sheets, menus, notifications, toasts, the selection bar and the now-playing pill float on frosted glass, with the page blurred softly behind sheets (solid panels where blur isn't available or "reduce transparency" is on).
- **Fresher motion:** one quick, springy curve everywhere. Sheets settle in, toasts and menus pop, buttons give a little when pressed, folders lift on hover, the first rows ripple in when you change pages, and covers settle into place. The Control Center opens with the same quick motion as the other sheets. "Reduce motion" is respected.
- Rounder buttons and badges, to match.
- **Tag Loadouts are now Tag Presets**, everywhere. Your saved ones move over by themselves (from `config/loadouts/` to `config/presets/`).
- **Compact actions:** Apply preset, Organize and (on phones) Select are icon buttons now, and show their name when you point at them. On phones the album's actions fit on one row.
- **A real player:** pressing play queues the rest of the album (or search results) after the track, and it carries on to the next one by itself. **Shuffle**, **previous** and **next** (also from your lock screen and headphones). Tap the now-playing pill for the full player: a big cover, **Up next** (jump to any track, or take one out) and **Lyrics**: synced lyrics follow along line by line (tap a line to jump there), plain lyrics show as they are. Lyrics come from the track's tag or a `.lrc` file next to it.

## 0.7.0 (2026-11-18)

- **Library health** (Level Up #4): a card on the Library page ("23 things to look at") opens one list of what's worth fixing across your whole library: albums that show up split in your player (album name, album artist or year spelled differently, features without an album artist), missing tracks, the same track number twice, missing disc numbers, no cover or a small one, missing basic tags, the same album in two folders, the same song twice, unreadable files, and MP3s inside a FLAC album. It reads Codetta's search index, so checking thousands of albums takes under a second and no music file is opened. Obvious fixes are one tap ("Use “Kehlani” as the album artist", "Number from file names", "Number from disc folders"), with a preview first and one undo in Activity; everything else opens the album, Find in MusicBrainz or (if connected) Find in slskd. Ignore anything you're happy with, and switch any check off under **Checks**. Library health is optional as a whole: a short setup step asks whether you want it (handy to leave off if your library is named exactly the way you want it), and **Account → Library health** switches it on or off any time. Off means no card and nothing is checked.
- **Search anything:** the search bar now says "Search anything" and, when you tap it, offers the places you can search besides your library. **`!mb`** (new) searches MusicBrainz for artists and releases: an artist page (who they are, years active, links, every album, EP and single) and a release page (cover, label, catalog number, tracklist), each marked **In your library** when you have it, with **Open in library**, and **Find in slskd** if that's connected. Each bang is offered only while its connection is on. Back and forward work across these pages.
- The search bar opens wider while you use it and settles back with a softer motion, and its suggestions fade in and out.
- **Account, redesigned** (try it): it now grows straight out of your profile picture like Control Center, on frosted glass, with tiles that light up for Theme, Library health and Advanced mode, corners that follow the panel's curve, and Connections and Password opening in place.
- **You can always tell it's working:** a thin line under the top bar while Codetta waits on the server, a clear "Looking up … on MusicBrainz" page with placeholders while MusicBrainz answers, and a busy state when a Soulseek search is sent. If MusicBrainz says it's busy, Codetta waits a moment and tries once more.
- **Input checks everywhere:** every field the server accepts has sensible limits, IDs are checked before anything else happens, slskd's address and API key are checked as you save them (with a clear message in the form), and searches need at least two letters or numbers.
- Updates reach your browser right away: Codetta's script and styles are now always checked with the server before a cached copy is used.
- **README:** Codetta is presented as what it mainly is, a manager for your music library (fix tags, match on MusicBrainz, organize, bring in new music); Soulseek through slskd is one optional integration among the connections.

## 0.6.2 (2026-11-18)

- **Security:** a downloaded file's tags can no longer steer where Organize or the inbox puts it. A name starting with "@" (like an album artist "@replaced") used to point at one of Codetta's own folders; it now becomes "＠", which looks the same. The inbox can no longer be set to the folder that keeps replaced albums, and a Soulseek download is only ever matched to files that arrived for it (an older album in the inbox with the same file names is never taken for it, so blocklisting can't delete it). One look at the inbox also stops after 5,000 folders.
- **Faster on phones:** the page, its script and styles and every API answer are now sent gzip-compressed (about a quarter of the size; the app's code goes from about 310 KB to 80 KB). Audio, images and fonts are sent as they are.
- **Faster folders:** Codetta remembers the tags of files that haven't changed, so opening a folder again doesn't read every file again. Any change, by Codetta or another program, is picked up straight away.
- **Less disk:** Soulseek download progress is saved every 30 seconds instead of every few seconds, finished requests keep a summary instead of every file list, and the most recent 50 requests are kept.
- **Replaced albums are kept for 30 days** (like "Recently Deleted"), then removed. Undo works until then.

## 0.6.1 (2026-11-18)

- **Fixed:** on phones, the notifications panel and pop-ups ran off the left edge of the screen (the bell moved in from the edge with 0.6.0's new top bar). They now always stay on screen, and are a little more compact on phones.

## 0.6.0 (2026-11-18)

- **Soulseek through slskd** (Level Up #3): a new connection for people who run [slskd](https://github.com/slskd/slskd). Type `!slskd` in the search bar and it becomes a **slskd** chip: what you type next is searched on Soulseek (`*` works as a wildcard for filtered names, like `*-Pain`). Or press **Find in slskd** on an album to fill the search bar with its artist and album, ready to edit. Codetta picks the best copy (lossless first by default, then free upload slots, queue and speed), downloads it into your inbox, moves on to the next copy if one fails or stalls, and asks before it joins your library: **Import**, **Blocklist & try next**, or **Choose another**. A download from an album's button replaces that album (the old copy is kept so Activity can undo it). Turn off *Review each download* to let exact MusicBrainz matches file themselves. Set it up in the new setup step or **Account → Connections**; Codetta warns you if slskd isn't sharing a folder, since Soulseek users often refuse people who share nothing. `CODETTA_SLSKD`, `CODETTA_SLSKD_URL`, `CODETTA_SLSKD_API_KEY`.
- **A roomier top bar on phones:** the tools sit beside the logo and the search bar gets its own full-width row, with a **Cancel** button that slides in while you use it (like iOS). On computers the search bar widens while you use it.
- The Inbox's **Soulseek** and **Settings** are proper buttons now.
- **Download progress:** an album that's still arriving in the inbox shows a progress bar with how many files are in and roughly how long the rest will take (from slskd, for anything downloading there, started from Codetta or not). Soulseek downloads in the Soulseek sheet show the time left too.
- **README:** rewritten for what Codetta is now: find, import, match, fix and file your music, with an updated comparison table and FAQ.

## 0.5.0 (2026-11-18)

- **Import inbox** (Level Up #2): pick the folder new music lands in (downloads, rips). Codetta groups it into albums (disc folders join their album; loose tracks are one item each), finds each on MusicBrainz (by tags, then by sound if AcoustID is on), and files it into your library: MusicBrainz tags + your Organize pattern, each an undoable activity entry. Confident matches show "Ready to file" (or file themselves if you allow it); the rest wait for a review in the familiar match dialog. Albums already in your library are never overwritten. Inbox button in the top bar with a count; optional check every 15 minutes (off by default so idle disks can sleep). The inbox can be a folder outside your music folder: mount your downloads (e.g. slskd's) at `/inbox` (or set `CODETTA_INBOX_DIR`); files are copied across, checked, then removed from the downloads folder. Albums that are still arriving wait until their files have been still for 2 minutes.
- **Easier setup:** after creating your account, a few short steps: online features, how your folders should be named, and where new music arrives. Each is skippable and changeable later. Existing installs see only the new steps, once.
- **What's new:** this changelog in the app. It pops up once after setup and after each update, and there's a "What's new" link in the footer, in Account, and on the sign-in screen.
- **Now playing:** a pill grows out of a circle at the bottom of the screen while a track plays: cover (turning like a record), title, artist, time, play/pause, stop, and a thin line you can drag to seek. Music keeps playing while you browse; tap the title to jump back to its album.
- **Notifications:** a bell next to your account picture. Things Codetta does in the background (the inbox finished looking things up, an album filed itself, a new version is out) pop out of the bell for a few seconds, and the bell keeps the list. Tap one to go straight there.
- **Fixed:** an album's genre chip only showed the first genre when genres were separated with ";". It now lists every genre, separated by commas, however the file separates them (";", ",", "|" or separate values).

- **Organize** (Level Up #1): rename and move files into folders from their tags with a pattern like `{albumartist|artist}/{album}[ ({year})]/{disctrack} {title}`. Presets, one-tap tag buttons and a live example; a preview of every move before anything happens. Names are made safe for any filesystem or network share, nothing is ever overwritten (conflicts are listed instead), lyrics files and the album's cover, booklet and scans move along, and emptied folders are tidied away. One undoable entry in the activity log. Files without artist/album tags are flagged before they'd land in "Unknown Artist".

- **Play a track** from the list: a play button at the end of every row (it grows to "Play" when you point at it). Plays the file straight from your server, with seeking and lock-screen/headphone controls. Nothing is converted or cached; formats your browser can't play (WMA, DSF, WavPack…) get no button.
- **Multi-disc albums** read like a streaming service: a "Disc 2" line (with the disc subtitle) between discs, tracks grouped by disc, and pointing at a row shows "2/01". The disc icon spins when you point at it, and slowly while that disc is playing.

## 0.4.1 (2026-11-18)

- The dashboard icons (`/static/icons/`) are now included in the Docker image (0.4.0 left them out).

## 0.4.0 (2026-11-18)

- **Offline unless you opt in.** Online features are now *connections*, all off until you choose. After creating your account (or on first start after upgrading) a welcome card asks: stay offline, or turn on online features, with a switch for each one saying exactly what it sends and where. Change them any time in **Account → Connections**. `CODETTA_MUSICBRAINZ`, `CODETTA_LYRICS_LOOKUP` and `CODETTA_UPDATE_CHECK` (`on`/`off`) lock a switch from your compose file; `CODETTA_OFFLINE=on` blocks them all.
- **Changed:** Find lyrics and the update check used to be on by default. They're now off until you turn them on (the welcome card offers this once).
- **Match on MusicBrainz:** find the release for an album folder (or selected tracks) by its tags or a pasted musicbrainz.org link, compare editions (year, country, format, label, catalog number, track count, match score), then review a per-file preview before writing. Files are paired with tracks by disc/track number, then title and length, and any pairing can be changed. Choose the fields (titles, credits from recording and work relationships, release details, sort names, MusicBrainz IDs and ISRCs, genres), replace or only fill empty tags, and add cover art from the Cover Art Archive. One activity entry, undoable as a whole (tags and cover together). Respects MusicBrainz's one-request-a-second limit; `CODETTA_MUSICBRAINZ_URL` points it at your own mirror.
- **Identify by sound (AcoustID):** a new connection that recognises tracks by their audio, even untagged ones. In the match dialog, **Listen** fingerprints each file on your server with Chromaprint's `fpcalc` and sends only those codes and track lengths to AcoustID. Releases holding most of your tracks are offered first ("9 of your 10 tracks are on it"), and files pair with their exact recordings. The Docker image now includes Chromaprint's official static `fpcalc` (about 9 MB, checksum-verified). `CODETTA_ACOUSTID`, `CODETTA_ACOUSTID_KEY`, `CODETTA_FPCALC`.
- MusicBrainz IDs (release, release group, recording, release track, artist, album artist, work) and `script` are stored the way Picard writes them in every format, including M4A and WMA.
- **Find in MusicBrainz** button on album pages, beside the genre (phones: "Find", first in the action row), with a MusicBrainz-coloured edge that shifts and glows on hover.
- **Dashboard icons:** the Codetta icon in full colour, light (for dark dashboards) and dark (for light dashboards), as SVG, PNG and WebP, served at `/static/icons/` so Homepage, Homarr or Dashy can point straight at them.
- Account → Connections opens and closes (the closed row says what's on), and the sound lookup button reads **Listen** → **Listening…** while it works.
- With sign-in turned off, the account button now opens Settings, so connections and Advanced mode stay reachable.

## 0.3.1 (2026-11-18)

- The browser tab and home-screen icon now update to the new logo right away (they were being kept from the browser's cache).

## 0.3.0 (2026-11-18)

- A new look, "liner notes": Codetta now reads like the credits pages of a CD or LP booklet. New lowercase wordmark and icon, the Schibsted Grotesk typeface (bundled), booklet-white and booklet-black themes, and ink rules and hairlines instead of boxes.
- Each album lends Codetta a colour picked from its cover (adjusted for readable contrast), used for the active track, changed fields, section heads and the logo's square, crossfading as you move between albums.
- Album folders open as a booklet spread: large cover, album title, artist, year, track count and total runtime, and a genre chip. Columns that would repeat the same value on every row (album, artist, format, cover) are left out; phones show track numbers.
- The editor reads like a credits sheet: labels beside values on hairlines, with the field box appearing when you point at or edit it.
- Sign-in is a clean title page; the folder grid is a contents page; phones show one back link instead of a cramped breadcrumb.
- Accessibility: text on coloured fills switches to dark in dark mode for readable contrast; checkmarks are drawn icons.

## 0.2.0 (2026-11-17)

- 10 more formats: WAV, AIFF, DSF (DSD), TrueAudio, MP2, WavPack, WMA, M4B audiobooks, Ogg FLAC and Speex, with album art and every editor field on each. Codetta now handles 15 file types.
- Sort names (title, artist, album, album artist, composer) and classical fields (work, movement, movement number and count, show movement) plus subtitle, stored where Picard puts them in every format.
- Advanced mode (account menu): a Raw tags section in the editor lists every stored field exactly as the file has it (ID3 frames, MP4 atoms, Vorbis comments, APEv2 items, WMA attributes, pictures). Read-only.
- Lyrics: plain or synced (LRC) in a roomy editor box with a "Synced lyrics · 42 timed lines" hint; stored where players look (Vorbis LYRICS, ID3 USLT, MP4 ©lyr, APE Lyrics, WM/Lyrics). Long values are shortened in the activity log (undo still restores the full text).
- Find lyrics: looks the track up on LRCLIB (only when you press it, sending artist, title, album and length), shows a preview, and offers synced or plain lyrics as an unsaved change. `CODETTA_LYRICS_LOOKUP=off` hides it. First of Codetta's online providers (MusicBrainz and Last.fm will follow the same pattern).

## 0.1.1 (2026-11-17)

- README rewritten as a short landing page; details moved to `docs/` (install, configuration, features, FAQ), plus `SECURITY.md` and `CONTRIBUTING.md`.
- README: an honest comparison with MusicBrainz Picard, beets and Metadata Remote.
- A quiet footer on the sign-in screen and under the track list: GitHub link · Made with ♥︎ · version.

## 0.1.0 (2026-11-17)

First release.

- Edit tags on FLAC, MP3, M4A, OGG Vorbis and Opus files, one track or many at once.
- Navidrome / OpenSubsonic tag set (credits, mood, label, release type, multiple artists…), stored the way MusicBrainz Picard does.
- Save to folder, copy & paste tags, smart suggestions from the folder, and hints for dates and multi-value fields.
- Album art: add, replace or remove embedded covers as part of a save, for one track, a selection or the whole folder; thumbnails on every track row.
- Tag Loadouts with placeholders and a preview before writing.
- Filter a folder by tag; folders as a list (default) or grid.
- Works with any language: every script and emoji round-trips exactly; accent-insensitive search; right-to-left names display correctly; sorting ignores case and accents; file names that aren't valid UTF-8 are skipped with a note instead of breaking the folder; emoji get a gentle tip, never a block; commas in names (e.g. "Tyler, The Creator") are never flagged.
- Comma-separated genres and moods ("Hip-Hop, Trap, Rap", as Navidrome splits them by default) are saved as typed and filter by each part.
- Activity log of every change, with old and new values, and undo/redo straight from the log (files edited again since are left alone).
- Safe writes: temporary copy, verify, atomic swap; symlinks, hard links, permissions and cover art preserved.
- Sign-in with hashed passwords, 30-day sessions, lockout and password reset from the server.
- Profile pictures: a round photo of your choice in the top bar and account menu (JPEG, PNG, WebP, GIF, AVIF, and HEIC on iPhone/Safari).
- Version shown on the sign-in screen and account menu, with a check for new releases.
- Large folders stay fast: a 2,000-track folder opens in under a second and filters in a quarter of a second; a shared album cover downloads once.
- Simultaneous saves to the same file (two devices, a double-tap) can no longer lose an edit.
- Security hardening: strict Content Security Policy and security headers, cross-site request protection, request size limits, album art only ever served as an image, stronger password hashing (upgraded automatically at sign-in), optional `CODETTA_ALLOWED_HOSTS`.
- Search your whole library by tag: `genre: rap, hip-hop`, `artist: drake`, `year: 2024`, or plain words. Commas mean "or", and matching is word-aware ("rap" doesn't find "Trap") and accent-insensitive. Results can be selected and edited like a folder. Backed by a small index in the config folder that updates in the background and right after every edit.
- Ready-made Docker image for Intel/AMD and ARM servers: `ghcr.io/gavndev/codetta`. Install with one compose file, update with `docker compose pull`.
- The container runs as your user, with a health check and read-only filesystem.
- Small footprint: a ~100 MB image (Alpine), ~70 MB of memory, a search index of about 2 KB per track, and no background disk activity when idle (the library is re-checked when you search, at most every 15 minutes), so hard drives can spin down. No per-request access log filling up Docker's logs.
- First-run setup only works from home networks, Tailscale or the server itself (`CODETTA_ALLOW_PUBLIC_SETUP` to override), so nobody on the internet can claim a fresh install.
- Requests are bounded (at most 1,000 files and 100,000 characters per tag value), and a file listed twice in one request is edited once. Big Save to folder jobs are sent in batches automatically.
- On desktop, the selection bar and notifications no longer cover the editor's activity log when the editor is open.
- On phones, value suggestions for half-width fields (Genre, Disc) are wide enough to read.
