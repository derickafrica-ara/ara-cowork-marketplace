import type { EngineInterface, Register, ThemeSetArgs } from 'claude-code'

import { makeColors } from './make-colors.js'
import { SCENE } from './scene.js'

// Clay orange leads: peach-tinted ivory by day, burnt-clay browns by night,
// with ink-black text. Olive, amber and dusty blue keep code readable.
const { theme, problems } = makeColors({
  label: 'Papercut',
  roles: {
    accent: '#d97757',
    danger: '#b8343f',
    success: '#788c5d',
    warning: '#c8a04a',
    pro: '#6a9bcc',
  },
  light: {
    gray: {
      anchors: {
        'surface-0': '#f4e2d6',
        'surface-1': '#f8ebe2',
        'surface-2': '#fcf4ee',
        'text-primary': '#1f1410',
        'text-secondary': '#4a3128',
        'text-muted': '#6b4a3e',
      },
    },
  },
  dark: {
    gray: {
      anchors: {
        'surface-0': '#24150f',
        'surface-1': '#2e1b14',
        'surface-2': '#38221a',
        'surface-3': '#3c251c',
        'text-primary': '#f6ede6',
        'text-secondary': '#ead8cc',
        'text-muted': '#c8a999',
      },
    },
  },
})

const SCENE_NAME = 'papercut'

// The panels frost over the collage, so the orange shows through them.
const LOOK: ThemeSetArgs = {
  colors: theme,
  backdrop: { scene: SCENE_NAME, glass: { blur: 18, opacity: 0.74 } },
}

const HELP = ['/papercut on   turn the look on', '/papercut off  back to the app’s own look'].join('\n')

async function isLookOn($: EngineInterface): Promise<boolean> {
  return (await $.store.get('isLookOn')) !== false
}

async function applyLook($: EngineInterface): Promise<string> {
  const unpainted = problems.find(line => line.startsWith("Desktop won't paint"))

  if (unpainted !== undefined) {
    $.ui.toast(unpainted)
  }
  const set = await $.theme.set(LOOK)

  return set.isDrawn ? 'Papercut is on.' : `Papercut is set, but nothing draws it here: ${set.reason}`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'papercut',
      description: 'Clay-orange cut-paper look: on or off',
    })

    if (await isLookOn($)) {
      await applyLook($)
    }

    return next(e)
  })

  on('command.run', { command: 'papercut' }, async ($, e) => {
    const args = e.args.trim().toLowerCase()

    if (args === 'on') {
      await $.store.set('isLookOn', true)

      return { text: await applyLook($) }
    }
    if (args === 'off') {
      await $.store.set('isLookOn', false)
      await $.theme.clear()

      return { text: 'Papercut is off. /papercut on brings it back.' }
    }

    return { text: HELP }
  })

  on('ui.render', { component: 'Backdrop' }, ($, e, next) => {
    const isOurs = e.props.plugin === $.plugin.name && e.props.scene === SCENE_NAME
    const isAppSurface = e.surface === 'desktop' || e.surface === 'mobile'

    if (!isOurs || !isAppSurface) {
      return next(e)
    }

    const { Svg } = $.ui.resolve(e)

    return (
      <Svg
        source={SCENE}
        alt="A cut-paper collage on clay orange: ivory shapes, hand-drawn ink threads and an ink bloom"
        isInteractive
      />
    )
  })
}
