import type { ThemeSetArgs } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const BACKDROP = {
  plugin: 'papercut',
  component: 'Backdrop',
  requestId: 'backdrop',
  props: { scene: 'papercut', plugin: 'papercut', glass: { blur: 18, opacity: 0.74 } },
} as const

test('session start sets the orange palette and the collage', async ($, on) => {
  mock.store(on)
  const sets: ThemeSetArgs[] = []
  on('command.register', () => ({ value: { command: 'papercut' } }))
  on('theme.set', (_, e) => {
    sets.push(e)

    return { value: { isDrawn: true, requestId: 'backdrop' } }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  expect(sets.length).toBe(1)
  expect(sets[0]?.colors?.label).toBe('Papercut')
  expect(sets[0]?.backdrop).toEqual({ scene: 'papercut', glass: { blur: 18, opacity: 0.74 } })
})

test('the collage draws on the apps and leaves other backdrops alone', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })

  for (const surface of ['desktop', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...BACKDROP, surface })
    expect(await ui.find({ type: 'Svg' })).toBeDefined()
    await ui.unmount()
  }

  const other = await $.ui.mount({
    ...BACKDROP,
    props: { ...BACKDROP.props, plugin: 'woodgrain', scene: 'woodgrain' },
    surface: 'desktop',
  })
  expect((await other.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  await other.unmount()
})

test('/papercut off clears the look, and the next session stays plain', async ($, on) => {
  mock.store(on)
  let cleared = 0
  let sets = 0
  on('command.register', () => ({ value: { command: 'papercut' } }))
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
    command: 'papercut',
    args: 'off',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 80 },
  })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  expect(text).toBe('Papercut is off. /papercut on brings it back.')
  expect(cleared).toBe(1)
  expect(sets).toBe(0)
})
