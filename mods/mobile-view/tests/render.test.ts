import { describe, expect, mock, test } from 'claude-code/testing'

import { clockTime } from '../hooks/format'

import {
  ENV,
  SESSION,
  TRANSCRIPT,
  assistantMessage,
  command,
  elementsOf,
  helperJson,
  pane,
  promptHint,
  stampOf,
  textOf,
  toolGroup,
  toolResult,
  toolUse,
  userMessage,
  worldOf,
} from './fixtures/world'

const PLUGIN = 'mobile-view'

/** Starts a session with a world beneath it, a mocked clock and store, and an indexed transcript. */
async function started($: any, on: any, titles: string[] = [], stored: Record<string, unknown> = {}) {
  const world = worldOf(on)
  const clock = mock.clock(on)
  for (const [key, value] of Object.entries(stored)) {
    world.store.set(key, value)
  }
  on('classic.SessionStart', () => ({}) as never)
  world.helperStdout = helperJson(titles)
  world.files.set(TRANSCRIPT, 'x'.repeat(100))
  await $.session.start(SESSION)
  await $.classic.SessionStart({ source: 'resume', transcript_path: TRANSCRIPT })
  await clock.advance(10)
  return { world, clock }
}

/** Types `key` into the prompt box holding `text`, caret at its end, and lets the clock run. */
async function typed($: any, clock: any, key: string, text = '') {
  const box = await $.prompt.edit({ origin: { kind: 'composer' }, text, cursor: text.length, start: text.length, end: text.length, inputText: key })
  await clock.advance(10)
  return box
}

const edit = toolUse('t1', 'Edit', { file_path: 'C:/work/src/a.ts', old_string: 'one', new_string: 'two' })

describe('session start', () => {
  test('registers /mobile-view only', async ($, on) => {
    const { world } = await started($, on)
    expect(world.commands).toEqual(['mobile-view'])
  })

  test('indexes the transcript with the helper, isolated, from the kit folder', async ($, on) => {
    const { world } = await started($, on, ['first'])
    expect(world.runs.at(-1)).toEqual([ENV.MOBILE_VIEW_PYTHON, '-I', '-X', 'utf8', ENV.MOBILE_VIEW_PROMPTS, '--transcript', TRANSCRIPT])
  })
})

describe('tool rows', () => {
  test('a standalone call is one line and its result is hidden until opened', async ($, on) => {
    await started($, on)
    const row = await $.ui.render(edit)
    expect(textOf(row)).toContain('\u25cf Edit  src/a.ts  +1 \u22121')
    expect(textOf(row)).not.toContain('ENGINE')
    const hidden = await $.ui.render(toolResult('t1', 'Edit'))
    expect(textOf(hidden)).toBe('')
    expect(elementsOf(hidden, 'Box')[0]?.props).toMatchObject({ display: 'none' })

    await $.ui.press({ plugin: PLUGIN, key: 'call:t1' })
    const open = await $.ui.render(edit)
    expect(textOf(open)).toContain('\u25be Edit')
    expect(textOf(open)).toContain('ENGINE ToolUse')
    expect(textOf(await $.ui.render(toolResult('t1', 'Edit')))).toContain('ENGINE ToolResult')

    await $.ui.press({ plugin: PLUGIN, key: 'call:t1' })
    expect(textOf(await $.ui.render(edit))).not.toContain('ENGINE')
  })

  test('a group lists each call with failures marked, and a press unfolds it', async ($, on) => {
    await started($, on)
    const group = toolGroup([
      { id: 'b1', tool: 'Bash', input: { command: 'adb shell input swipe', description: 'Swipe up, look for the wake prompt' }, isErrored: true, output: 'Error: Exit code 1' },
      { id: 'r1', tool: 'Read', input: { file_path: 'C:/work/src/MorningCard.tsx' } },
    ])
    const folded = textOf(await $.ui.render(group))
    expect(folded).toContain('\u25cf Bash  Swipe up, look for the wake prompt  \u2717 exit 1')
    expect(folded).toContain('\u25cf Read  src/MorningCard.tsx')

    await $.ui.press({ plugin: PLUGIN, key: 'call:r1' })
    const open = textOf(await $.ui.render(group))
    expect(open).toContain('fold 2 calls')
    expect(open).toContain('ENGINE ToolGroup {"isExpanded":true}')
    // The unfolded calls draw as ToolUse rows with their output, as the person asked.
    expect(textOf(await $.ui.render(toolUse('r1', 'Read', { file_path: 'C:/work/src/MorningCard.tsx' })))).toContain('ENGINE ToolUse')
  })

  test('a one-call group opens straight to its call, which folds it again', async ($, on) => {
    await started($, on)
    const group = toolGroup([{ id: 'b1', tool: 'Bash', input: { command: 'exit 3' }, isErrored: true, output: 'Error: Exit code 3' }])
    await $.ui.render(group)
    await $.ui.press({ plugin: PLUGIN, key: 'call:b1' })
    const open = textOf(await $.ui.render(group))
    expect(open).toBe('ENGINE ToolGroup {"isExpanded":true}')
    const call = toolUse('b1', 'Bash', { command: 'exit 3' }, { isErrored: true })
    expect(textOf(await $.ui.render(call))).toContain('ENGINE ToolUse')
    await $.ui.press({ plugin: PLUGIN, key: 'call:b1' })
    expect(textOf(await $.ui.render(group))).toContain('\u25cf Bash  exit 3  \u2717 exit 3')
    expect(textOf(await $.ui.render(edit))).not.toContain('ENGINE')
  })

  test('folding one call of an opened group keeps the mobile view (it is not ctrl+o)', async ($, on) => {
    await started($, on)
    const calls = [
      { id: 'r1', tool: 'Read', input: { file_path: 'C:/work/a.ts' } },
      { id: 'r2', tool: 'Read', input: { file_path: 'C:/work/b.ts' } },
    ]
    await $.ui.render(toolGroup(calls))
    await $.ui.press({ plugin: PLUGIN, key: 'call:r1' })
    const first = toolUse('r1', 'Read', { file_path: 'C:/work/a.ts' })
    await $.ui.render(first)
    await $.ui.press({ plugin: PLUGIN, key: 'call:r1', requestId: 'r1' })
    const folded = textOf(await $.ui.render(first))
    expect(folded).toContain('\u25cf Read  a.ts')
    expect(folded).not.toContain('ENGINE')
    expect(textOf(await $.ui.render(edit))).not.toContain('ENGINE')
  })

  test('a long group counts the rest', async ($, on) => {
    await started($, on)
    const calls = Array.from({ length: 11 }, (_, i) => ({ id: `r${i}`, tool: 'Read', input: { file_path: `C:/work/f${i}.ts` } }))
    const text = textOf(await $.ui.render(toolGroup(calls)))
    expect(text).toContain('f7.ts')
    expect(text).not.toContain('f8.ts')
    expect(text).toContain('\u2026 +3 more')
  })

  test('an expanded group, plan and question tools, and other surfaces are left to the engine', async ($, on) => {
    await started($, on)
    expect(textOf(await $.ui.render(toolGroup([{ id: 'x', tool: 'Read', input: {} }], true)))).toContain('ENGINE ToolGroup')
    expect(textOf(await $.ui.render(toolUse('p1', 'ExitPlanMode', { plan: 'x' })))).toContain('ENGINE ToolUse')
    expect(textOf(await $.ui.render(toolUse('p2', 'AskUserQuestion', {})))).toContain('ENGINE ToolUse')
    expect(textOf(await $.ui.render({ ...edit, surface: 'mobile' as never }))).toContain('ENGINE ToolUse')
  })
})

describe('messages', () => {
  const code = ['Here is the script:', '```python', ...Array.from({ length: 30 }, (_, i) => `print(${i})`), '```', 'Run it.'].join('\n')

  test('a long code block is folded, and the button shows it', async ($, on) => {
    await started($, on)
    const folded = textOf(await $.ui.render(assistantMessage('m1', code)))
    expect(folded).toContain('\u25b8 python \u00b7 30 lines hidden')
    expect(folded).not.toContain('print(29)')
    expect(folded).toContain('show code (1 block, 30 lines)')

    await $.ui.press({ plugin: PLUGIN, key: 'code' })
    const open = textOf(await $.ui.render(assistantMessage('m1', code)))
    expect(open).toContain('print(29)')
    expect(open).toContain('hide code')
  })

  test('prose without long code is untouched', async ($, on) => {
    await started($, on)
    const text = textOf(await $.ui.render(assistantMessage('m2', 'The morning question is there. I will answer it.')))
    expect(text).toBe('ENGINE AssistantMessage {"text":"The morning question is there. I will answer it."}')
  })

  test('prompts carry their number; ctrl+o (isExpanded) shows everything in full', async ($, on) => {
    await started($, on, ['first', 'second'])
    expect(textOf(await $.ui.render(userMessage('u2', 'second')))).toContain('"text":"#2  second"')

    const full = textOf(await $.ui.render(userMessage('u2', 'second', true)))
    expect(full).toContain('"text":"second"')
    expect(textOf(await $.ui.render(edit))).toContain('ENGINE ToolUse')

    await $.ui.render(userMessage('u2', 'second', false))
    expect(textOf(await $.ui.render(edit))).not.toContain('ENGINE')
  })
})

describe('mode', () => {
  test('/mobile-view off draws everything as stock and is remembered', async ($, on) => {
    const { world } = await started($, on)
    await $.command.run(command('mobile-view', 'off'))
    expect(textOf(await $.ui.render(edit))).toContain('ENGINE ToolUse')
    expect(world.toasts.at(-1)).toContain('off')
    expect(world.store.get('mode')).toBe('full')

    await $.command.run(command('mobile-view', 'on'))
    expect(textOf(await $.ui.render(edit))).not.toContain('ENGINE')
  })

  test('a session starts in the mode the person left it in', async ($, on) => {
    await started($, on, [], { mode: 'full' })
    expect(textOf(await $.ui.render(edit))).toContain('ENGINE ToolUse')
    expect(textOf(await $.ui.render(toolResult('t1', 'Edit')))).toContain('ENGINE ToolResult')
  })
})

describe('questions', () => {
  test('. in an empty prompt opens a focused pane listing every prompt; the footer says so', async ($, on) => {
    const { world, clock } = await started($, on, ['how does the kit work', 'make it like the mobile app'])
    expect(textOf(await $.ui.render(promptHint()))).toContain('"tail":". for questions"')
    // Only while `.` would open it: not over a draft.
    expect(textOf(await $.ui.render(promptHint(true)))).not.toContain('for questions')
    expect(await typed($, clock, '.')).toEqual({ text: '', cursor: 0 })
    expect(world.opened.at(-1)).toEqual({ id: 'questions', focus: true, closeOnEscape: true })
    // While the list is open the hint is left out (the docked list also narrows the prompt's row).
    expect(textOf(await $.ui.render(promptHint(false, 100)))).not.toContain('for questions')
    const text = textOf(await $.ui.render(pane(90)))
    expect(text).toContain('type to filter · ↑↓ choose · Enter jumps · Esc back · 2 questions')
    expect(text).toContain('how does the kit work')
    expect(text).toContain('#2 ')
  })

  test('. after text is typed as usual', async ($, on) => {
    const { world, clock } = await started($, on, ['one'])
    expect(await typed($, clock, '.', 'a ')).toEqual({ text: 'a .', cursor: 3 })
    expect(world.opened).toEqual([])
  })

  test('there is no /questions command, and the stock view has no . door or footer line', async ($, on) => {
    const { world, clock } = await started($, on, [], { mode: 'full' })
    expect(world.commands).toEqual(['mobile-view'])
    expect(textOf(await $.ui.render(promptHint()))).not.toContain('for questions')
    expect(await typed($, clock, '.')).toEqual({ text: '.', cursor: 1 })
    expect(world.opened).toEqual([])
    await $.command.run(command('mobile-view', 'on'))
    expect(textOf(await $.ui.render(promptHint()))).toContain('. for questions')
  })

  test('where a key alone cannot place the pane, . is typed and Enter on it opens the list', async ($, on) => {
    const { world, clock } = await started($, on, ['one'])
    world.isPlaceable = false
    expect(await typed($, clock, '.')).toEqual({ text: '.', cursor: 1 })
    expect(world.closed).toEqual(['questions'])
    expect(world.toasts.at(-1)).toBe('Press Enter to open your questions; after that, . alone opens them')
    // The footer now says to press Enter, until the list opens.
    expect(textOf(await $.ui.render(promptHint(false, 137)))).toContain('"tail":". then Enter for questions"')

    world.isPlaceable = true
    expect(await $.prompt.submit({ text: ' . ' })).toEqual({ drop: 'Questions opened' })
    await clock.advance(10)
    expect(world.opened.at(-1)).toEqual({ id: 'questions', focus: true, closeOnEscape: true })
    expect(world.fills).toEqual([''])

    // Under 110 columns even an asked-for pane needs Enter each time; the toast says so.
    world.isPlaceable = false
    await $.ui.render(promptHint(false, 100))
    await typed($, clock, '.')
    expect(world.toasts.at(-1)).toBe('Press Enter to open your questions (. alone needs a terminal 110 columns wide)')
  })

  test('typing filters the list (< is only text); the next open starts unfiltered', async ($, on) => {
    const { world, clock } = await started($, on, ['fix the icon', 'build the apk', 'ship the icon'])
    await typed($, clock, '.')
    await $.ui.render(pane(90))
    await $.ui.input({ plugin: PLUGIN, key: 'filter', text: 'icon', kind: 'change' })
    const narrowed = textOf(await $.ui.render(pane(90)))
    expect(narrowed).toContain('fix the icon')
    expect(narrowed).not.toContain('build the apk')
    expect(narrowed).toContain('2 of 3')
    await $.ui.input({ plugin: PLUGIN, key: 'filter', text: '#2', kind: 'change' })
    expect(textOf(await $.ui.render(pane(90)))).toContain('build the apk')

    // `<` is only text now (Esc goes back); the next open starts unfiltered.
    await $.ui.input({ plugin: PLUGIN, key: 'filter', text: '<', kind: 'change' })
    expect(world.closed).toEqual([])
    await typed($, clock, '.')
    expect(textOf(await $.ui.render(pane(90)))).toContain('3 questions')
  })

  test('Enter in the field jumps to the newest question it keeps', async ($, on) => {
    const { world, clock } = await started($, on, ['fix the icon', 'build the apk', 'ship the icon'])
    await typed($, clock, '.')
    await $.ui.render(pane(90))
    await $.ui.input({ plugin: PLUGIN, key: 'filter', text: 'icon' })
    expect(world.toasts.at(-1)).toMatch(/^Can't jump to #3 /)
    await $.ui.input({ plugin: PLUGIN, key: 'filter', text: 'nothing like it' })
    expect(world.toasts.at(-1)).toBe('No question matches "nothing like it"')
  })

  // The kit does not model a plugin moving a site's ring (it answers "no implementation"), so the
  // engine moves it here; the mod's own move to the field is checked in a real terminal.
  test('the row holding the focus ring is marked', async ($, on) => {
    const { clock } = await started($, on, ['one', 'two'])
    await typed($, clock, '.')
    await $.ui.focus({ component: 'Pane', requestId: 'questions', key: 'q:u2', element: 'q:u2', origin: 'person' } as never)
    expect(textOf(await $.ui.render(pane()))).toContain('❯ #2 ')

    await $.ui.focus({ component: 'Pane', requestId: 'questions', key: 'q:u1', element: 'q:u1', origin: 'person' } as never)
    const moved = textOf(await $.ui.render(pane()))
    expect(moved).toContain('❯ #1 ')
    expect(moved).not.toContain('❯ #2 ')

    // Without the keyboard the pane marks nothing and says how to take it, under the newest question.
    const idle = textOf(await $.ui.render(pane(70, false)))
    expect(idle).not.toContain('❯')
    // Questions show local time, so the expected clock follows this machine's zone.
    const asked = clockTime(stampOf(1))
    expect(idle).toMatch(new RegExp(`#2 ${asked} two.*ctrl\\+x tab \\(or a click\\) to choose · Esc closes · 2 questions$`))
  })

  // In a list taller than the pane Claude Code spends ↑↓ on scrolling the body and leaves the ring where it
  // was; the arrow (a one-row scroll with no pointer) moves the choice instead. The kit sends a pane's own
  // $.ui.focus and $.ui.scroll to the engine alone, which it does not model, so these check the choice the
  // list draws; the ring and the window following it are checked in a real terminal.
  const arrow = (by: number) => ({ component: 'Pane', requestId: 'questions', by, offset: 0, bodyRows: 3, contentRows: 8, origin: { kind: 'person' } })
  const ringOn = ($: any, key: string) =>
    $.ui.focus({ component: 'Pane', requestId: 'questions', key, element: key, origin: 'person' } as never)
  const chosen = async ($: any) => /❯ #(\d+) /.exec(textOf(await $.ui.render(pane())))?.[1] ?? null

  test('an arrow in a list taller than the pane moves the choice, not the window', async ($, on) => {
    const { clock } = await started($, on, ['one', 'two', 'three'])
    await typed($, clock, '.')
    await ringOn($, 'q:u3')
    expect((await $.ui.scroll(arrow(-1) as never))?.deny).toBeDefined()
    await clock.advance(10)
    expect(await chosen($)).toBe('2')
    expect((await $.ui.scroll(arrow(-1) as never))?.deny).toBeDefined()
    await clock.advance(10)
    expect(await chosen($)).toBe('1')
  })

  test('arrows stop at the oldest question, and ↓ past the newest returns to the filter', async ($, on) => {
    const { clock } = await started($, on, ['one', 'two'])
    await typed($, clock, '.')
    await ringOn($, 'q:u1')
    expect((await $.ui.scroll(arrow(-1) as never))?.deny).toBeDefined()
    await clock.advance(10)
    expect(await chosen($)).toBe('1')

    await ringOn($, 'q:u2')
    expect((await $.ui.scroll(arrow(1) as never))?.deny).toBeDefined()
    await clock.advance(10)
    expect(await chosen($)).toBeNull()

    // From the field, ↑ goes to the newest question the filter keeps.
    await $.ui.scroll(arrow(-1) as never)
    await clock.advance(10)
    expect(await chosen($)).toBe('2')
  })

  test('the wheel and page keys still scroll the window', async ($, on) => {
    const { world, clock } = await started($, on, ['one', 'two', 'three'])
    await typed($, clock, '.')
    await ringOn($, 'q:u3')
    expect((await $.ui.scroll({ ...arrow(-1), pointer: { row: 1, column: 4 } } as never))?.deny).toBeUndefined()
    expect((await $.ui.scroll(arrow(-3) as never))?.deny).toBeUndefined()
    await clock.advance(10)
    expect(await chosen($)).toBe('3')
    expect(world.scrolls).toHaveLength(2)
  })

  // The test kit does not model a plugin scrolling a transcript row (it answers "no implementation"),
  // so these check the press lands on the right question and that a refusal reaches the person.
  // The jump itself is checked against the real terminal in the install verification.
  test('pressing a question asks to jump to it, and a refusal shows its text', async ($, on) => {
    const { world, clock } = await started($, on, ['one', 'two'])
    await typed($, clock, '.')
    await $.ui.render(pane())
    await $.ui.press({ plugin: PLUGIN, key: 'q:u1' })
    expect(world.toasts.at(-1)).toMatch(/^Can't jump to #1 \(.+\); its text is shown in the list$/)
    // A question the transcript can't show any more is read in the list; a second press folds it.
    expect(textOf(await $.ui.render(pane()))).toContain('one, asked in full')
    await $.ui.press({ plugin: PLUGIN, key: 'q:u1' })
    expect(textOf(await $.ui.render(pane()))).not.toContain('one, asked in full')
  })

  test('a helper failure is shown in the pane and toasted once', async ($, on) => {
    const { world, clock } = await started($, on)
    world.helperStdout = '{"version":1,"error":"transcript not found: x"}'
    world.files.set(TRANSCRIPT, 'x'.repeat(200))
    await typed($, clock, '.')
    // The list opens at once; the re-read of the grown transcript follows on the clock.
    for (let tick = 0; tick < 5; tick += 1) {
      await clock.advance(10)
    }
    expect(world.toasts.at(-1)).toContain('transcript not found')
    expect(textOf(await $.ui.render(pane()))).toContain('⚠ transcript not found')
  })

  test('a prompt typed now is listed before the helper runs again', async ($, on) => {
    await started($, on, ['one'])
    await $.session.append({ message: { type: 'user', content: [{ type: 'text', text: 'a brand new question' }] }, door: 'prompt', origin: { kind: 'composer' }, uuid: 'live-9' } as never)
    const text = textOf(await $.ui.render(pane()))
    expect(text).toContain('#2 ')
    expect(text).toContain('a brand new question')
  })
})

describe('the terminal accepts what the mod draws', () => {
  const accepted = async ($: any, input: Record<string, unknown>) => {
    const mounted = await $.ui.mount({ ...input, plugin: PLUGIN })
    await mounted.unmount()
    return mounted.surface
  }

  test('rows, groups, folded messages and the pane', async ($, on) => {
    await started($, on, ['one', 'two'])
    expect(await accepted($, edit)).toBe('terminal')
    expect(await accepted($, toolGroup([{ id: 'b1', tool: 'Bash', input: { command: 'exit 3' }, isErrored: true, output: 'Error: Exit code 3' }]))).toBe('terminal')
    expect(await accepted($, toolResult('t9', 'Edit'))).toBe('terminal')
    expect(await accepted($, assistantMessage('m9', ['```js', ...Array.from({ length: 20 }, () => 'x()'), '```'].join('\n')))).toBe('terminal')
    expect(await accepted($, pane(30))).toBe('terminal')
  })
})
