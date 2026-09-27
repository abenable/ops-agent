import type { UIMessage } from 'ai'

export type Thread = {
  thread_id: string
  title: string
  started_at: string
  updated_at: string
  turns: number
  messages: number
}

export type Json = string | number | boolean | null | Array<Json> | { [key: string]: Json }

export type ToolCall = { id: string; name: string; args: { [key: string]: Json } }

export type TranscriptMessage = {
  id: string
  type: 'human' | 'ai' | 'tool' | 'summary' | 'system'
  content: string
  at: string | null
  tool_calls?: Array<ToolCall>
  usage?: { input_tokens: number; output_tokens: number; total_tokens: number } | null
  tool_call_id?: string
  name?: string
  status?: 'success' | 'error'
}

export type AgentTool = { name: string; description: string; backend: 'docker' | 'prometheus' | 'loki' }

export type Source = 'web' | 'discord' | 'other'

export const sourceOf = (threadId: string): Source =>
  threadId.startsWith('web-') ? 'web' : /^\d{15,20}$/.test(threadId) ? 'discord' : 'other'

export const newThreadId = () => `web-${crypto.randomUUID()}`

// How the agent's approval step records a call the person denied.
export const wasDenied = (result?: TranscriptMessage) => !!result?.content.startsWith('User rejected the tool call')

export function toUIMessages(messages: Array<TranscriptMessage>, awaiting: Array<string> = []): Array<UIMessage> {
  const results = new Map(
    messages.filter((m) => m.type === 'tool').map((m) => [m.tool_call_id, m]),
  )
  const out: Array<UIMessage> = []
  let assistant: UIMessage | null = null
  for (const message of messages) {
    if (message.type === 'human') {
      assistant = null
      out.push({ id: message.id, role: 'user', parts: [{ type: 'text', text: message.content }] })
      continue
    }
    if (message.type !== 'ai') continue
    if (!assistant) {
      assistant = { id: message.id, role: 'assistant', parts: [] }
      out.push(assistant)
    }
    if (message.content) assistant.parts.push({ type: 'text', text: message.content, state: 'done' })
    for (const call of message.tool_calls ?? []) {
      const result = results.get(call.id)
      const base = { type: 'dynamic-tool', toolName: call.name, toolCallId: call.id, input: call.args } as const
      if (awaiting.includes(call.id)) {
        assistant.parts.push({ ...base, state: 'approval-requested', approval: { id: call.id } })
        continue
      }
      if (wasDenied(result)) {
        assistant.parts.push({ ...base, state: 'output-denied', approval: { id: call.id, approved: false } })
        continue
      }
      assistant.parts.push(
        result && result.status !== 'error'
          ? { ...base, state: 'output-available', output: result.content }
          : { ...base, state: 'output-error', errorText: result?.content ?? 'No result was recorded.' },
      )
    }
  }
  return out
}

const FAILURES = [
  'investigation timed out',
  'investigation failed',
  'model call failed',
  'the model returned an empty answer',
  'tool call limit reached',
]

export type Step = {
  call: ToolCall
  result?: TranscriptMessage
  latencyMs: number | null
}

export type Turn = {
  index: number
  question: TranscriptMessage
  messages: Array<TranscriptMessage>
  answer: string
  steps: Array<Step>
  durationMs: number | null
  inputTokens: number
  outputTokens: number
  toolErrors: number
  outcome: 'answered' | 'failed' | 'no answer'
}

const ms = (from?: string | null, to?: string | null) =>
  from && to ? new Date(to).getTime() - new Date(from).getTime() : null

export function turnsOf(messages: Array<TranscriptMessage>): Array<Turn> {
  const turns: Array<Turn> = []
  for (const message of messages) {
    if (message.type === 'human') {
      turns.push({
        index: turns.length + 1,
        question: message,
        messages: [],
        answer: '',
        steps: [],
        durationMs: null,
        inputTokens: 0,
        outputTokens: 0,
        toolErrors: 0,
        outcome: 'no answer',
      })
    } else if (turns.length) {
      turns[turns.length - 1].messages.push(message)
    }
  }
  for (const turn of turns) {
    const byCall = new Map(turn.messages.filter((m) => m.type === 'tool').map((m) => [m.tool_call_id, m]))
    for (const message of turn.messages) {
      if (message.type !== 'ai') continue
      turn.inputTokens += message.usage?.input_tokens ?? 0
      turn.outputTokens += message.usage?.output_tokens ?? 0
      for (const call of message.tool_calls ?? []) {
        const result = byCall.get(call.id)
        turn.steps.push({ call, result, latencyMs: ms(message.at, result?.at) })
      }
    }
    turn.toolErrors = turn.steps.filter((s) => !s.result || s.result.status === 'error').length
    const last = turn.messages.at(-1)
    if (last?.type === 'ai' && !last.tool_calls?.length && last.content) {
      turn.answer = last.content
      turn.durationMs = ms(turn.question.at, last.at)
      const lower = last.content.toLowerCase()
      turn.outcome = FAILURES.some((f) => lower.startsWith(f)) ? 'failed' : 'answered'
    }
  }
  return turns
}

export function toolStats(turns: Array<Turn>) {
  const stats = new Map<string, { calls: number; errors: number; totalMs: number; timed: number }>()
  for (const step of turns.flatMap((t) => t.steps)) {
    const s = stats.get(step.call.name) ?? { calls: 0, errors: 0, totalMs: 0, timed: 0 }
    s.calls += 1
    if (!step.result || step.result.status === 'error') s.errors += 1
    if (step.latencyMs != null) {
      s.totalMs += step.latencyMs
      s.timed += 1
    }
    stats.set(step.call.name, s)
  }
  return [...stats.entries()]
    .map(([name, s]) => ({ name, ...s, avgMs: s.timed ? s.totalMs / s.timed : null }))
    .sort((a, b) => b.calls - a.calls)
}

export const formatMs = (value: number | null) =>
  value == null ? '—' : value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`
