[← Back to the README](../README.md)

# Translating Codetta

Codetta's page speaks **English** and **Spanish (Español)**. It follows each
browser's language, and **Settings → General → Language** picks another one for that
browser. Your music is never translated: titles, artists, albums, folder names
and tag values always show exactly as they are in your files.

The Spanish was drafted by the Codetta team. If a word sounds off, or you'd
like to add your language, you're very welcome to help.

## Fix a translation

Translations live in one file per language in
[`src/codetta/web/static/i18n/`](../src/codetta/web/static/i18n/), for example
`es.json`. Each line pairs Codetta's English text with its translation:

```json
"Moved to “{x}”": "Movido a “{x}”",
```

- Change only the part on the right.
- Keep everything in `{curly braces}` exactly as it is: those are names and
  numbers Codetta fills in. You can move them around in the sentence.
- Brand names (MusicBrainz, Soulseek, Navidrome…) and settings named after
  other apps' menus (Lidarr's "Settings → Metadata") stay as they are.

Open a pull request with your change, or open an issue with the label
**translation** if you'd rather just describe it.

## Add a language

1. Copy `es.json` to your language's two-letter code, like `fr.json` or
   `de.json`, and change `meta.name` to the language's own name ("Français").
2. Translate the right-hand side of every line. The `words` section holds
   counted words, singular then plural: `"track": ["piste", "pistes"]`.
3. Add the code and name to `LANGUAGES` at the top of
   [`js/i18n.js`](../src/codetta/web/static/js/i18n.js).
4. Run `pytest tests/test_i18n.py`. It checks every line is translated and that
   no `{name}` went missing.

A partly translated file works too: lines left as `""` show in English.

## For maintainers: new texts

When the page or the server gets new texts, refresh every catalog:

```sh
npm install --no-save acorn          # once
node tools/i18n-extract.mjs > /tmp/page.json
python tools/i18n.py /tmp/page.json  # adds new texts as "", drops old ones
python tools/i18n.py --missing es    # what's left to translate
```

How it works: the page is written in English, and `js/i18n.js` swaps each text
for its translation as it appears on screen (exact texts, plus patterns for
texts with names or numbers in them). Anything inside `translate="no"` is left
alone, and `h()` adds that to every element marked `dir="auto"`, which is how
Codetta marks your own text. The changelog (What's new), the docs and the
server log stay in English.
