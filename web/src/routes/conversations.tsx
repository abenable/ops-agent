import { Link, createFileRoute, stripSearchParams, useNavigate, useRouter } from '@tanstack/react-router'
import { FileTextIcon, MessagesSquareIcon, SearchIcon } from 'lucide-react'
import { z } from 'zod'
import { PageHeader } from '@/components/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { sourceOf } from '@/lib/transcript'
import { listThreads } from '@/server/functions'

const search = z.object({
  q: z.string().trim().max(200).optional().catch(undefined),
  source: z.enum(['all', 'web', 'discord', 'other']).default('all').catch('all'),
  page: z.coerce.number().int().min(1).default(1).catch(1),
})

export const Route = createFileRoute('/conversations')({
  validateSearch: search,
  search: { middlewares: [stripSearchParams({ source: 'all', page: 1 })] },
  loaderDeps: ({ search: { q, source, page } }) => ({ q, source, page }),
  loader: ({ deps }) => listThreads({ data: deps }),
  head: () => ({ meta: [{ title: 'Oracle · Conversations' }] }),
  component: Conversations,
})

const SOURCES = [
  ['all', 'All'],
  ['web', 'Web'],
  ['discord', 'Discord'],
  ['other', 'API & eval'],
] as const

function Conversations() {
  const { threads, total, pages } = Route.useLoaderData()
  const { q, source, page } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const router = useRouter()
  const pageLink = (target: number) => {
    const disabled = target < 1 || target > pages
    return {
      href: router.buildLocation({ to: Route.fullPath, search: (s) => ({ ...s, page: target }) }).href,
      'aria-disabled': disabled,
      tabIndex: disabled ? -1 : undefined,
      className: cn(disabled && 'pointer-events-none opacity-50'),
      onClick: (e: React.MouseEvent) => {
        e.preventDefault()
        navigate({ search: (s) => ({ ...s, page: target }) })
      },
    }
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <PageHeader crumbs={[{ label: 'History' }]}>
        <span className="text-sm text-muted-foreground tabular-nums">{total} conversations</span>
      </PageHeader>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 md:p-8">
        <div className="flex flex-col gap-2">
          <h2 className="text-4xl font-medium md:text-5xl">History</h2>
          <p className="text-muted-foreground">
            Every conversation the agent remembers, from this app, Discord channels and DMs, and the API.
          </p>
        </div>
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <form
            className="md:max-w-sm md:flex-1"
            onSubmit={(e) => {
              e.preventDefault()
              const value = new FormData(e.currentTarget).get('q')?.toString().trim()
              navigate({ search: (s) => ({ ...s, q: value || undefined, page: 1 }) })
            }}
          >
            <InputGroup>
              <InputGroupAddon>
                <SearchIcon />
              </InputGroupAddon>
              <InputGroupInput name="q" defaultValue={q} placeholder="Search questions" key={q} />
            </InputGroup>
          </form>
          <ToggleGroup
            type="single"
            variant="outline"
            value={source}
            onValueChange={(value) => value && navigate({ search: (s) => ({ ...s, source: value as typeof source, page: 1 }) })}
          >
            {SOURCES.map(([value, label]) => (
              <ToggleGroupItem key={value} value={value}>
                {label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
        {threads.length === 0 ? (
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <MessagesSquareIcon />
              </EmptyMedia>
              <EmptyTitle>No conversations</EmptyTitle>
              <EmptyDescription>{q ? `Nothing matches "${q}".` : 'Ask the agent something to start one.'}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="overflow-hidden rounded-xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Opening question</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="text-right">Turns</TableHead>
                  <TableHead>Last active (UTC)</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {threads.map((thread) => {
                  const origin = sourceOf(thread.thread_id)
                  return (
                    <TableRow key={thread.thread_id}>
                      <TableCell className="max-w-md">
                        {origin === 'web' ? (
                          <Link to="/c/$threadId" params={{ threadId: thread.thread_id }} className="block truncate hover:underline">
                            {thread.title || 'Untitled'}
                          </Link>
                        ) : (
                          <span className="block truncate">{thread.title || 'Untitled'}</span>
                        )}
                        <span className="block truncate font-mono text-xs text-muted-foreground">{thread.thread_id}</span>
                      </TableCell>
                      <TableCell>
                        <Badge variant={origin === 'web' ? 'default' : 'secondary'}>{origin}</Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{thread.turns}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground tabular-nums">
                        {formatDate(thread.updated_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button asChild variant="ghost" size="sm">
                          <Link to="/transcripts/$threadId" params={{ threadId: thread.thread_id }}>
                            <FileTextIcon data-icon="inline-start" />
                            Transcript
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
        {pages > 1 && (
          <Pagination>
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious {...pageLink(page - 1)} />
              </PaginationItem>
              <PaginationItem className="px-3 text-sm text-muted-foreground tabular-nums">
                {page} / {pages}
              </PaginationItem>
              <PaginationItem>
                <PaginationNext {...pageLink(page + 1)} />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        )}
      </div>
    </div>
  )
}
