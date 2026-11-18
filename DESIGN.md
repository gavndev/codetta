---
name: Codetta
description: A self-hosted music tag editor set like the credits pages of a CD/LP booklet.
colors:
  house-spot: "#0e7c74"
  house-spot-dark: "#4fc3b4"
  booklet-stock: "#f7f8f8"
  sheet-white: "#ffffff"
  ink: "#1b1e24"
  muted-ink: "#59606d"
  faint-ink: "#6f7581"
  field-line: "#8b919b"
  hairline: "rgba(27, 30, 36, 0.1)"
  danger: "#c4291c"
  success: "#1f7a3a"
  warning: "#9c4f00"
  booklet-black: "#131418"
  sheet-dark: "#1a1c21"
  sheet-raised-dark: "#23252b"
  ink-dark: "#f0f0ec"
  muted-ink-dark: "#a4a9b4"
  faint-ink-dark: "#8a909b"
  field-line-dark: "#6e737d"
  hairline-dark: "rgba(240, 240, 236, 0.1)"
typography:
  display:
    fontFamily: "Schibsted Grotesk, Codetta Cyrillic, -apple-system, system-ui, sans-serif"
    fontSize: "52px"
    fontWeight: 800
    lineHeight: 1.04
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Schibsted Grotesk, Codetta Cyrillic, -apple-system, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 800
    lineHeight: 1.04
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Schibsted Grotesk, Codetta Cyrillic, -apple-system, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 800
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  section-head:
    fontFamily: "Schibsted Grotesk, Codetta Cyrillic, -apple-system, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.45
  body:
    fontFamily: "Schibsted Grotesk, Codetta Cyrillic, -apple-system, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Schibsted Grotesk, Codetta Cyrillic, -apple-system, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.45
  track-number:
    fontFamily: "Schibsted Grotesk, Codetta Cyrillic, -apple-system, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    fontFeature: "tnum"
  wordmark:
    fontFamily: "Schibsted Grotesk"
    fontSize: "21px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.035em"
  mono:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "12px"
rounded:
  cover: "2px"
  art: "3px"
  chip: "4px"
  control: "6px"
  popover: "10px"
  card: "12px"
  sheet: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  2xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.booklet-stock}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "34px"
  button-secondary:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "34px"
  button-small:
    rounded: "{rounded.control}"
    padding: "0 10px"
    height: "30px"
  icon-button:
    textColor: "{colors.muted-ink}"
    rounded: "{rounded.control}"
    size: "32px"
  input-field:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 10px"
    height: "36px"
  credit-line-field:
    textColor: "{colors.ink}"
    rounded: "0"
    padding: "0 0 0 2px"
    height: "36px"
  genre-chip:
    textColor: "{colors.house-spot}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    padding: "3px 10px"
  track-row:
    textColor: "{colors.ink}"
    height: "48px"
  album-cover:
    rounded: "{rounded.cover}"
    size: "200px"
  dialog-sheet:
    backgroundColor: "{colors.sheet-white}"
    rounded: "{rounded.sheet}"
---

# Design System: Codetta

## Overview

**Creative North Star: "Liner Notes"**

Codetta reads like the credits pages of a beautifully made CD or LP booklet: every track gets the credits page it deserves. The ground is booklet stock (near-white, faintly cool) or booklet black, the type is ink in one display-grade grotesque, and structure comes from rules rather than boxes: a 1.5px ink rule opens each list, hairlines separate entries, and editable fields sit on a hairline like a printed credit line until touched. It is an operating tool, dense and calm, with the music's own artwork as the only full colour on screen.

The one moving part of the identity is the spot colour. Each album lends the interface a single colour lifted from its cover art, fitted for text contrast against the current theme, and crossfaded when you move between albums. It marks the active track, changed fields, the editor's section heads, the album's genre chip, links, focus and selection. The library, search results and coverless folders fall back to the house spot (teal). Everything else is ink, stock and grey.

It refuses the category default of a grey dashboard with one fixed blue accent and a boxed data table. It is not dark-and-nerdy, cute or corporate; confidence comes from exact, quiet typesetting, not decoration.

**Key Characteristics:**
- One typeface (Schibsted Grotesk), heavy and tight for titles, regular for credits.
- Rules, not boxes: 1.5px ink rule over every list, 1px hairlines between entries.
- One spot colour per album from its cover; house teal when there is none.
- Album art is the only full colour; covers are square (2–3px corners).
- A folder that is one album becomes a booklet spread: 200px cover beside a 52px title, with repeating columns dropped.
- Light and dark themes are equals; the spot is refitted on every theme change.

## Colors

Booklet stock and ink, plus one borrowed spot colour; the palette is deliberately monochrome so the album's own colour can carry the screen.

### Primary
- **The Spot (dynamic)**: the album's colour, set at runtime on `--spot` (app.js:297–358). `coverColour()` samples the cover at 32×32, discards near-black, near-white and low-saturation pixels, and takes the saturation-weighted average of the strongest of 24 hue bins; grey covers return null. `fitSpot()` clamps saturation to 0.5–0.85 and walks lightness until text in the colour reaches 4.6:1 against the current background (darker on stock, lighter on booklet black). `refitSpot()` reruns on theme change. `--spot` is registered with `@property` (app.css:25) so it crossfades over 700ms (app.css:137). `--accent`, `--accent-hover`, `--accent-soft` (13%) and `--selected` (10%) all derive from it with `color-mix(in oklab, …)` (app.css:131–136).
- **House Teal** (light `house-spot`, dark `house-spot-dark`): the spot when no album cover applies: library, search, coverless folders, the sign-in wordmark's square, and the app icon / favicon.

### Neutral
- **Booklet Stock** (`booklet-stock`): the page ground in light theme, and the text colour on the ink Save button.
- **Sheet White** (`sheet-white`): editor panel, dialogs, buttons, inputs in light theme.
- **Ink** (`ink`): all primary text, the 1.5px list rules, and the primary button fill.
- **Muted Ink** (`muted-ink`): secondary text: artist/album columns, meta lines, field labels, durations.
- **Faint Ink** (`faint-ink`): placeholders, separators, timestamps, paths.
- **Field Line** (`field-line`): input and button borders; chosen for 3:1 against the field (WCAG non-text contrast).
- **On Colour** (`--on-color`): text, ticks and icons on the spot or status colours (badges, the phone brand icon, checked boxes, activity icons, danger fills): white in light, booklet black `#131418` in dark, because the dark spot and status colours are fitted light.
- **Hairline** (`hairline`): the 10% ink line between credit entries, track rows and editor groups.
- **Booklet Black / Sheet Dark / Sheet Raised Dark / Ink Dark** (dark theme): the same roles inverted; ground `booklet-black`, panels `sheet-dark`, popovers `sheet-raised-dark`, text `ink-dark` (warm off-white).

### Status
- **Danger** (`danger`), **Success** (`success`), **Warning** (`warning`), each with a soft 8–14% tint for backgrounds; dark theme brightens them (`#ff6b5e`, `#4cd07d`, `#ffad42`). Status colours never stand in for the spot.

### Named Rules
**The One Borrowed Colour Rule.** The only chromatic UI colour on screen is the open album's spot (or house teal). Never add a second brand accent, a fixed blue, or decorative colour; album art supplies the rest.

**The Fitted Spot Rule.** Any colour taken from artwork must pass through `fitSpot()` before it touches text: 4.6:1 against the current background, refitted when the theme changes. Never paint raw cover colour onto UI.

**The Ink Button Rule.** The primary action (Save, Sign in) is solid ink on stock, not the spot. The spot marks state and identity; ink marks commitment.

## Typography

**Display Font:** Schibsted Grotesk (variable 400–900, bundled woff2), with "Codetta Cyrillic" (Inter's Cyrillic subset) and system fonts per script.
**Body Font:** Schibsted Grotesk.
**Label/Mono Font:** system monospace only for raw tag names, tag keys and code (`--mono`).

**Character:** One grotesque doing everything, like a booklet typeset in a single family: titles set heavy (800) and tracked tight, credits set regular and plain.

### Hierarchy
- **Display** (800, 52px, 1.04, −0.035em): the album title in the booklet-spread header; 30px on phones. `text-wrap: balance`.
- **Headline** (800, 40px, 1.04, −0.035em): folder and library titles; 30px on phones.
- **Wordmark** (800, 21px, −0.035em): lowercase "codetta" in the top bar; 56px (−0.045em) on the sign-in page.
- **Title** (800, 19px, 1.3, −0.02em): the editor's track title (two-line clamp); sign-in heading 22px.
- **Section head** (700, 14px, spot colour): the editor's collapsible group heads ("Basics").
- **Body** (400, 14px, 1.45): everything else; 15px on phones. Track titles 600.
- **Label** (500, 12px, muted): credit-sheet field labels, editor sub-lines, table head (600).

### Named Rules
**The Tabular Track Number Rule.** Tabular figures are used only for track numbers ("01"–"99", zero-padded, weight 600, app.css:482). Times, counts, versions and sizes keep the font's default figures (`font-variant-numeric: normal`).

**The Heavy-and-Tight Rule.** Any title 19px and up is weight 800 with negative tracking (−0.02em to −0.045em). Body and credits never go below 400 or get tracked.

## Layout

A slim top bar (wordmark left, breadcrumbs, filter field and icon buttons right; glass background with backdrop blur), then a browser column and, on desktop, a 500px editor panel on the right. Browser content is capped at 1200px and centred, with 24px side padding (16px on phones, both respecting safe-area insets) and 96–120px bottom padding to clear the floating selection bar.

A folder whose tracks share a cover becomes a **booklet spread**: a 200px cover beside the heavy title, artist/year/track-count/runtime line and genre chip, aligned to the bottom (32px gap; 96px cover and 16px gap on phones). The track list's columns are computed in JS (`--cols` / `--cols-mid`, app.js:795–814): a single album drops the thumbnail and album columns, a shared artist drops the artist column, a shared format drops the format column. At ≤1180px the album column goes; at ≤760px rows become thumbnail (or track number for one album) + title/sub-line + time, 62px tall, with selection circles only after tapping Select.

The editor on desktop is a **credits sheet**: a 116px label column and the value on the right, 3px row padding. On phones (≤760px) it becomes a full-screen sheet with stacked labels, and dialogs dock to the bottom edge.

Rhythm runs on 4px steps (4 / 8 / 12 / 16 / 24 / 32). Rows are a minimum of 48px; 44px touch targets on phones; inputs are 16px on phones to stop iOS zoom. Breakpoints: 760px (phone) and 1180px (medium).

## Elevation & Depth

The page itself is flat: depth comes from rules and the ground/sheet tone step, not shadows. Shadows belong to things that float (dialogs, popovers, the selection bar, toasts) and to album art, which sits on the page like a printed cover.

### Shadow Vocabulary
- **Cover** (`0 1px 2px rgba(0,0,0,0.12), 0 10px 24px -10px rgba(0,0,0,0.35)`): the 200px album-header cover only.
- **Ambient** (`--shadow`: `0 1px 2px rgba(27,30,36,0.05), 0 10px 28px rgba(27,30,36,0.07)`): toasts and the editor's album-art square.
- **Lifted** (`--shadow-lg`: `0 24px 64px rgba(27,30,36,0.18)`; dark 0.6 black): dialogs, the selection bar, save-preview and suggestion popovers.
- **Segment** (`0 1px 3px rgba(0,0,0,0.12)`): the selected segment in toggles.

### Named Rules
**The Flat Page Rule.** Nothing in the reading flow (rows, folders, headers, fields) carries a shadow. If it's on the page, it's ruled; if it floats, it may lift.

## Shapes

Square and printed on the page, gently softened on things that float. Covers and thumbnails are near-square (2px; editor art 3px). Controls (buttons, inputs, icon buttons, crumbs) have small 6px corners; the genre chip 4px. Floating layers are softer: popovers and preview lists 10px, banners, cards and toasts 12px, the selection bar 14px, dialogs 16px (top corners only on phones). Filter and query chips are pills. Selection circles in the track list are round; option checkboxes are 5px squares.

Rules are part of the shape language: **1.5px solid ink** opens the track list, the folder list, each grid-view folder entry and the sign-in wordmark; **1px hairline** separates entries and editor groups.

### Named Rules
**The Ink Rule.** Every list starts under a 1.5px ink rule and separates its entries with 1px hairlines. Never box a list in a bordered card.

## Components

### Buttons
- **Shape:** small corners (6px), 34px tall (38px on phones), 0 14px padding, weight 600.
- **Primary:** solid ink fill and border, booklet-stock text. Hover mixes 16% spot into the ink. Disabled primary goes to the hover tint with faint text rather than fading.
- **Secondary:** sheet surface with a field-line border; hover/pressed use 4% / 7% ink tints. Danger variant uses danger text; destructive confirm uses a danger fill with `--on-color` text (white in light, booklet black in dark, since the dark status colours are light).
- **Icon button:** 32px (40px on phones), transparent, muted icon turning ink on hover. Icons are 18px inline SVG strokes at 1.6.
- **Press:** buttons scale to 0.97 on `:active`.

### Chips
- **Genre chip (signature):** 4px corners, 13px weight 700, spot text on a 13% spot tint. Shown in the album header only when every track shares one genre.
- **Filter chips:** pill, spot tint background, ink text, a 20px round remove button.

### Inputs / Fields
- **Default (dialogs, filter):** 36px tall, 6px corners, field-line border, input background; focus turns the border to spot with a 3px spot-tint ring.
- **Credit-line field (editor and sign-in):** no box at rest, just a field-line bottom border and 2px left inset, like a printed credit line. Hover darkens the line to ink; focus draws the full box in spot with 4px corners and the input background.
- **Changed:** spot border plus a 2px spot underline (inset shadow); the label's flag reads "changed" in spot. **Removed:** danger border on a danger tint.

### Track list (signature)
Rows a minimum of 48px under the ink rule, separated by hairlines. Track numbers are tabular, weight 600, muted, right-aligned; titles weight 600; artist/album muted. The row being edited takes a spot tint and turns its number and title spot; selected rows take a 10% spot tint. Off-screen rows use `content-visibility: auto` so huge folders stay fast.

### Folder list and grid
List view (default) is ruled rows like the track list, 48px, weight 600, with a muted count. **Grid view is a contents page**: each folder is a ruled entry (1.5px ink top rule, no box), 16px weight 700, whose rule turns spot on hover.

### Editor panel
500px sheet-white panel with a hairline left border: a header with the 19px title, a toolbar (Copy left; Save to folder and the ink Save right, with a hover/focus popover listing exactly what will be written), the album-art square, file facts, then collapsible groups whose heads are 14px weight 700 in spot. The activity log docks at the bottom with undo per entry.

### Navigation
Top bar with the wordmark (lowercase "codetta" plus a square full stop in spot, sized 0.29em). On phones the wordmark becomes a 30px spot square with a lowercase "c", breadcrumbs collapse to a single back link, and the filter field grows to fill the bar.

### Sign-in (booklet page)
No card: the 56px wordmark sits over a 1.5px ink rule on bare stock, followed by a 22px heading and credit-line fields with a 96px label column on desktop. The square uses house teal.

## Do's and Don'ts

### Do:
- **Do** derive every chromatic UI colour from `--spot` (`--accent`, `--accent-soft`, `--selected` via `color-mix`), and let the house teal stand in when there is no cover.
- **Do** open every list with a 1.5px ink rule and separate entries with 1px hairlines.
- **Do** set titles in Schibsted Grotesk 800 with negative tracking, and reserve tabular figures for track numbers.
- **Do** drop columns that would repeat the same value on every row of a single album.
- **Do** keep primary actions solid ink, 6px corners, and say what will happen ("Save to 5 tracks").
- **Do** use the motion tokens (120 / 200 / 260ms, ease-out in, ease-in out); phone sheets slide 340ms; the spot crossfades 700ms; all of it stops under `prefers-reduced-motion`.
- **Do** keep 16px inputs and 44px touch targets on phones, and honour safe-area insets.
- **Do** bundle every font and icon; no CDNs, no inline scripts or handler attributes (CSP).

### Don't:
- **Don't** add a second accent, a fixed brand blue, gradients or decorative colour; album art is the only full colour.
- **Don't** use raw cover colour for text or UI without `fitSpot()`.
- **Don't** box lists or rows in bordered cards, or put shadows on anything in the reading flow.
- **Don't** round covers or the logo's square beyond 2–3px.
- **Don't** extend the floating layer's softer corners (10–16px) to page-level surfaces.
- **Don't** add uppercase tracked section labels, kicker lines above titles, or text-glyph icons; use inline SVG. (Format codes such as FLAC in the small badge are data, not labels.)
