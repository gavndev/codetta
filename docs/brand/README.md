# Codetta brand

Codetta reads like the credits pages of a well-made CD or LP booklet: booklet
stock and ink, one strong grotesque, hairline rules, and one spot colour per
album taken from its cover.

## Logo

| File | Use it on |
|---|---|
| `logo-light.svg` | Light backgrounds: lowercase **codetta** in ink with the square spot |
| `logo-dark.svg` | Dark backgrounds |
| `mark.svg` / `app-icon.svg` | Favicon and app icon: the spot square with a knocked-out lowercase c |
| `social-preview.png` | GitHub social preview / link cards (1280 × 640) |
| `../../src/codetta/web/static/icons/codetta.{svg,png,webp}` | Dashboards: the full-colour app icon, on any background |
| `…/icons/codetta-light.*` | Dashboards with dark backgrounds: "c." in booklet white with the dark-mode spot |
| `…/icons/codetta-dark.*` | Dashboards with light backgrounds: "c." in ink with the house spot |

The dashboard icons follow the naming dashboard-icon collections use (`name`,
`name-light`, `name-dark`) and are served by Codetta at `/static/icons/` without
sign-in, so a dashboard can point straight at them. PNG and WebP are 512 × 512.

`dashboard-icons/` holds the same three SVGs cropped to the artwork, as the
shared collections want them: submit them at
[dashboardicons.com/submit](https://dashboardicons.com/submit), and see the
[selfh.st request](https://github.com/selfhst/icons/discussions/1098).

**The wordmark** is "codetta" in Schibsted Grotesk at weight 800, tracked
tight (−3.5%), followed by a small square "full stop" sized from the x-height.
In the app the square takes the open album's spot colour; everywhere else it
is the house teal. Text is converted to outlines in the SVG files.

Keep clear space of at least the square's width × 2 around the logo. Don't
stretch, outline, recolour the letters, or round the square.

## Colour

| Role | Light | Dark |
|---|---|---|
| Ground (booklet stock) | `#f7f8f8` | `#131418` |
| Ink | `#1b1e24` | `#f0f0ec` |
| Muted text | `#59606d` | `#a4a9b4` |
| House spot | `#0e7c74` | `#4fc3b4` |

**The spot colour.** Each album lends Codetta one colour, picked from its cover
(the strongest saturated hue) and adjusted until text in it passes 4.5:1
contrast on the current background. It marks the active track, changed fields,
section heads, the genre chip, links and focus, and crossfades as you move
between albums. Albums without a cover, the library and search use the house
spot. Album art is the only other full colour on screen.

## Type

[Schibsted Grotesk](https://github.com/schibsted/schibsted-grotesk) (SIL Open
Font License), bundled with the app. Titles heavy (800) and tight; credits and
body regular. Track numbers use tabular figures ("01"); times use the default
figures.

## Shape and rules

Covers and thumbnails are square (2–3px). Controls have small 6px corners. A
1.5px ink rule opens each list, hairlines separate entries, and fields sit on a
hairline like a credits line until you edit them.

## Motion

Quick and quiet: 120–340 ms, ease-out in, ease-in out. The one signature moment
is the spot colour crossfading (700 ms) when you open an album. All motion
turns off with the system's reduced-motion setting.

## Voice

Plain, friendly and precise. Say what will happen ("Save to 5 tracks"), not what
the code does.
