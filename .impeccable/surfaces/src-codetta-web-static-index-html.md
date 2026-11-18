---
version: 1
slug: "src-codetta-web-static-index-html"
primary_target: "src/codetta/web/static/index.html"
related_targets: ["src/codetta/web/static/app.css","src/codetta/web/static/app.js"]
---

# Surface: Codetta app (sign-in, library, search, editor, dialogs)

Mode: Operate. One app shell: top bar, library/album/search view, editor panel (phone: full-screen sheet), dialogs, sign-in. Users: homelab owners fixing tags on desktop and phone equally (PRODUCT.md). Structure stays easy to understand (user: "keep the easy to understand structure, but feel free to take interesting design changes that make the site pop"); identity should be felt most in sign-in, library/album views and the editor. Must not feel generic/corporate, gimmicky, dark-and-nerdy, or cute.

## Direction contract

THESIS: Codetta reads like the credits pages of a beautifully made CD/LP booklet: every track gets the credits page it deserves. Refuses the category default of a grey dashboard with one blue accent and a generic data table.

OWN-WORLD: Booklet stock (near-white, faintly cool) and ink, one display-grade grotesque (Schibsted Grotesk, heavy and tight for titles, regular for credits); hairline rules between credit lines; numbered tracks "01"; one spot colour per album lifted from its cover (house spot teal when there is none), used for the active track, changed fields and the album's genre chip. Album art is the only full colour. Lowercase "codetta" wordmark with a square spot mark.

STORY: The visitor recognises their album as a booklet spread, sees exactly what is credited, changes a line, and Saves; confidence comes from the calm, exact typesetting.

FIRST VIEWPORT: Slim top bar (wordmark left, breadcrumbs, search right). Album view: large cover (200px) beside a heavy 52px title, artist/year/count line and spot-colour genre chip; numbered track list with hairlines; editor on the right as a credits sheet (label column + value with hairline), Save as solid ink button. Phone: same booklet order, editor as a full sheet.

FORM: Liner Notes, Impeccable's pick (my list position 1), seed:5675e23ec6ca6e2a. Signature move: per-album spot colour taken from the cover art, carried into the active track, changed fields, genre chip and the editor's section heads.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
