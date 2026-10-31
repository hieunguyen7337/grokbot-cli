import { describe, expect, test } from 'claude-code/testing'

import { addLive, entryFromAppend, merge, parseHelper } from '../hooks/prompts'

const prompt = (uuid: string, ts: string, extra: Record<string, unknown> = {}) => ({
  uuid,
  n: 0,
  ts,
  title: uuid,
  isBeforeCompact: false,
  ...extra,
})

describe('helper output', () => {
  test('a list of prompts', async () => {
    const parsed = parseHelper(
      JSON.stringify({ version: 1, size: 42, prompts: [{ uuid: 'a', ts: 't', title: 'one', isBeforeCompact: true }, { uuid: 'b', title: 'two' }, { title: 'no id' }] }),
    )
    expect(parsed).toEqual({
      size: 42,
      prompts: [
        { uuid: 'a', n: 1, ts: 't', title: 'one', isBeforeCompact: true },
        { uuid: 'b', n: 2, ts: null, title: 'two', isBeforeCompact: false },
      ],
    })
  })

  test('errors, garbage and missing lists', async () => {
    expect(parseHelper('{"error": "transcript not found: x"}')).toEqual({ error: 'transcript not found: x' })
    expect('error' in parseHelper('Traceback (most recent call last)')).toBe(true)
    expect(parseHelper('{}')).toEqual({ error: 'helper output has no prompts' })
  })
})

describe('live prompts', () => {
  const row = (extra: Record<string, unknown> = {}) => ({
    door: 'prompt',
    origin: { kind: 'composer' },
    uuid: 'live-1',
    message: { type: 'user', content: 'what changed?' },
    ...extra,
  })

  test('a typed prompt becomes an entry; a phone prompt too', async () => {
    expect(entryFromAppend(row(), 'NOW')).toEqual({
      uuid: 'live-1',
      n: 0,
      ts: 'NOW',
      title: 'what changed?',
      text: 'what changed?',
      isBeforeCompact: false,
      isLive: true,
    })
    // The list keeps up to 600 characters, to show a question the transcript no longer has.
    expect(entryFromAppend(row({ message: { type: 'user', content: 'x'.repeat(700) } }), 'NOW')?.text).toHaveLength(600)
    expect(entryFromAppend(row({ origin: { kind: 'bridge' } }), 'NOW')?.uuid).toBe('live-1')
    expect(entryFromAppend(row({ message: { type: 'user', content: [{ type: 'text', text: 'block text' }] } }), 'NOW')?.title).toBe('block text')
  })

  test('meta rows, subagents, other doors, notifications and slash commands are not prompts', async () => {
    expect(entryFromAppend(row({ message: { type: 'user', isMeta: true, content: 'x' } }), 'NOW')).toBeNull()
    expect(entryFromAppend(row({ agentId: 'a1' }), 'NOW')).toBeNull()
    expect(entryFromAppend(row({ door: 'tool-result' }), 'NOW')).toBeNull()
    expect(entryFromAppend(row({ origin: { kind: 'task-notification' } }), 'NOW')).toBeNull()
    expect(entryFromAppend(row({ message: { type: 'user', content: '<command-name>/effort</command-name>' } }), 'NOW')).toBeNull()
    expect(entryFromAppend(row({ message: { type: 'user', content: '/compact' } }), 'NOW')).toBeNull()
    expect(entryFromAppend(row({ message: { type: 'user', content: '/plugin-x:run now' } }), 'NOW')).toBeNull()
    expect(entryFromAppend(row({ message: { type: 'user', content: '/usr/bin is missing' } }), 'NOW')?.title).toBe('/usr/bin is missing')
  })

  test('merge keeps the helper order, adds newer live prompts and drops rewound ones', async () => {
    const helper = [prompt('a', '2026-10-13T01:00:00Z'), prompt('b', '2026-10-13T02:00:00Z')]
    const live = [
      prompt('b', '2026-10-13T02:00:00Z', { isLive: true }),
      prompt('old', '2026-10-13T01:30:00Z', { isLive: true }),
      prompt('new', '2026-10-13T03:00:00Z', { isLive: true }),
    ]
    expect(merge(helper, live).map(item => `${item.n}:${item.uuid}`)).toEqual(['1:a', '2:b', '3:new'])
  })

  test('addLive appends once and renumbers', async () => {
    const list = addLive([prompt('a', 't1')], prompt('b', 't2', { isLive: true }))
    expect(list.map(item => `${item.n}:${item.uuid}`)).toEqual(['1:a', '2:b'])
    expect(addLive(list, prompt('b', 't2'))).toBe(list)
  })
})
