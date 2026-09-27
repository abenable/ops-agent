import { Await, createFileRoute, stripSearchParams, useNavigate, useRouter } from '@tanstack/react-router'
import { FileWarningIcon, RotateCwIcon } from 'lucide-react'
import { useState } from 'react'
import { z } from 'zod'
import { MessageResponse } from '@/components/ai-elements/message'
import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { formatDate } from '@/lib/format'
import { newThreadId } from '@/lib/transcript'
import { getDigest, listContainers } from '@/server/functions'

export const Route = createFileRoute('/reports')({
  validateSearch: z.object({ period: z.enum(['daily', 'weekly']).default('daily').catch('daily') }),
  search: { middlewares: [stripSearchParams({ period: 'daily' })] },
  loaderDeps: ({ search: { period } }) => ({ period }),
  // The digest takes a few seconds (it ends with an LLM summary), so it streams in after the page.
  loader: ({ deps }) => ({
    digest: getDigest({ data: { kind: deps.period } }),
    containers: listContainers().catch(() => []),
  }),
  head: () => ({ meta: [{ title: 'Oracle · Reports' }] }),
  component: Reports,
})

function DigestSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="mt-4 h-4 w-1/4" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  )
}

function IncidentReport({ containers }: { containers: Array<{ name: string; state: string }> }) {
  const navigate = useNavigate()
  const [service, setService] = useState('')
  return (
    <Card>
      <CardHeader>
        <CardTitle>Incident report</CardTitle>
        <CardDescription>
          A structured write-up for one service: what happened, evidence, likely cause, next steps. It opens as a
          conversation, and each tool call asks for approval.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Select value={service} onValueChange={setService}>
          <SelectTrigger className="w-full md:w-80">
            <SelectValue placeholder={containers.length ? 'Choose a container' : 'No containers found'} />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {containers.map((c) => (
                <SelectItem key={c.name} value={c.name}>
                  <span className="font-mono">{c.name}</span>
                  <span className="text-muted-foreground">{c.state}</span>
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </CardContent>
      <CardFooter>
        <Button
          disabled={!service}
          onClick={() => navigate({ to: '/c/$threadId', params: { threadId: newThreadId() }, search: { ask: `/report ${service}` } })}
        >
          <FileWarningIcon data-icon="inline-start" />
          Write report
        </Button>
      </CardFooter>
    </Card>
  )
}

function Reports() {
  const { digest, containers } = Route.useLoaderData()
  const { period } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const router = useRouter()

  return (
    <div className="flex min-h-dvh flex-col">
      <PageHeader crumbs={[{ label: 'Reports' }]} />
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-4 md:p-8">
        <div className="flex flex-col gap-2">
          <h2 className="text-4xl font-medium md:text-5xl">Reports</h2>
          <p className="text-muted-foreground">
            The digests the bot posts to Discord on its schedule, rendered now, and incident reports on demand.
          </p>
        </div>

        <Card>
          <CardHeader className="flex flex-row flex-wrap items-center gap-3">
            <div className="flex flex-col gap-1.5">
              <CardTitle>{period === 'daily' ? 'Daily digest' : 'Weekly digest'}</CardTitle>
              <CardDescription>
                {period === 'daily'
                  ? 'Current state and every up/down change in the last 24 hours.'
                  : 'Current state and outage totals over the lookback window.'}
              </CardDescription>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={period}
                onValueChange={(value) => value && navigate({ search: { period: value as typeof period } })}
              >
                <ToggleGroupItem value="daily">Daily</ToggleGroupItem>
                <ToggleGroupItem value="weekly">Weekly</ToggleGroupItem>
              </ToggleGroup>
              <Button variant="secondary" size="sm" onClick={() => router.invalidate({ filter: (m) => m.routeId === Route.id })}>
                <RotateCwIcon data-icon="inline-start" />
                Regenerate
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <Await promise={digest} fallback={<DigestSkeleton />}>
              {(result) =>
                'error' in result ? (
                  <Alert variant="destructive">
                    <AlertTitle>Couldn't build the digest</AlertTitle>
                    <AlertDescription>{result.error}</AlertDescription>
                  </Alert>
                ) : (
                  <div className="flex flex-col gap-4">
                    <MessageResponse className="text-sm">{result.body}</MessageResponse>
                    <p className="text-xs text-muted-foreground tabular-nums">Generated {formatDate(result.generated_at)} UTC</p>
                  </div>
                )
              }
            </Await>
          </CardContent>
        </Card>

        <Await promise={containers} fallback={<Skeleton className="h-48 w-full rounded-xl" />}>
          {(list) => <IncidentReport containers={list} />}
        </Await>
      </div>
    </div>
  )
}
