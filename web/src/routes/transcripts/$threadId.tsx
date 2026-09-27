import { Link, createFileRoute, notFound, stripSearchParams, useNavigate } from '@tanstack/react-router'
import { DownloadIcon, MessagesSquareIcon } from 'lucide-react'
import { z } from 'zod'
import { MessageResponse } from '@/components/ai-elements/message'
import { PageHeader } from '@/components/page-header'
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from '@/components/ai-elements/tool'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { formatDate } from '@/lib/format'
import type { Turn } from '@/lib/transcript'
import { formatMs, sourceOf, toolStats, turnsOf, wasDenied } from '@/lib/transcript'
import { getThread } from '@/server/functions'

const search = z.object({
  view: z.enum(['timeline', 'json']).default('timeline').catch('timeline'),
  turn: z.coerce.number().int().min(1).optional().catch(undefined),
})

export const Route = createFileRoute('/transcripts/$threadId')({
  validateSearch: search,
  search: { middlewares: [stripSearchParams({ view: 'timeline' })] },
  loader: async ({ params }) => {
    const thread = await getThread({ data: { threadId: params.threadId } })
    if (!thread) throw notFound()
    return thread.messages
  },
  head: () => ({ meta: [{ title: 'Oracle · Transcript' }] }),
  component: Transcript,
})

const median = (values: Array<number>) => {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="font-heading text-3xl tabular-nums">{value}</CardTitle>
        {detail && <CardDescription className="tabular-nums">{detail}</CardDescription>}
      </CardHeader>
    </Card>
  )
}

function TurnCard({ turn }: { turn: Turn }) {
  const results = new Map(turn.steps.map((s) => [s.call.id, s]))
  return (
    <Card id={`turn-${turn.index}`}>
      <CardHeader className="flex flex-row flex-wrap items-center gap-2">
        <CardTitle>Turn {turn.index}</CardTitle>
        <Badge variant={turn.outcome === 'answered' ? 'secondary' : 'destructive'}>{turn.outcome}</Badge>
        <span className="ml-auto text-sm text-muted-foreground tabular-nums">
          {formatMs(turn.durationMs)} · {turn.steps.length} tool {turn.steps.length === 1 ? 'call' : 'calls'}
          {turn.toolErrors > 0 && ` · ${turn.toolErrors} failed`}
          {turn.inputTokens + turn.outputTokens > 0 && ` · ${turn.inputTokens} in / ${turn.outputTokens} out tokens`}
        </span>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="ml-auto max-w-[85%] rounded-[22px] bg-secondary px-4 py-3 text-sm whitespace-pre-wrap">
          {turn.question.content}
        </div>
        {turn.messages.map((message) => {
          if (message.type === 'summary') {
            return (
              <Alert key={message.id}>
                <AlertTitle>Earlier turns were summarized here</AlertTitle>
                <AlertDescription className="line-clamp-3">{message.content}</AlertDescription>
              </Alert>
            )
          }
          if (message.type !== 'ai') return null
          return (
            <div key={message.id} className="flex flex-col gap-3">
              {message.content && (
                <MessageResponse className="text-sm">{message.content}</MessageResponse>
              )}
              {message.tool_calls?.map((call) => {
                const step = results.get(call.id)
                const denied = wasDenied(step?.result)
                const failed = !step?.result || step.result.status === 'error'
                return (
                  <Tool key={call.id} className="mb-0">
                    <ToolHeader
                      type="dynamic-tool"
                      toolName={call.name}
                      state={denied ? 'output-denied' : failed ? 'output-error' : 'output-available'}
                      title={`${call.name} · ${formatMs(step?.latencyMs ?? null)}`}
                    />
                    <ToolContent>
                      <ToolInput input={call.args} />
                      <ToolOutput
                        output={failed ? undefined : <pre className="p-3 font-mono whitespace-pre-wrap">{step?.result?.content}</pre>}
                        errorText={failed ? (step?.result?.content ?? 'No result was recorded.') : undefined}
                      />
                    </ToolContent>
                  </Tool>
                )
              })}
            </div>
          )
        })}
        {turn.outcome === 'no answer' && (
          <p className="text-sm text-muted-foreground">
            No final answer was recorded. The run timed out, failed before answering, or was stopped.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function Transcript() {
  const messages = Route.useLoaderData()
  const { threadId } = Route.useParams()
  const { view, turn } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })

  const turns = turnsOf(messages)
  const tools = toolStats(turns)
  const steps = turns.flatMap((t) => t.steps)
  const answered = turns.filter((t) => t.outcome === 'answered').length
  const failed = turns.filter((t) => t.outcome === 'failed').length
  const durations = turns.flatMap((t) => (t.durationMs == null ? [] : [t.durationMs]))
  const tokensIn = turns.reduce((n, t) => n + t.inputTokens, 0)
  const tokensOut = turns.reduce((n, t) => n + t.outputTokens, 0)
  const shown = turn ? turns.filter((t) => t.index === turn) : turns
  const origin = sourceOf(threadId)
  const json = JSON.stringify({ thread_id: threadId, messages }, null, 2)

  return (
    <div className="flex min-h-dvh flex-col">
      <PageHeader crumbs={[{ label: 'History', link: { to: '/conversations' } }, { label: 'Transcript' }]}>
          {origin === 'web' && (
            <Button asChild variant="secondary" size="sm">
              <Link to="/c/$threadId" params={{ threadId }}>
                <MessagesSquareIcon data-icon="inline-start" />
                Continue
              </Link>
            </Button>
          )}
          <Button asChild variant="secondary" size="sm">
            <a download={`${threadId}.json`} href={`data:application/json;charset=utf-8,${encodeURIComponent(json)}`}>
              <DownloadIcon data-icon="inline-start" />
              JSON
            </a>
          </Button>
      </PageHeader>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 p-4 md:p-8">
        <div className="flex flex-col gap-2">
          <h2 className="text-3xl font-medium md:text-4xl">{turns[0]?.question.content || 'Untitled'}</h2>
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="secondary">{origin}</Badge>
            <span className="font-mono">{threadId}</span>
            <span>·</span>
            <span className="tabular-nums">
              {formatDate(messages[0]?.at)} → {formatDate(messages.at(-1)?.at)} UTC
            </span>
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat label="Turns" value={String(turns.length)} detail={`${answered} answered · ${failed} failed · ${turns.length - answered - failed} no answer`} />
          <Stat label="Tool calls" value={String(steps.length)} detail={`${steps.filter((s) => !s.result || s.result.status === 'error').length} failed`} />
          <Stat label="Median turn" value={formatMs(median(durations))} detail={`slowest ${formatMs(durations.length ? Math.max(...durations) : null)}`} />
          <Stat label="Tokens" value={(tokensIn + tokensOut).toLocaleString('en-US')} detail={`${tokensIn.toLocaleString('en-US')} in · ${tokensOut.toLocaleString('en-US')} out`} />
        </div>

        {tools.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Tools</CardTitle>
              <CardDescription>Latency runs from the model's call to the recorded result.</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tool</TableHead>
                    <TableHead className="text-right">Calls</TableHead>
                    <TableHead className="text-right">Failed</TableHead>
                    <TableHead className="text-right">Avg latency</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tools.map((t) => (
                    <TableRow key={t.name}>
                      <TableCell className="font-mono">{t.name}</TableCell>
                      <TableCell className="text-right tabular-nums">{t.calls}</TableCell>
                      <TableCell className="text-right tabular-nums">{t.errors}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatMs(t.avgMs)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        <Tabs value={view} onValueChange={(value) => navigate({ search: (s) => ({ ...s, view: value as typeof view }) })}>
          <div className="flex flex-wrap items-center gap-3">
            <TabsList>
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
              <TabsTrigger value="json">Raw JSON</TabsTrigger>
            </TabsList>
            {view === 'timeline' && turns.length > 1 && turns.length <= 30 && (
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={turn ? String(turn) : 'all'}
                onValueChange={(value) =>
                  value && navigate({ search: (s) => ({ ...s, turn: value === 'all' ? undefined : Number(value) }) })
                }
              >
                <ToggleGroupItem value="all">All</ToggleGroupItem>
                {turns.map((t) => (
                  <ToggleGroupItem key={t.index} value={String(t.index)}>
                    {t.index}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            )}
          </div>
          <TabsContent value="timeline" className="flex flex-col gap-4 pt-4">
            {shown.map((t) => (
              <TurnCard key={t.index} turn={t} />
            ))}
          </TabsContent>
          <TabsContent value="json" className="pt-4">
            <ScrollArea className="h-[70dvh] rounded-xl border bg-card">
              <pre className="p-4 font-mono text-xs">{json}</pre>
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
