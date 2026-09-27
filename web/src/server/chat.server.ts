import type { UIMessage, UIMessageStreamWriter } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import { COMMANDS, parseCommand } from '@/lib/commands'
import { AGENT_API_URL, AgentApiError, agentFetch, agentJson } from './agent-api.server'

type Writer = UIMessageStreamWriter<UIMessage>

export const ChatRequest = z.object({
  id: z.string().regex(/^web-[\w-]{1,64}$/),
  messages: z.array(z.custom<UIMessage>((m) => typeof m === 'object' && m !== null)).min(1).max(500),
  tools: z.array(z.string().max(100)).max(50).optional(),
})

type Chat = z.infer<typeof ChatRequest>

const Decided = z.object({
  type: z.literal('dynamic-tool'),
  toolCallId: z.string(),
  state: z.literal('approval-responded'),
  approval: z.object({ id: z.string(), approved: z.boolean() }),
})

// Commands the web server runs itself (the rest of the tool calls belong to the agent).
const Approved = z.object({
  type: z.literal('dynamic-tool'),
  toolCallId: z.string(),
  toolName: z.enum(['status', 'containers', 'watch', 'unwatch']),
  state: z.literal('approval-responded'),
  input: z.object({ container: z.string().min(1).max(200).optional() }),
  approval: z.object({ id: z.string(), approved: z.boolean() }),
})

function say(writer: Writer, text: string) {
  const id = crypto.randomUUID()
  writer.write({ type: 'text-start', id })
  writer.write({ type: 'text-delta', id, delta: text })
  writer.write({ type: 'text-end', id })
}

function askFirst(writer: Writer, name: string, input: Record<string, unknown>) {
  const toolCallId = crypto.randomUUID()
  writer.write({ type: 'tool-input-available', toolCallId, toolName: name, input, dynamic: true })
  writer.write({ type: 'tool-approval-request', approvalId: toolCallId, toolCallId })
}

const OUTDATED = `The agent API at ${AGENT_API_URL} is older than this web app and cannot ask before running tools, so nothing was sent. Restart it: uv run python -m agent api --host 127.0.0.1`
const UNAPPROVED =
  'The agent ran a tool that was not approved, so the answer was stopped. The agent API is probably out of date: restart it.'

// Approval must fail closed. `/tools` arrived with approval support, so an API without it would ignore the flag.
let approvalSupported = false
async function requireApprovalSupport() {
  if (approvalSupported) return
  try {
    await agentJson('/tools')
  } catch (error) {
    throw error instanceof AgentApiError && error.status === 404 ? new Error(OUTDATED) : error
  }
  approvalSupported = true
}

async function* serverSentEvents(body: ReadableStream<Uint8Array>) {
  const decoder = new TextDecoder()
  let buffer = ''
  for await (const bytes of body) {
    buffer += decoder.decode(bytes, { stream: true })
    let end: number
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const event = /^event: (.*)$/m.exec(frame)?.[1]
      const data = /^data: (.*)$/m.exec(frame)?.[1]
      if (event && data) yield { event, data: JSON.parse(data) }
    }
  }
}

// Web chats always run with approval: the agent pauses before each tool call until the person decides.
async function runAgent(
  writer: Writer,
  body: { thread_id: string; tools?: Array<string>; question?: string; report?: string; decisions?: Record<string, boolean> },
  signal: AbortSignal,
) {
  await requireApprovalSupport()
  const decided = new Set(Object.keys(body.decisions ?? {}))
  const denied = new Set(Object.entries(body.decisions ?? {}).flatMap(([id, ok]) => (ok ? [] : [id])))
  const response = await agentFetch('/investigate/stream', {
    method: 'POST',
    body: JSON.stringify({ ...body, approval: true }),
    signal,
  })
  let open: string | null = null
  const close = () => {
    if (open) writer.write({ type: 'text-end', id: open })
    open = null
  }
  for await (const { event, data } of serverSentEvents(response.body!)) {
    if (event === 'token') {
      const id = data.id ?? 'answer'
      if (open !== id) {
        close()
        open = id
        writer.write({ type: 'text-start', id })
      }
      writer.write({ type: 'text-delta', id, delta: data.text })
    } else if (event === 'tool_call') {
      close()
      writer.write({ type: 'tool-input-available', toolCallId: data.id, toolName: data.name, input: data.args, dynamic: true })
    } else if (event === 'tool_result') {
      // Only calls decided in this request may produce a result; anything else ran without asking.
      if (!decided.has(data.id)) {
        close()
        throw new Error(UNAPPROVED)
      }
      writer.write(
        denied.has(data.id)
          ? { type: 'tool-output-denied', toolCallId: data.id }
          : data.status === 'error'
          ? { type: 'tool-output-error', toolCallId: data.id, errorText: data.content, dynamic: true }
          : { type: 'tool-output-available', toolCallId: data.id, output: data.content, dynamic: true },
      )
    } else if (event === 'approval_required') {
      close()
      for (const call of data.tool_calls) {
        writer.write({ type: 'tool-approval-request', approvalId: call.id, toolCallId: call.id })
      }
    } else if (event === 'error') {
      close()
      throw new Error(data.message)
    }
  }
  close()
}

type Status = {
  containers: Array<{ name: string; state: string; status: string; image: string }>
  containers_down: Array<string>
  endpoints: Array<{ name: string; url: string; reachable: boolean }>
  endpoints_down: Array<string>
}

async function runCommand(writer: Writer, name: string, arg: string, chat: Chat, signal: AbortSignal) {
  const code = (items: Array<string>) => items.map((i) => `\`${i}\``).join(', ')
  switch (name) {
    case 'status':
    case 'containers':
      askFirst(writer, name, {})
      return
    case 'watchlist': {
      const { containers } = await agentJson<{ containers: Array<string> }>('/watchlist')
      say(writer, containers.length ? `**Watched containers:** ${code(containers)}` : 'No containers are pinned. Use `/watch <container>`.')
      return
    }
    case 'report': {
      if (!arg) return say(writer, 'Which service? Try `/report <service>`.')
      // Through the agent with approval, like any question, so the report's tool calls ask first.
      await runAgent(writer, { thread_id: chat.id, tools: chat.tools, report: arg }, signal)
      return
    }
    case 'digest': {
      const kind = arg || 'daily'
      if (kind !== 'daily' && kind !== 'weekly') return say(writer, 'Use `/digest daily` or `/digest weekly`.')
      const { body } = await agentJson<{ body: string }>(`/digest/${kind}`)
      say(writer, body)
      return
    }
    case 'watch':
    case 'unwatch': {
      if (!arg) return say(writer, `Which container? Try \`/${name} <container>\`.`)
      askFirst(writer, name, { container: arg })
      return
    }
    default:
      say(
        writer,
        ['**Commands**', ...COMMANDS.map((c) => `- \`${c.usage}\`: ${c.description}`), '', 'Anything else goes to the agent as a question.'].join('\n'),
      )
  }
}

async function runLocal(name: z.infer<typeof Approved>['toolName'], container?: string) {
  if (name === 'status') return agentJson<Status>('/status')
  if (name === 'containers') return agentJson('/containers')
  if (!container) throw new Error('No container was given.')
  return name === 'watch'
    ? agentJson('/watchlist', { method: 'POST', body: JSON.stringify({ container }) })
    : agentJson(`/watchlist/${encodeURIComponent(container)}`, { method: 'DELETE' })
}

function statusLine(status: Status) {
  const down = [...status.containers_down, ...status.endpoints_down]
  return down.length
    ? `**${down.length} down:** ${down.map((i) => `\`${i}\``).join(', ')}`
    : `All ${status.containers.length} containers and ${status.endpoints.length} endpoints are up.`
}

async function resolveApprovals(writer: Writer, message: UIMessage, chat: Chat, signal: AbortSignal) {
  const decisions: Record<string, boolean> = {}
  for (const part of message.parts) {
    const parsed = Approved.safeParse(part)
    if (!parsed.success) {
      const decided = Decided.safeParse(part)
      if (decided.success) decisions[decided.data.toolCallId] = decided.data.approval.approved
      continue
    }
    const { toolCallId, toolName, input, approval } = parsed.data
    if (!approval.approved) {
      writer.write({ type: 'tool-output-denied', toolCallId })
      continue
    }
    try {
      const output = await runLocal(toolName, input.container)
      writer.write({ type: 'tool-output-available', toolCallId, output, dynamic: true })
      if (toolName === 'status') say(writer, statusLine(output as Status))
    } catch (error) {
      writer.write({ type: 'tool-output-error', toolCallId, errorText: String((error as Error).message), dynamic: true })
    }
  }
  if (Object.keys(decisions).length) {
    await runAgent(writer, { thread_id: chat.id, tools: chat.tools, decisions }, signal)
  }
}

export function chatResponse(chat: Chat, signal: AbortSignal): Response {
  const { id, messages, tools } = chat
  const last = messages[messages.length - 1]
  const stream = createUIMessageStream({
    // Lets an approval's follow-up continue the assistant message that asked, instead of starting a new one.
    originalMessages: messages,
    execute: async ({ writer }) => {
      writer.write({ type: 'start' })
      if (last.role === 'assistant') {
        await resolveApprovals(writer, last, chat, signal)
      } else {
        const text = last.parts.flatMap((p) => (p.type === 'text' ? [p.text] : [])).join('\n').trim()
        const command = parseCommand(text)
        if (command) await runCommand(writer, command.name, command.arg, chat, signal)
        else if (text) await runAgent(writer, { thread_id: id, tools, question: text }, signal)
      }
      writer.write({ type: 'finish' })
    },
    onError: (error) => (error instanceof Error ? error.message : String(error)),
  })
  return createUIMessageStreamResponse({ stream })
}
