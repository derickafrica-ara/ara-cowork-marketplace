# Woodgrain

A Claude Code mod that gives the desktop and mobile apps a late-1970s
home-console look, in warm clay, ivory and slate tones.

- **Colors:** every page, panel, text shade and accent is recolored, with a
  clay-orange accent, dusty blue and olive green, in both light and dark mode.
  Code highlighting follows the same palette.
- **Background:** a chunky pixel-art scene with CRT scanlines behind the
  conversation. A banded sky has a clay-orange pixel sunburst and drifting
  clouds by day, and stars by night. Below are stepped mountains, striped
  ground, a woodgrain strip and "PLAYER 1" in pixel lettering. A small saucer
  drifts slowly across the sky.
- **Chime:** a short two-note 8-bit blip when a reply finishes (macOS only).

The terminal and IDE extensions don't draw themes, and permission prompts keep
the app's own look. Text stays in the app's normal font.

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install woodgrain --marketplace derickafrica-ara/ara-cowork-marketplace
```

Answer `y` to add the marketplace, then pick a scope (user scope loads it in
every session).

From a shell:

```
claude plugin install woodgrain --marketplace derickafrica-ara/ara-cowork-marketplace
```

In the desktop app, where `/plugin` does not run: click **+** next to the
prompt box, then **Plugins**, **Add marketplace** with
`derickafrica-ara/ara-cowork-marketplace`, then **Add plugin**.

## Commands

| Command | What it does |
| --- | --- |
| `/woodgrain on` | Turn the look on |
| `/woodgrain off` | Go back to the app's own look (remembered across sessions) |
| `/woodgrain sound on` | Play the chime when a reply finishes |
| `/woodgrain sound off` | Silence the chime |

## Changing the scene

The background is generated. Edit `scripts/gen_scene.py` (palette, sky bands,
sprites) and regenerate:

```
python3 scripts/gen_scene.py hooks /tmp
```

That rewrites `hooks/scene.js` and writes a light and dark `preview-*.svg` to
`/tmp`. The app colors live in `hooks/register.tsx`. `hooks/make-colors.js` is
Claude Code's own palette helper; leave it as it is.

From this folder, run the tests with `claude plugin test .` and check the mod
with `claude plugin validate .`.
