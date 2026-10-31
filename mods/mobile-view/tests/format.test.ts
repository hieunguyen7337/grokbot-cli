import { describe, expect, test } from 'claude-code/testing'

import {
  cellWidth,
  clockTime,
  collapseCodeBlocks,
  promptTitle,
  relPath,
  statusMark,
  toolLabel,
  toolName,
  truncateCells,
} from '../hooks/format'

const WHERE = { cwd: 'C:/work/app', home: 'C:/Users/me' }

describe('tool labels', () => {
  test('Bash shows its description, else the first command line', async () => {
    expect(toolLabel('Bash', { command: 'adb shell input swipe 540 1700', description: 'Swipe up on the phone' }, WHERE)).toBe('Swipe up on the phone')
    expect(toolLabel('Bash', { command: 'npm test\nnpm run lint' }, WHERE)).toBe('npm test \u2026')
    expect(toolLabel('Bash', { command: 'sleep 60', description: 'Wait', run_in_background: true }, WHERE)).toBe('Wait \u00b7 background')
    expect(toolLabel('PowerShell', { command: 'Get-ChildItem', description: 'List files' }, WHERE)).toBe('List files')
  })

  test('file tools show paths relative to the working directory or home', async () => {
    expect(toolLabel('Read', { file_path: 'C:\\work\\app\\src\\main.ts' }, WHERE)).toBe('src/main.ts')
    expect(toolLabel('Read', { file_path: '/c/work/app/README.md', offset: 10, limit: 5 }, WHERE)).toBe('README.md:10-14')
    expect(toolLabel('Read', { file_path: 'c:/users/me/.claude/settings.json' }, WHERE)).toBe('~/.claude/settings.json')
    expect(toolLabel('Read', { file_path: 'D:/other/x.txt' }, WHERE)).toBe('D:/other/x.txt')
    expect(toolLabel('Edit', { file_path: 'C:/work/app/a.ts', old_string: 'one', new_string: 'two\nthree' }, WHERE)).toBe('a.ts  +2 \u22121')
    expect(toolLabel('Write', { file_path: 'C:/work/app/new.md', content: 'a\nb\nc' }, WHERE)).toBe('new.md  (3 lines)')
    expect(toolLabel('Read', { file_path: 'C:/work/app/日本語/ファイル.md' }, WHERE)).toBe('日本語/ファイル.md')
  })

  test('Linux and macOS paths keep their case, and a one-letter folder is not a drive', async () => {
    const posix = { cwd: '/home/me/app', home: '/home/me' }
    expect(toolLabel('Read', { file_path: '/home/me/app/src/main.ts' }, posix)).toBe('src/main.ts')
    expect(toolLabel('Read', { file_path: '/home/me/.claude/settings.json' }, posix)).toBe('~/.claude/settings.json')
    expect(toolLabel('Read', { file_path: '/HOME/me/app/a.ts' }, posix)).toBe('/HOME/me/app/a.ts')
    expect(toolLabel('Read', { file_path: '/c/data/x.txt' }, posix)).toBe('/c/data/x.txt')
    expect(toolLabel('Read', { file_path: '/Users/me/notes.md' }, { cwd: '/Users/me/app', home: '/Users/me' })).toBe('~/notes.md')
    expect(relPath('/home/me/app', posix)).toBe('.')
    expect(relPath('/home/me', posix)).toBe('~')
  })

  test('searches, the web, agents and MCP tools', async () => {
    expect(toolLabel('Grep', { pattern: 'sessionId', path: 'C:/work/app/src', glob: '*.ts' }, WHERE)).toBe('"sessionId" in src (*.ts)')
    expect(toolLabel('Glob', { pattern: '**/*.tsx' }, WHERE)).toBe('**/*.tsx')
    expect(toolLabel('WebFetch', { url: 'https://code.claude.com/docs/en/hooks', prompt: 'x' }, WHERE)).toBe('code.claude.com')
    expect(toolLabel('WebSearch', { query: 'claude code mods' }, WHERE)).toBe('claude code mods')
    expect(toolLabel('Agent', { description: 'Map existing kit', prompt: 'x' }, WHERE)).toBe('Map existing kit')
    expect(toolName('mcp__claude_ai_Gmail__search_threads')).toBe('Gmail')
    expect(toolLabel('mcp__claude_ai_Gmail__search_threads', { query: 'from:boss' }, WHERE)).toBe('search_threads: from:boss')
    expect(toolLabel('SomethingNew', { value: 'shown', other: 1 }, WHERE)).toBe('shown')
  })

  test('relPath handles the working directory itself and Git Bash paths', async () => {
    expect(relPath('C:/work/app', WHERE)).toBe('.')
    expect(relPath('/c/Users/me', WHERE)).toBe('~')
  })
})

describe('status marks', () => {
  test('nothing on success, an exit code or first line on failure', async () => {
    expect(statusMark({ tool: 'Bash', input: {} })).toEqual({ text: '', tone: 'ok' })
    expect(statusMark({ tool: 'Bash', input: {}, isRunning: true })).toEqual({ text: '\u2026', tone: 'running' })
    expect(statusMark({ tool: 'Bash', input: {}, isErrored: true, output: 'Error: Exit code 3' })).toEqual({ text: '\u2717 exit 3', tone: 'error' })
    expect(statusMark({ tool: 'Bash', input: {}, isErrored: true, output: { stderr: 'Exit code 1\nboom' } }).text).toBe('\u2717 exit 1')
    expect(statusMark({ tool: 'Edit', input: {}, isErrored: true, output: 'Error: File has not been read yet' }).text).toBe('\u2717 File has not been read yet')
    expect(statusMark({ tool: 'Edit', input: {}, isInterrupted: true })).toEqual({ text: '\u2298 interrupted', tone: 'warn' })
  })
})

describe('code blocks', () => {
  const block = (lines: number, fence = '```', info = 'python') =>
    [`${fence}${info}`, ...Array.from({ length: lines }, (_, i) => `print(${i})`), fence].join('\n')

  test('short blocks and plain text stay', async () => {
    expect(collapseCodeBlocks('just prose', { minLines: 12 })).toEqual({ text: 'just prose', count: 0, lines: 0 })
    const short = `before\n${block(3)}\nafter`
    expect(collapseCodeBlocks(short, { minLines: 12 }).text).toBe(short)
  })

  test('a long block becomes one line naming its language and size', async () => {
    const folded = collapseCodeBlocks(`Here it is:\n${block(30)}\nDone.`, { minLines: 12 })
    expect(folded).toEqual({ text: 'Here it is:\n\u25b8 python \u00b7 30 lines hidden\nDone.', count: 1, lines: 30 })
  })

  test('tildes, longer fences, info strings and two blocks', async () => {
    expect(collapseCodeBlocks(block(20, '~~~', 'ts'), { minLines: 12 }).text).toBe('\u25b8 ts \u00b7 20 lines hidden')
    const nested = ['````md', '```js', ...Array.from({ length: 15 }, () => 'x'), '```', '````'].join('\n')
    expect(collapseCodeBlocks(nested, { minLines: 12 })).toEqual({ text: '\u25b8 md \u00b7 17 lines hidden', count: 1, lines: 17 })
    expect(collapseCodeBlocks(block(20, '```', 'python title="a.py"'), { minLines: 12 }).text).toBe('\u25b8 python \u00b7 20 lines hidden')
    const two = collapseCodeBlocks(`${block(13)}\nmid\n${block(14, '```', '')}`, { minLines: 12 })
    expect(two.text).toBe('\u25b8 python \u00b7 13 lines hidden\nmid\n\u25b8 code \u00b7 14 lines hidden')
    expect(two.count).toBe(2)
    expect(two.lines).toBe(27)
  })

  test('an unclosed block (still streaming), a list-indented block and CRLF', async () => {
    const open = ['```bash', ...Array.from({ length: 20 }, () => 'echo x')].join('\n')
    expect(collapseCodeBlocks(open, { minLines: 12 }).text).toBe('\u25b8 bash \u00b7 20 lines\u2026')
    const listed = ['1. Run:', '   ```sh', ...Array.from({ length: 13 }, () => '   make'), '   ```', '2. Done'].join('\n')
    expect(collapseCodeBlocks(listed, { minLines: 12 }).text).toBe('1. Run:\n   \u25b8 sh \u00b7 13 lines hidden\n2. Done')
    expect(collapseCodeBlocks(block(13).replace(/\n/g, '\r\n'), { minLines: 12 }).text).toBe('\u25b8 python \u00b7 13 lines hidden')
  })

  test('inline triple backticks in a sentence are not a fence', async () => {
    const text = '```not a fence``` and more'
    expect(collapseCodeBlocks(text, { minLines: 0 }).text).toBe(text)
  })
})

describe('text', () => {
  test('cell widths and truncation count wide characters as two', async () => {
    expect(cellWidth('abc')).toBe(3)
    expect(cellWidth('日本')).toBe(4)
    expect(cellWidth('🚀')).toBe(2)
    expect(truncateCells('hello world', 8)).toBe('hello w\u2026')
    expect(truncateCells('日本語テキスト', 7)).toBe('日本語\u2026')
    expect(truncateCells('short', 10)).toBe('short')
  })

  test('prompt titles show pastes and the first line', async () => {
    expect(promptTitle('<pasted_content id="1">\nlog\n</pasted_content id="1">\n\ninstead show the answer')).toBe('[pasted] instead show the answer')
    expect(promptTitle('\n\n  first line  \nsecond')).toBe('first line')
    expect(promptTitle('')).toBe('[empty]')
  })

  test('clock times are blank for nothing', async () => {
    expect(clockTime(null)).toBe('     ')
    expect(clockTime('not a date')).toBe('     ')
    expect(clockTime('2026-10-13T02:08:00.000Z')).toMatch(/^\d\d:\d\d$/)
  })
})
