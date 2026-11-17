import type { EngineInterface, Register, ThemeSetArgs } from 'claude-code'

import { makeColors } from './make-colors.js'
import { SCENE } from './scene.js'

// Warm ivory and slate neutrals with a clay-orange accent, dusty blue and
// olive green. The design system keeps each role's hue and tunes its
// lightness, so text stays readable.
const { theme, problems } = makeColors({
  label: 'Woodgrain',
  roles: {
    accent: '#d97757',
    danger: '#b5423c',
    success: '#788c5d',
    warning: '#c8a04a',
    pro: '#6a9bcc',
  },
  light: {
    gray: {
      anchors: {
        'surface-0': '#f0eee6',
        'surface-1': '#f5f4ee',
        'surface-2': '#faf9f5',
        'text-primary': '#141413',
        'text-secondary': '#3d3d3a',
        'text-muted': '#5e5d59',
      },
    },
  },
  dark: {
    gray: {
      anchors: {
        'surface-0': '#141413',
        'surface-1': '#1c1c1a',
        'surface-2': '#242422',
        'surface-3': '#2a2a27',
        'text-primary': '#faf9f5',
        'text-secondary': '#e8e6dc',
        'text-muted': '#b0aea5',
      },
    },
  },
})

const SCENE_NAME = 'woodgrain'

const LOOK: ThemeSetArgs = {
  colors: theme,
  backdrop: { scene: SCENE_NAME, glass: { blur: 6, opacity: 0.78 } },
}

const HELP = [
  '/woodgrain on        turn the look on',
  '/woodgrain off       back to the app’s own look',
  '/woodgrain sound on  play the chime when a turn ends',
  '/woodgrain sound off silence the chime',
].join('\n')

async function isEnabled($: EngineInterface, key: string): Promise<boolean> {
  return (await $.store.get(key)) !== false
}

async function applyLook($: EngineInterface): Promise<string> {
  const unpainted = problems.find(line => line.startsWith("Desktop won't paint"))

  if (unpainted !== undefined) {
    $.ui.toast(unpainted)
  }
  const set = await $.theme.set(LOOK)

  return set.isDrawn ? 'Woodgrain is on.' : `Woodgrain is set, but nothing draws it here: ${set.reason}`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'woodgrain',
      description: 'Retro console look: on, off, sound on, sound off',
    })

    if (await isEnabled($, 'isLookOn')) {
      await applyLook($)
    }

    return next(e)
  })

  on('command.run', { command: 'woodgrain' }, async ($, e) => {
    const args = e.args.trim().toLowerCase()

    if (args === 'on') {
      await $.store.set('isLookOn', true)

      return { text: await applyLook($) }
    }
    if (args === 'off') {
      await $.store.set('isLookOn', false)
      await $.theme.clear()

      return { text: 'Woodgrain is off. /woodgrain on brings it back.' }
    }
    if (args === 'sound on' || args === 'sound off') {
      await $.store.set('isSoundOn', args === 'sound on')

      return { text: `Chime ${args === 'sound on' ? 'on' : 'off'}.` }
    }

    return { text: HELP }
  })

  // A short two-note chime when the main conversation finishes a turn.
  on('turn.complete', async ($, e, next) => {
    const isMainAnswer = e.agentId === undefined && e.reason === 'answer'

    if (isMainAnswer && (await isEnabled($, 'isLookOn')) && (await isEnabled($, 'isSoundOn'))) {
      void $.audio.play({ asset: 'sounds/done.wav' }, { gain: 0.6 }).catch(() => undefined)
    }

    return next(e)
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
        alt="A pixel-art sky with a clay-orange sunburst over blocky mountains, and a slow saucer drifting past"
        isInteractive
      />
    )
  })
}
