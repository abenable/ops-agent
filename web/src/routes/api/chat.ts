import { createFileRoute } from '@tanstack/react-router'
import { ChatRequest, chatResponse } from '@/server/chat.server'

export const Route = createFileRoute('/api/chat')({
  server: {
    handlers: {
      POST: async ({ request }) => {
        // JSON-only: a cross-site form or text/plain post can't reach the agent without a CORS preflight.
        if (!request.headers.get('content-type')?.startsWith('application/json')) {
          return new Response('Expected application/json', { status: 415 })
        }
        const parsed = ChatRequest.safeParse(await request.json().catch(() => null))
        if (!parsed.success) return Response.json({ error: parsed.error.issues }, { status: 400 })
        return chatResponse(parsed.data, request.signal)
      },
    },
  },
})
