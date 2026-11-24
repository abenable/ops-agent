import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

// One row of the agent's GET /nodes. A reading is null when it's unknown (no Prometheus, or no such sensor).
export type AgentNode = {
  name: string
  down: boolean
  up?: boolean | null
  docker_reachable: boolean | null
  containers: number | null
  running: number | null
  cpu_percent?: number | null
  memory_percent?: number | null
  temperature_c?: number | null
  undervoltage?: number | null
  throttled?: number | null
  power_mw?: number | null
}

const reading = (value: number | null | undefined, unit: string) => (value == null ? '–' : `${value}${unit}`)

function containersCell(node: AgentNode) {
  if (node.docker_reachable === false) return <span className="text-destructive">Docker unreachable</span>
  if (node.containers == null) return '–'
  return (
    <span className={node.running === node.containers ? undefined : 'text-destructive'}>
      {node.running}/{node.containers} running
    </span>
  )
}

export function NodeTable({ nodes }: { nodes: Array<AgentNode> }) {
  return (
    <Table>
      <caption className="sr-only">Nodes and their health</caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Node</TableHead>
          <TableHead scope="col">Health</TableHead>
          <TableHead scope="col">Containers</TableHead>
          <TableHead scope="col" className="text-right">CPU</TableHead>
          <TableHead scope="col" className="text-right">Memory</TableHead>
          <TableHead scope="col" className="text-right">Temp</TableHead>
          <TableHead scope="col" className="text-right">Power</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {nodes.map((n) => (
          <TableRow key={n.name}>
            <TableCell className="font-mono">{n.name}</TableCell>
            <TableCell>
              <span className="flex flex-wrap gap-1.5">
                <Badge variant={n.down ? 'destructive' : 'secondary'}>{n.down ? 'Down' : 'Up'}</Badge>
                {n.undervoltage ? <Badge variant="destructive">Undervoltage</Badge> : null}
                {n.throttled ? <Badge variant="destructive">Throttled</Badge> : null}
              </span>
            </TableCell>
            <TableCell>{containersCell(n)}</TableCell>
            <TableCell className="text-right tabular-nums">{reading(n.cpu_percent, '%')}</TableCell>
            <TableCell className="text-right tabular-nums">{reading(n.memory_percent, '%')}</TableCell>
            <TableCell className="text-right tabular-nums">{reading(n.temperature_c, ' °C')}</TableCell>
            <TableCell className="text-right tabular-nums">{reading(n.power_mw, ' mW')}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
