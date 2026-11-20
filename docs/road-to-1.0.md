# The road to 1.0

Codetta is in beta: careful with your files and used daily on real libraries, but
still changing quickly. 1.0 means you can install it and stop worrying about it.
This is the list it has to pass first. It's public so you can see how close it is,
and hold it to it.

## Your files

- [ ] **No open data-loss bugs.** Any report of a damaged, lost or wrongly moved file blocks 1.0.
- [x] **Every write is verified** (temporary copy, read back, atomic swap) and every change can be undone.
- [ ] **Tested against a collection of real-world oddities:** files tagged by iTunes, foobar2000,
      Windows Media Player, Mp3tag and old Picard versions, broken headers, huge covers, every
      script and emoji, and each save checked to change nothing it wasn't asked to.
- [ ] **Round-trip tests with generated tags:** thousands of random tag sets per format, each
      saved and read back exactly.

## Updating

- [x] **Settings carry a version number**, are backed up before an upgrade changes them, and are
      never touched by an older Codetta.
- [ ] **Upgrades tested from every 0.9.x release** to the 1.0 candidate, with real settings folders.
- [ ] **Test builds before every release** (`beta` image tag, the snap's beta channel).

## Running it

- [ ] **Tested on a Raspberry Pi 4 with a USB hard drive** and a large library (100,000 tracks),
      for memory, startup time and how long a first scan takes.
- [x] Runs as your user, never root, with sign-in, a strict security setup and no telemetry.
- [ ] **An outside security review** of sign-in, file paths and uploads.

## The code

- [x] The API is split into one module per area, and so is the page.
- [x] A public map of the code ([ARCHITECTURE.md](../ARCHITECTURE.md)).
- [ ] **The interface is ready for translation:** every piece of text in one place, so
      translations can be added without touching the code.

## After 1.0

Refresh from MusicBrainz, ReplayGain, Windows and Homebrew installs, and a small website.
Big changes after 1.0 come with an upgrade path and a clear note in the changelog.
