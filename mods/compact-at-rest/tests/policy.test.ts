import { describe, expect, test } from 'claude-code/testing'

import { parseNear, shouldCompact } from '../hooks/policy'

describe('parseNear', () => {
  test('defaults to 90', () => {
    expect(parseNear(undefined)).toBe(90)
  })
  test('takes a value in range', () => {
    expect(parseNear('80')).toBe(80)
    expect(parseNear('50')).toBe(50)
    expect(parseNear('100')).toBe(100)
  })
  test('falls back to 90 out of range or unparsed', () => {
    expect(parseNear('49')).toBe(90)
    expect(parseNear('101')).toBe(90)
    expect(parseNear('abc')).toBe(90)
    expect(parseNear('')).toBe(90)
  })
})

describe('shouldCompact', () => {
  const base = { tokens: 180000, window: 200000, nearPercent: 90, minTokens: 100000 }
  test('false below minTokens', () => {
    expect(shouldCompact({ ...base, tokens: 90000, window: 100000 })).toBe(false)
  })
  test('false below the near line', () => {
    expect(shouldCompact({ ...base, tokens: 179999 })).toBe(false)
  })
  test('true exactly at the near line', () => {
    expect(shouldCompact(base)).toBe(true)
  })
  test('true above the near line', () => {
    expect(shouldCompact({ ...base, tokens: 195000 })).toBe(true)
  })
  test('false with a zero or missing window', () => {
    expect(shouldCompact({ ...base, window: 0 })).toBe(false)
    expect(shouldCompact({ ...base, window: undefined })).toBe(false)
  })
})
