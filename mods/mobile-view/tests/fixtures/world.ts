import type { On, RenderElement, RenderNode } from 'claude-code'

/** What the plugin asked of the engine, and the answers the engine gives it, in memory. */
export type World = {
  files: Map<string, string>
  commands: string[]
  opened: { id: string; focus: boolean; closeOnEscape: boolean }[]
  /** Ids of the panes the plugin closed, oldest first. */
  closed: string[]
  /** False to answer `$.ui.open` as a terminal too narrow for a pane nobody asked for. */
  isPlaceable: boolean
  /** What the plugin put in the prompt box with `$.prompt.fill`, oldest first. */
  fills: string[]
  /** Where the focus ring was moved in a site, oldest first. */
  focuses: { requestId: string; element?: string }[]
  /** The person's scrolls of the Questions pane that reached the engine, oldest first. */
  scrolls: Record<string, unknown>[]
  toasts: string[]
  runs: (readonly string[])[]
  invalidations: number
  /** What the plugin keeps in `$.store`. */
  store: Map<string, unknown>
  /** What `$.process.run` of the prompts helper prints. */
  helperStdout: string
}

export const CWD = 'C:/work'
// Absolute on every platform once a drive letter is dropped: Linux and macOS resolve `C:/...` against the
// plugin folder, and Windows may hand `/home/...` back as `C:\home\...`, so file lookups go through fileKey.
export const TRANSCRIPT = '/home/me/.claude/projects/-work/s1.jsonl'
export const ENV = { MOBILE_VIEW_PYTHON: 'C:/py/python.exe', MOBILE_VIEW_PROMPTS: 'C:/kit/bin/claude-prompts.py', USERPROFILE: 'C:/Users/me' }
export const SESSION = { surface: 'terminal' as const, isInteractive: true, cwd: CWD }
export const VIEWPORT = { columns: 120, rows: 40, isFullscreen: true }

/** The engine beneath the plugin. Its own drawing is a Text naming the component and the props it got. */
export function worldOf(on: On, env: Readonly<Record<string, string>> = ENV): World {
  const world: World = {
    files: new Map(),
    commands: [],
    opened: [],
    closed: [],
    isPlaceable: true,
    fills: [],
    focuses: [],
    scrolls: [],
    toasts: [],
    runs: [],
    invalidations: 0,
    store: new Map(),
    helperStdout: JSON.stringify({ version: 1, size: 0, prompts: [] }),
  }

  on('fs.read', ($, e) => {
    const text = fileOf(world, e.path)
    return text === undefined ? { deny: `ENOENT: ${e.path}` } : { value: text }
  })
  on('fs.stat', ($, e) => {
    // The engine hands paths over in the platform's spelling.
    const text = fileOf(world, e.path)
    return text === undefined ? { deny: `ENOENT: ${e.path}` } : { value: { kind: 'file' as const, size: text.length, mtimeMs: 1, isLink: false } }
  })
  on('env.get', ($, e) => ({ value: env[e.name] }))
  on('command.register', ($, e) => {
    world.commands.push(e.name)
    return { value: { command: e.name } }
  })
  on('ui.focus', ($, e) => {
    const input = e as { requestId: string; element?: string; key?: string }
    world.focuses.push({ requestId: input.requestId, element: input.element ?? input.key })
    return {} as never
  })
  // The pane's window; a transcript scroll stays unmodelled (the kit answers "no implementation").
  on('ui.scroll', ($, e, next) => {
    const input = e as Record<string, unknown>
    if (input.component !== 'Pane' && input.in !== 'questions') {
      return next(e)
    }
    world.scrolls.push(input)
    return {} as never
  })
  on('ui.open', ($, e) => {
    world.opened.push({ id: e.id, focus: e.focus === true, closeOnEscape: e.closeOnEscape === true })
    return { value: world.isPlaceable ? { isPlaced: true } : { isPlaced: false, reason: 'under 144 columns' } } as never
  })
  on('ui.close', ($, e) => {
    world.closed.push(e.id)
    return { value: undefined } as never
  })
  on('prompt.fill', ($, e) => {
    world.fills.push(e.text)
    return { isFilled: true } as never
  })
  // The prompt box's own editor: the splice applied, the cursor after what went in.
  on('prompt.edit', ($, e) => {
    const text = e.text.slice(0, e.start) + e.inputText + e.text.slice(e.end)
    return { text, cursor: e.start + e.inputText.length } as never
  })
  on('ui.toast', ($, e) => {
    world.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.invalidate', () => {
    world.invalidations += 1
    return { value: undefined }
  })
  on('process.run', ($, e) => {
    world.runs.push(e.argv)
    return {
      value: { exitCode: 0, stdout: world.helperStdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
    } as never
  })
  on('store.get', ($, e) => ({ value: world.store.get(e.key) }))
  on('store.set', ($, e) => {
    world.store.set(e.key, e.value)
    return { value: undefined }
  })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('ui.render', ($, e) => {
    const props = e.props as Record<string, unknown>
    const shown: Record<string, unknown> = {}
    for (const key of ['text', 'isExpanded', 'tool', 'tail']) {
      if (key in props) {
        shown[key] = props[key]
      }
    }
    return { type: 'Text', children: [`ENGINE ${e.component} ${JSON.stringify(shown)}`] } as never
  })

  return world
}

/** Every string a drawn tree holds, in drawing order (Button labels included). */
export function stringsOf(node: RenderNode | RenderElement | null | undefined): string[] {
  if (node === null || node === undefined) {
    return []
  }
  if (typeof node === 'string') {
    return [node]
  }
  const own: string[] = []
  const props = (node as { props?: Record<string, unknown> }).props
  if (node.type === 'Button' && typeof props?.label === 'string') {
    own.push(props.label)
  }
  const children = (node as { children?: readonly RenderNode[] }).children ?? []
  return [...own, ...children.flatMap(child => stringsOf(child))]
}

export const textOf = (node: RenderNode | RenderElement | null | undefined): string => stringsOf(node).join('')

/** Every element of `type` in a drawn tree. */
export function elementsOf(node: RenderNode | RenderElement | null | undefined, type: string): RenderElement[] {
  if (node === null || node === undefined || typeof node === 'string') {
    return []
  }
  const children = (node as { children?: readonly RenderNode[] }).children ?? []
  return [...(node.type === type ? [node] : []), ...children.flatMap(child => elementsOf(child, type))]
}

export const command = (name: string, args = '', columns = 160) => ({
  command: name,
  args,
  origin: { kind: 'composer' as const },
  presentation: { isFullscreen: true, columns },
})

export const toolUse = (id: string, tool: string, input: unknown, extra: Record<string, unknown> = {}) => ({
  component: 'ToolUse' as const,
  surface: 'terminal' as const,
  requestId: id,
  viewport: VIEWPORT,
  props: { tool_use_id: id, tool, input, isRunning: false, isErrored: false, isInterrupted: false, ...extra },
})

export const toolResult = (id: string, tool: string, output: unknown = { stdout: 'x' }) => ({
  component: 'ToolResult' as const,
  surface: 'terminal' as const,
  requestId: id,
  viewport: VIEWPORT,
  props: { tool_use_id: id, tool, output, isErrored: false },
})

export const toolGroup = (calls: { id: string; tool: string; input: unknown; isErrored?: boolean; output?: unknown }[], isExpanded = false) => ({
  component: 'ToolGroup' as const,
  surface: 'terminal' as const,
  requestId: `collapsed-${calls[0]?.id ?? 'x'}`,
  viewport: VIEWPORT,
  props: {
    calls: calls.map(call => ({
      tool_use_id: call.id,
      tool: call.tool,
      input: call.input,
      isRunning: false,
      isErrored: call.isErrored === true,
      isInterrupted: false,
      output: call.output,
    })),
    isActive: false,
    isExpanded,
  },
})

export const userMessage = (id: string, text: string, isExpanded = false) => ({
  component: 'UserMessage' as const,
  surface: 'terminal' as const,
  requestId: id,
  viewport: VIEWPORT,
  props: { text, origin: { kind: 'composer' as const }, isExpanded },
})

export const assistantMessage = (id: string, text: string) => ({
  component: 'AssistantMessage' as const,
  surface: 'terminal' as const,
  requestId: id,
  viewport: VIEWPORT,
  props: { text, isFirstOfReply: true },
})

/** The hint line under the prompt (`? for shortcuts · ← for agents`). */
export const promptHint = (isDraft = false, columns = 160) => ({
  component: 'PromptHint' as const,
  surface: 'terminal' as const,
  requestId: 'prompt-hint',
  viewport: { ...VIEWPORT, columns },
  props: { isDraft, isWorking: false, hint: '? for shortcuts' },
})

export const pane = (bodyColumns = 48, isFocused = true) => ({
  component: 'Pane' as const,
  surface: 'terminal' as const,
  requestId: 'questions',
  viewport: VIEWPORT,
  props: { title: 'Questions', isFocused, bodyColumns, placement: 'dock' as const, scroll: { offset: 0, bodyRows: 40 }, view: {} },
})

/** A path as the fixture files are keyed: forward slashes, no drive letter. */
const fileKey = (path: string) => path.replaceAll('\\', '/').replace(/^[A-Za-z]:(?=\/)/, '')

function fileOf(world: World, path: string): string | undefined {
  const wanted = fileKey(path)
  for (const [key, text] of world.files) {
    if (fileKey(key) === wanted) {
      return text
    }
  }
  return undefined
}

/** When the helper says question `index` (from 0) was asked. */
export const stampOf = (index: number) => `2026-10-13T0${index}:00:00.000Z`

export const helperJson = (titles: string[], size = 100) =>
  JSON.stringify({
    version: 1,
    path: TRANSCRIPT,
    size,
    prompts: titles.map((title, index) => ({
      uuid: `u${index + 1}`,
      n: index + 1,
      ts: stampOf(index),
      title,
      text: `${title}, asked in full`,
      isBeforeCompact: false,
    })),
  })
