import { createIsomorphicFn, createServerFn } from '@tanstack/react-start'
import { getCookie } from '@tanstack/react-start/server'
import { z } from 'zod'
import type { AgentTool, Thread, TranscriptMessage } from '@/lib/transcript'
import { sourceOf } from '@/lib/transcript'
import { AgentApiError, agentJson } from './agent-api.server'

export const listThreads = createServerFn()
  .validator(
    z.object({
      q: z.string().max(200).optional(),
      source: z.enum(['all', 'web', 'discord', 'other']).default('all'),
      page: z.number().int().min(1).default(1),
      perPage: z.number().int().min(1).max(100).default(25),
    }),
  )
  .handler(async ({ data }) => {
    const { threads } = await agentJson<{ threads: Array<Thread> }>('/threads')
    const q = data.q?.toLowerCase()
    const matching = threads.filter(
      (t) =>
        (data.source === 'all' || sourceOf(t.thread_id) === data.source) &&
        (!q || t.title.toLowerCase().includes(q) || t.thread_id.includes(q)),
    )
    const start = (data.page - 1) * data.perPage
    return {
      threads: matching.slice(start, start + data.perPage),
      total: matching.length,
      pages: Math.max(1, Math.ceil(matching.length / data.perPage)),
    }
  })

export const getThread = createServerFn()
  .validator(z.object({ threadId: z.string().min(1).max(100) }))
  .handler(async ({ data }) => {
    try {
      return await agentJson<{ messages: Array<TranscriptMessage>; awaiting_approval: Array<string> }>(
        `/threads/${encodeURIComponent(data.threadId)}`,
      )
    } catch (error) {
      if (error instanceof AgentApiError && error.status === 404) return null
      throw error
    }
  })

export const listTools = createServerFn().handler(
  async () => (await agentJson<{ tools: Array<AgentTool> }>('/tools')).tools,
)

export const getDigest = createServerFn()
  .validator(z.object({ kind: z.enum(['daily', 'weekly']) }))
  .handler(async ({ data }) => {
    try {
      return await agentJson<{ kind: string; generated_at: string; body: string }>(`/digest/${data.kind}`)
    } catch (error) {
      return { error: (error as Error).message }
    }
  })

export const listContainers = createServerFn().handler(
  async () => (await agentJson<{ containers: Array<{ name: string; state: string; status: string }> }>('/containers')).containers,
)

// shadcn's sidebar remembers its state in this cookie; reading it here keeps a reload from reopening it.
export const sidebarOpen = createIsomorphicFn()
  .server(() => getCookie('sidebar_state') !== 'false')
  .client(() => !document.cookie.includes('sidebar_state=false'))
