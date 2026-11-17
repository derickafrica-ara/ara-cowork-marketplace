import type { ThemeSetArgs } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const BACKDROP = {
  plugin: 'woodgrain',
  component: 'Backdrop',
  requestId: 'backdrop',
  props: { scene: 'woodgrain', plugin: 'woodgrain', glass: { blur: 6, opacity: 0.78 } },
} as const

test('session start sets the palette and the pixel scene', async ($, on) => {
  mock.store(on)
  const sets: ThemeSetArgs[] = []
  on('command.register', () => ({ value: { command: 'woodgrain' } }))
  on('theme.set', (_, e) => {
    sets.push(e)

    return { value: { isDrawn: true, requestId: 'backdrop' } }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  expect(sets.length).toBe(1)
  expect(sets[0]?.colors?.label).toBe('Woodgrain')
  expect(sets[0]?.backdrop).toEqual({ scene: 'woodgrain', glass: { blur: 6, opacity: 0.78 } })
})

test('the scene draws on the apps and leaves other surfaces alone', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })

  for (const surface of ['desktop', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...BACKDROP, surface })
    const svg = await ui.find({ type: 'Svg' })
    expect(svg).toBeDefined()
    await ui.unmount()
  }

  const other = await $.ui.mount({
    ...BACKDROP,
    props: { ...BACKDROP.props, plugin: 'someone-else' },
    surface: 'desktop',
  })
  expect((await other.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  await other.unmount()
})

test('/woodgrain off clears the look, and the next session stays plain', async ($, on) => {
  mock.store(on)
  let cleared = 0
  let sets = 0
  on('command.register', () => ({ value: { command: 'woodgrain' } }))
  on('theme.set', () => {
    sets += 1

    return { value: { isDrawn: true, requestId: 'backdrop' } }
  })
  on('theme.clear', () => {
    cleared += 1

    return { value: { isDrawn: false, reason: 'cleared' } }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  const { text } = await $.command.run({
    command: 'woodgrain',
    args: 'off',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 80 },
  })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  expect(text).toBe('Woodgrain is off. /woodgrain on brings it back.')
  expect(cleared).toBe(1)
  expect(sets).toBe(0)
})
