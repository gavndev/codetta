# Using Codetta with Lidarr

[Lidarr](https://lidarr.audio) finds and downloads albums. Codetta makes their
tags right. They work well side by side on the same music folder, as long as
Lidarr hears about Codetta's changes and only one of them names the files.
The **Lidarr** connection takes care of both.

## Connect them

1. In Lidarr, copy the API key from **Settings → General → API Key**.
2. In Codetta, open **Account → Connections**, turn on **Lidarr**, and enter
   Lidarr's address (`http://lidarr:8686` on the same Docker network, or
   `http://192.168.1.50:8686`) and the key. Press **Save and test**.

New installs (and existing ones, once) are also asked "Do you use Lidarr?"
during setup.

Codetta finds Lidarr's folders in your library by itself, even when the two
containers call the music folder different things (`/music` in Codetta,
`/data/media/music` in Lidarr). Both just need to see the same folder.

## What the connection does

- **Lidarr rescans straight away.** After Codetta changes files in Lidarr's
  folders (tags, covers, renames, moves, deletes), it asks Lidarr to rescan
  just those folders, a few seconds later and in one go. Without this, files
  Codetta moved look missing to Lidarr until its next scheduled scan, and a
  monitored album could be downloaded again.
- **One app names the files.** When Lidarr's renaming is on (**Settings →
  Media Management → Rename Tracks**), Organize and Tidy up leave file names
  and folders in Lidarr's folders alone and fix tags only. If you'd rather
  Codetta's folder pattern name everything, switch off **Let Lidarr name its
  files** in Codetta, and turn off Rename Tracks in Lidarr. Moving or renaming
  something yourself always works either way.
- **Warnings about conflicts.** Codetta reads Lidarr's settings and tells you
  when they would undo your work.

## The one setting to check in Lidarr

**Settings → Metadata → Write Audio Tags.** If it's set to **All files** (or
**Sync**), Lidarr rewrites the tags of every file in an album on its scheduled
refresh, which undoes what you fixed in Codetta. In testing, a title fix was
reverted and a genre was replaced by Lidarr's own list of 17 genres. Set it to
**For new files only** (Lidarr tags what it imports, Codetta takes it from
there) or **Never**. Codetta shows a warning while it's set to All files.

## Don't share a downloads folder

Lidarr imports from its download client's folder by itself. Don't choose that
same folder as Codetta's inbox, or both apps will try to import the same
downloads. Codetta's inbox is for music Lidarr doesn't handle (Soulseek, rips,
anything you copy in).

## Tested

With Lidarr 3.1 on real albums (silent copies with real track lengths and tags):

| What happens | Without the connection | With it |
|---|---|---|
| Codetta fixes tags (a MusicBrainz match on a messy album) | Fine: Lidarr keeps every file | Same, and Lidarr rescans the album |
| Codetta renames or moves files | Lidarr finds them again on its next scan; until then they look missing | Lidarr has them at their new place within seconds |
| Lidarr writes tags to all files | Lidarr undoes Codetta's fixes | Codetta warns you and names the setting |
| Lidarr renames files | Its next import or Rename moves files back to its pattern | Codetta leaves names in Lidarr's folders alone |

## Server settings

| Variable | What it does |
|---|---|
| `CODETTA_LIDARR` | `on`/`off`: the Lidarr connection (locks the switch in the app). |
| `CODETTA_LIDARR_URL` | Lidarr's address as Codetta sees it, e.g. `http://lidarr:8686`. |
| `CODETTA_LIDARR_API_KEY` | Lidarr's API key. Saved keys live in `lidarr.json` in the config folder, readable by Codetta only, and are never sent back to the browser. |
