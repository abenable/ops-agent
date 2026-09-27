import { createFileRoute, redirect } from '@tanstack/react-router'
import { z } from 'zod'
import { Chat } from '@/components/chat'
import { Skeleton } from '@/components/ui/skeleton'
import { sourceOf, toUIMessages } from '@/lib/transcript'
import { getThread, listTools } from '@/server/functions'

export const Route = createFileRoute('/c/$threadId')({
  // The chat is live client state (streaming, scroll anchoring), so only its data is server-rendered.
  ssr: 'data-only',
  // `ask` opens the chat with that message already sent (the Reports page uses it).
  validateSearch: z.object({ ask: z.string().max(2000).optional().catch(undefined) }),
  beforeLoad: ({ params }) => {
    // Discord and API threads are read-only here: continuing them would write into that channel's memory.
    if (sourceOf(params.threadId) !== 'web') {
      throw redirect({ to: '/transcripts/$threadId', params })
    }
  },
  loader: async ({ params }) => {
    // No tool list means an API too old to ask before running tools; the chat refuses to send (null).
    const [thread, tools] = await Promise.all([
      getThread({ data: { threadId: params.threadId } }),
      listTools().catch(() => null),
    ])
    return { messages: toUIMessages(thread?.messages ?? [], thread?.awaiting_approval), tools }
  },
  head: () => ({ meta: [{ title: 'Oracle · Conversation' }] }),
  pendingComponent: ChatSkeleton,
  component: ChatRoute,
})

function ChatRoute() {
  const { threadId } = Route.useParams()
  const { messages, tools } = Route.useLoaderData()
  const { ask } = Route.useSearch()
  return <Chat key={threadId} threadId={threadId} initialMessages={messages} tools={tools} ask={ask} />
}

function ChatSkeleton() {
  return (
    <div className="mx-auto flex h-dvh w-full max-w-3xl flex-col gap-6 p-4 pt-20">
      <Skeleton className="ml-auto h-10 w-1/2 rounded-lg" />
      <Skeleton className="h-24 w-4/5 rounded-lg" />
      <Skeleton className="mt-auto h-28 w-full rounded-xl" />
    </div>
  )
}
