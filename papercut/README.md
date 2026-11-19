# Papercut

A Claude Code mod that gives the desktop and mobile apps a clay-orange,
cut-paper look.

- **Colors:** every page, panel, text shade and accent is recolored, with
  peach-tinted ivory by day and burnt-clay browns by night, ink-black text and a
  clay-orange accent. Olive, amber and dusty blue keep code highlighting
  readable.
- **Background:** a collage behind the conversation on a speckled clay-orange
  ground. Ivory paper shapes (a circle, square, diamond and triangle) have
  hand-cut edges and soft shadows, with darker orange paper layered underneath.
  Two hand-drawn ink threads draw themselves in when the app opens, an ink bloom
  inside the large paper circle turns very slowly, and small paper confetti
  drifts. The chat panels frost over it, so the orange shows through.
- **Phones** get a lighter arrangement, and reduced-motion settings get a still
  version of the scene.

The terminal and IDE extensions don't draw themes, and permission prompts keep
the app's own look.

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install papercut --marketplace derickafrica-ara/ara-cowork-marketplace
```

Answer `y` to add the marketplace if asked, then pick a scope (user scope loads
it in every session).

From a shell:

```
claude plugin install papercut --marketplace derickafrica-ara/ara-cowork-marketplace
```

In the desktop app, where `/plugin` does not run: click **+** next to the
prompt box, then **Plugins**, **Add marketplace** with
`derickafrica-ara/ara-cowork-marketplace`, then **Add plugin**.

Only one theme shows at a time. If another theme mod (such as `woodgrain`) is
also installed, turn it off (`/woodgrain off`) while using Papercut.

## Commands

| Command | What it does |
| --- | --- |
| `/papercut on` | Turn the look on |
| `/papercut off` | Go back to the app's own look (remembered across sessions) |

## Changing the scene

The background is generated. Edit `scripts/gen_papercut.py` (palette, shapes,
ink threads, bloom) and regenerate:

```
python3 scripts/gen_papercut.py hooks /tmp
```

That rewrites `hooks/scene.js` and writes a light and dark `preview-*.svg` to
`/tmp`. The app colors live in `hooks/register.tsx`. `hooks/make-colors.js` is
Claude Code's own palette helper; leave it as it is.

From this folder, run the tests with `claude plugin test .` and check the mod
with `claude plugin validate .`.
