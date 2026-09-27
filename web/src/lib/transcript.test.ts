import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseCommand } from './commands.ts'
import type { TranscriptMessage } from './transcript.ts'
import { sourceOf, toUIMessages, turnsOf } from './transcript.ts'

const at = (s: number) => new Date(Date.UTC(2026, 8, 27, 12, 0, s)).toISOString()

const thread: Array<TranscriptMessage> = [
  { id: 'h1', type: 'human', content: 'is api up?', at: at(0) },
  { id: 'a1', type: 'ai', content: '', at: at(2), tool_calls: [{ id: 'c1', name: 'docker_status', args: { container: 'api' } }], usage: { input_tokens: 10, output_tokens: 2, total_tokens: 12 } },
  { id: 't1', type: 'tool', content: 'api: exited', at: at(3), tool_call_id: 'c1', name: 'docker_status', status: 'success' },
  { id: 'a2', type: 'ai', content: '`api` exited.', at: at(5), tool_calls: [], usage: { input_tokens: 20, output_tokens: 4, total_tokens: 24 } },
  { id: 'h2', type: 'human', content: 'and the worker?', at: at(9) },
  { id: 'a3', type: 'ai', content: 'Tool call limit reached: run limit exceeded (20/20 calls).', at: at(20), tool_calls: [] },
  { id: 'h3', type: 'human', content: 'still there?', at: at(30) },
]

test('commands parse with arguments and ignore unknown slashes', () => {
  assert.deepEqual(parseCommand('/watch lab-api'), { name: 'watch', arg: 'lab-api' })
  assert.deepEqual(parseCommand('  /STATUS '), { name: 'status', arg: '' })
  assert.equal(parseCommand('/nope'), null)
  assert.equal(parseCommand('why is /var full?'), null)
})

test('sources come from the thread id', () => {
  assert.equal(sourceOf('web-1f2e'), 'web')
  assert.equal(sourceOf('1526921636857516062'), 'discord')
  assert.equal(sourceOf('harbor'), 'other')
})

test('a transcript becomes one assistant message per turn with tool results attached', () => {
  const ui = toUIMessages(thread)
  assert.deepEqual(ui.map((m) => m.role), ['user', 'assistant', 'user', 'assistant', 'user'])
  const [tool, answer] = ui[1].parts
  assert.equal(tool.type, 'dynamic-tool')
  assert.equal(tool.type === 'dynamic-tool' && tool.state, 'output-available')
  assert.equal(tool.type === 'dynamic-tool' && tool.output, 'api: exited')
  assert.deepEqual(answer, { type: 'text', text: '`api` exited.', state: 'done' })
})

test('turns carry outcome, timing, latency and tokens', () => {
  const [first, second, third] = turnsOf(thread)
  assert.equal(first.outcome, 'answered')
  assert.equal(first.durationMs, 5000)
  assert.equal(first.steps[0].latencyMs, 1000)
  assert.equal(first.inputTokens, 30)
  assert.equal(second.outcome, 'failed')
  assert.equal(third.outcome, 'no answer')
  assert.equal(third.durationMs, null)
})

test('a call still awaiting approval comes back as an approval request', () => {
  const paused = thread.slice(0, 2)
  const [, assistant] = toUIMessages(paused, ['c1'])
  const [part] = assistant.parts
  assert.equal(part.type === 'dynamic-tool' && part.state, 'approval-requested')
  assert.deepEqual(part.type === 'dynamic-tool' && part.approval, { id: 'c1' })
})

test('a denied call comes back denied, not as an error', () => {
  const denied: Array<TranscriptMessage> = [
    ...thread.slice(0, 2),
    { id: 't9', type: 'tool', content: 'User rejected the tool call for `docker_status` with reason: no', at: at(3), tool_call_id: 'c1', name: 'docker_status', status: 'error' },
  ]
  const [part] = toUIMessages(denied)[1].parts
  assert.equal(part.type === 'dynamic-tool' && part.state, 'output-denied')
})
