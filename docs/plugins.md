# Writing a Codetta plugin

A plugin adds **actions** to Codetta: batch changes to tags that people can run
on a folder, a selection or search results. Codetta does the rest: it shows a
preview of every change, writes each file safely (temp copy → check → swap),
logs one entry in Activity and makes it undoable.

Codetta's own built-in actions ("Clean up titles", "Title Case"…) are written
this way, in [`src/codetta/plugins/builtin/tidy.py`](../src/codetta/plugins/builtin/tidy.py).
It's the best example to start from.

## The smallest plugin

Make a folder in your config folder's `plugins/` (in Docker that's
`/config/plugins/`) with two files.

`plugins/shout/plugin.json`

```json
{
  "id": "shout",
  "name": "Shout",
  "version": "1.0",
  "description": "Upper-case titles.",
  "author": "Your name",
  "url": "https://github.com/you/codetta-shout",
  "api": 1
}
```

`plugins/shout/plugin.py`

```python
def setup(codetta):
    codetta.add_action(
        id="upper",
        label="UPPERCASE titles",
        description="Make every title upper case.",
        fields=["title"],
        run=lambda tags: {"title": [t.upper() for t in tags.get("title", [])]},
    )
```

Reload the page, open **Account → Plugins** and switch it on. "UPPERCASE
titles" now shows in **Actions**.

## How actions work

`run(tags)` is called once for each chosen track.

- `tags` maps lower-case tag names (`title`, `artist`, `album`, `albumartist`,
  `tracknumber`, `date`, `genre`, …: see
  [`tagmap.py`](../src/codetta/core/tagmap.py)) to **lists of strings**.
  A tag with two values (two artists) is a list of two.
- Return a dict of only the tags you want to change. A value can be a list of
  strings, one string, or `None` / `[]` to remove the tag. Return `None` or
  `{}` to leave the track alone.
- `run` gets a copy, so changing `tags` itself does nothing.
- Don't open, write or move files in `run`. Codetta does the writing, which is
  what makes preview and undo work.
- `run` runs on the server, possibly for thousands of tracks, so keep it quick
  and don't call the internet from it.

If `run` raises an error, the person sees "*Your action* failed: …" and
nothing is written.

## plugin.json

| Key | |
|---|---|
| `id` | Required. Lower-case letters, numbers, `-` and `_`, up to 40. Must be unique. |
| `name` | Shown in Account → Plugins. |
| `version`, `description`, `author`, `url` | Shown to people. `url` must be `https://`. |
| `entry` | The Python file to load. Default `plugin.py`. It must be inside the plugin's folder. |
| `api` | The plugin API version you wrote against. Currently `1`. A plugin asking for a newer one is listed but not loaded. |

`setup(codetta)` is called once when the plugin is switched on (and when
Codetta starts, if it's on). `codetta.add_action(...)` takes:

| Argument | |
|---|---|
| `id` | Letters, numbers, `-` and `_`. The full id becomes `<plugin id>.<id>`. |
| `label` | The button text, up to 60 characters. |
| `description` | One sentence: what changes. |
| `fields` | The tags it reads or changes, shown to people. |
| `run` | The function described above. |

`codetta.api_version` tells you which API you're running on. New things will
only ever be added to it in ways that keep existing plugins working; if that
can't be done, `api` goes up.

## Safety and trust

- Plugins are **off until someone turns them on**. Codetta lists a plugin
  folder without running any of its code.
- A plugin that fails to load (a syntax error, a missing `setup`, an error
  while starting) is shown with its error in Account → Plugins. Codetta keeps
  running.
- Once on, a plugin is ordinary Python running on the server with Codetta's
  permissions. It is not sandboxed. Say plainly in your README what your
  plugin does, and keep it to changing tags through `run`.
- Plugins must respect Codetta's [privacy promise](../PRIVACY.md): no
  tracking, and no network calls the person didn't ask for.

## Sharing your plugin

Put the plugin folder in a Git repository with a README saying what it does
and showing a before → after example. People install it by copying (or
`git clone`-ing) the folder into `config/plugins/`. Open an issue on Codetta
with the label `plugin` to have it listed.

If your action would be useful to almost everyone, consider sending it as a
pull request to the built-in `tidy.py` instead.
