[← README](../README.md)

# Listen in your music apps

Codetta can serve your library to music apps that speak the **Subsonic / OpenSubsonic API**,
the same one Navidrome serves: Symfonium, Narjo, Arpeggi, Feishin, DSub, Substreamer, Eclipse
and many more. They can browse, search and play your music, show covers and lyrics, and offer
"similar songs" (from [Autoplay](autoplay.md)). They can't change your files.

**This feature is released in an alpha/WIP**, still working on…

- Converting files to a smaller format for mobile data (currently always streamed in original format)
- Playlists
- Stars
- Ratings
- Play counts (apps can send them; Codetta doesn't keep them).

Already run Navidrome? You don't need this: Navidrome is a full music server, and Codetta keeps
its tags right. This is for libraries that only have Codetta.

## Turn it on

1. In Codetta, open **Account → Connections** and switch on **Listen in your music apps** (or
   say yes in the setup step).
2. In your app, add a **Subsonic** (or **Navidrome**) server with:
   - **Server address:** the address you open Codetta at, e.g. `http://192.168.1.50:8111`
   - **Username:** your Codetta username
   - **Password:** the **app password** Codetta shows (never your Codetta password)

The app password only works for music apps. **Make a new password** signs every app out.

## What's included

| | |
|---|---|
| Browse | Artists, albums and songs (from your tags), or your folders |
| Search | Everything, including the full-library sync some apps do |
| Play | The original files, with seeking (no conversion) |
| Covers, lyrics | Embedded covers; plain and synced lyrics |
| Lists | Newest, random, A–Z, by year, by genre; random songs; similar songs |

## How it signs in

Apps sign in on every request with the app password: the classic Subsonic token (a salted MD5
hash), the password itself, or an OpenSubsonic API key. Wrong passwords are rate-limited like
Codetta's sign-in page. It's served at `/rest/` on Codetta's usual address, and nothing else
there opens without Codetta's own sign-in. Use HTTPS (or a private network like Tailscale) when
apps connect from outside your home.
