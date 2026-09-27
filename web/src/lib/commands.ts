export const COMMANDS = [
  { name: 'status', usage: '/status', description: 'Health of every container and endpoint' },
  { name: 'containers', usage: '/containers', description: 'Every in-scope container with its state' },
  { name: 'watchlist', usage: '/watchlist', description: 'Containers pinned into monitoring' },
  { name: 'report', usage: '/report <service>', description: 'Structured incident report for one service' },
  { name: 'digest', usage: '/digest [daily|weekly]', description: 'Render a scheduled digest now' },
  { name: 'watch', usage: '/watch <container>', description: 'Pin a container into monitoring (asks first)' },
  { name: 'unwatch', usage: '/unwatch <container>', description: 'Unpin a container (asks first)' },
  { name: 'help', usage: '/help', description: 'What the agent can do' },
] as const

export type CommandName = (typeof COMMANDS)[number]['name']

export function parseCommand(text: string): { name: CommandName; arg: string } | null {
  const match = /^\/(\w+)\s*(.*)$/s.exec(text.trim())
  const found = match && COMMANDS.find((c) => c.name === match[1].toLowerCase())
  return found ? { name: found.name, arg: match[2].trim() } : null
}
