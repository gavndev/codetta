[← Back to the README](../README.md)

# Codetta on your computer (desktop and portable)

No server, no Docker, nothing to set up: download Codetta for your computer,
unzip it and open it. It opens in a window of its own, works on the music folder
of that computer, and closes when you close the window.

> [!NOTE]
> **Not released yet.** The desktop app is a preview in the works: builds aren't
> on the releases page yet. This page describes how it will work. It's the same
> Codetta as the server version, packaged with everything it needs.

## Download

From the [latest release](https://github.com/gavndev/codetta/releases/latest):

| Your computer | Download |
|---|---|
| Windows 10 or 11 | `Codetta-…-windows-x86_64.zip` |
| Mac (Apple silicon) | `Codetta-…-macos-arm64.zip` |
| Linux | `Codetta-…-linux-x86_64.zip` (or `-arm64`) |

Each one also comes as **-Portable.zip** (see below).

## Open it

- **Windows:** unzip, open the **Codetta** folder and double-click **Codetta**.
  The first time, Windows may say "Windows protected your PC": choose **More
  info → Run anyway**. (Codetta isn't signed with a paid certificate yet.)
- **Mac:** unzip, then **right-click Codetta → Open → Open** the first time
  (macOS blocks apps from unidentified developers on a double-click).
- **Linux:** unzip and run `Codetta/Codetta`.

It opens your **Music** folder. There's no account to make and no sign-in
screen: the window signs itself in, and nothing outside your computer can reach
it.

**The window** is an app window of a browser you already have: Microsoft Edge
(on every Windows 10/11 PC), or Chrome, Brave or Chromium. Without one of those,
Codetta opens in your default browser instead, and **Account → Quit Codetta**
closes it.

**Your settings** (Tidy up, presets, undo history, Recently deleted) are kept in
your user's app-data folder, so they're still there after an update:
`%APPDATA%\Codetta` on Windows, `~/Library/Application Support/Codetta` on a
Mac, `~/.config/codetta` on Linux.

## Portable: from a USB stick

The **-Portable.zip** is the same app with an empty **Codetta Data** folder next
to it. With that folder there, Codetta keeps *everything* in it, and nothing on
the computer: copy the **Codetta** folder to a USB stick (or a synced folder),
plug it into any computer with the same system, and open it. Unplug it and
nothing is left behind.

Put your music in a **Music** folder next to the app, or open Codetta with
another folder: `Codetta /path/to/music` (it remembers it).

On a Mac, move **Codetta.app** with Finder to where it'll live (the stick)
before opening it the first time; macOS runs apps straight out of a download
from a hidden copy, where the Codetta Data folder can't be seen.

## For the curious

- One Codetta at a time: opening it again opens another window onto the one
  that's running.
- The log is `codetta.log` in the settings folder (handy for Report a problem).
- Want to reach it from your phone too? That's what the [server
  version](install.md) is for; the desktop app only listens on this computer.
