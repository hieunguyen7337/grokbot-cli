import { describe, expect, mock, test } from 'claude-code/testing'

const answer = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as const

/** Stubs the bottom of the world: 190k tokens in a 200k window, and a compact that records its calls. */
function world(on: any, env: Record<string, string> = {}) {
  const compacts: unknown[] = []
  mock.env(on, env)
  const clock = mock.clock(on)
  on('turn.complete', (_$: any, e: any) => ({ text: e.answer }) as never)
  on('session.usage', (_$: any, args: any) =>
    ({ value: { context: { tokens: 190000, window: 1000000, breakdown: args?.breakdown ? { rawMaxTokens: 200000 } : undefined } } }) as never,
  )
  on('session.compact', (_$: any, e: any) => {
    compacts.push(e)
    return { messages: [{ role: 'user', text: 'summary', toolUses: [] }], tokensBefore: 190000, tokensAfter: 90000 } as never
  })
  return { compacts, clock }
}

describe('compact-at-rest', () => {
  test('a main-loop answer over the line schedules one compaction', async ($, on) => {
    const { compacts, clock } = world(on)
    const result = await $.turn.complete(answer)
    expect(result).toEqual({ text: 'done' })
    await $.turn.complete({ ...answer, turnId: 't2' })
    await clock.advance(2000)
    expect(compacts.length).toBe(1)
  })
  test('a subagent turn does nothing', async ($, on) => {
    const { compacts, clock } = world(on)
    await $.turn.complete({ ...answer, agentId: 'a1' })
    await clock.advance(2000)
    expect(compacts.length).toBe(0)
  })
  test('an aborted turn does nothing', async ($, on) => {
    const { compacts, clock } = world(on)
    await $.turn.complete({ ...answer, reason: 'aborted', isAborted: true })
    await clock.advance(2000)
    expect(compacts.length).toBe(0)
  })
  test('off does nothing', async ($, on) => {
    const { compacts, clock } = world(on, { USAGE_OPTIMIZER_COMPACT_AT_REST: 'off' })
    await $.turn.complete(answer)
    await clock.advance(2000)
    expect(compacts.length).toBe(0)
  })
})
