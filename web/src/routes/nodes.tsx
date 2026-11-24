import { createFileRoute, useRouter } from '@tanstack/react-router'
import { RotateCwIcon, ServerIcon } from 'lucide-react'
import { NodeTable } from '@/components/node-table'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { listNodes } from '@/server/functions'

export const Route = createFileRoute('/nodes')({
  loader: () => listNodes(),
  head: () => ({ meta: [{ title: 'Nodes · Oracle' }] }),
  component: Nodes,
})

function Nodes() {
  const nodes = Route.useLoaderData()
  const router = useRouter()
  const down = nodes.filter((n) => n.down).length
  return (
    <div className="flex min-h-dvh flex-col">
      <PageHeader crumbs={[{ label: 'Nodes' }]}>
        <Button variant="ghost" size="sm" onClick={() => router.invalidate({ filter: (m) => m.routeId === Route.id })}>
          <RotateCwIcon data-icon="inline-start" />
          Refresh
        </Button>
      </PageHeader>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 md:p-8">
        <div className="flex flex-col gap-2">
          <h1 className="text-4xl font-medium md:text-5xl">Nodes</h1>
          <p className="text-muted-foreground">
            {nodes.length
              ? `${nodes.length} machines, ${down ? `${down} down` : 'all up'}. Docker state comes from each node over SSH; the readings come from Prometheus.`
              : 'The machines the agent can see, with their health.'}
          </p>
        </div>
        {nodes.length ? (
          <Card>
            <CardContent>
              <NodeTable nodes={nodes} />
            </CardContent>
          </Card>
        ) : (
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ServerIcon />
              </EmptyMedia>
              <EmptyTitle>No nodes configured</EmptyTitle>
              <EmptyDescription>
                The agent is watching one Docker host. Set <code className="font-mono">NODES</code> in its{' '}
                <code className="font-mono">.env</code> to list every machine.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </div>
    </div>
  )
}
