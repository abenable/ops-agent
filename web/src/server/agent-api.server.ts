import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parseEnv } from 'node:util'

// The agent's own .env, so `npm run dev` beside the Python API needs no setup.
// Only API_KEY and API_PORT are read from it; the LLM and Discord secrets stay out.
function repoEnv(): Record<string, string | undefined> {
  try {
    return parseEnv(readFileSync(resolve(process.cwd(), '../.env'), 'utf8'))
  } catch {
    return {}
  }
}

const fallback = repoEnv()
const setting = (name: string) => process.env[name] ?? fallback[name]

export const AGENT_API_URL = (
  process.env.AGENT_API_URL ?? `http://127.0.0.1:${setting('API_PORT') ?? '8000'}`
).replace(/\/+$/, '')

const API_KEY = setting('API_KEY') ?? ''

export class AgentApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

export async function agentFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (API_KEY) headers.set('X-API-Key', API_KEY)
  if (init.body) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(`${AGENT_API_URL}${path}`, { ...init, headers })
  } catch (error) {
    if (init.signal?.aborted) throw error
    throw new AgentApiError(503, `The agent API is unreachable at ${AGENT_API_URL}.`)
  }
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body.detail)
      .catch(() => response.statusText)
    throw new AgentApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return response
}

export async function agentJson<T>(path: string, init?: RequestInit): Promise<T> {
  return (await agentFetch(path, init)).json() as Promise<T>
}
