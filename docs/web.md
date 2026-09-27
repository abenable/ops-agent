# The web app

A browser front end for the same agent the Discord bot runs, for people who
would rather not use Discord. It lives in `web/` and talks to the agent only
through the [HTTP API](api.md); it has no database or agent logic of its own.

## What it does

| Page | Path | What's there |
|---|---|---|
| Chat | `/c/{thread}` | Ask questions and watch the answer stream in, with a card for every tool call. `/` opens a new conversation. |
| History | `/conversations` | Every conversation the agent remembers, searchable and filterable by source: this app, Discord, or API and eval runs. |
| Reports | `/reports` | The daily or weekly digest the bot posts to Discord, rendered on demand, and incident reports: pick a container and it opens as a conversation. |
| Transcript | `/transcripts/{thread}` | One conversation laid out for review: per-turn outcome (answered, failed, no answer), duration, tool calls with arguments, results and latency, token counts, a per-tool table, and the raw JSON to download. |

Every tool call the agent makes from the web asks first. The run pauses, a
pop-up lists the calls with their arguments, and nothing runs until you approve
or deny each one (or all at once). You can also answer from the card in the
chat. A denied call does not run; the agent is told so and answers from what it
has. A reload keeps the pending calls, and a new question is refused until they
are decided. The **Tools** menu in the message box chooses which tools the agent
may use at all; the choice is remembered in this browser. Discord and the plain
`/investigate` API are unchanged and do not ask.

Approval fails closed. If the API is too old to support it, the chat says so
and sends nothing; and if a tool result ever arrives for a call nobody
approved, the web server stops the answer there.

The chat also takes the Discord bot's commands: `/status`, `/containers`,
`/watchlist`, `/report <service>` (run by the agent, so its tool calls ask too), `/digest [daily|weekly]`, `/help`, and
`/watch` / `/unwatch <container>`. `/status`, `/containers`, `/watch` and `/unwatch`
ask for approval the same way.

Web conversations use thread ids starting `web-`, so they never share memory
with a Discord channel. Discord and API threads open read-only as transcripts;
continuing them from the web would write into that channel's history. Command
results are not stored in agent memory, so a reloaded chat shows the
investigations but not the command output.

History includes Discord DMs. Anyone who can reach the web app, or the API's
`/threads` routes, can read them.

## Running it

It needs the API running. With the API on its defaults, the web app finds it
without configuration: it reads `API_PORT` and `API_KEY` from the repository's
`.env` and nothing else from that file.

```bash
docker compose up -d api        # or: uv run python -m agent api
cd web
npm install
npm run dev                     # http://localhost:3000
```

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_API_URL` | `http://127.0.0.1:${API_PORT}` | Where the API is. Set it when the API is on another host or port. |
| `API_KEY` | from `.env` | Sent as `X-API-Key` when the API requires one. It stays on the web server. |
| `HOST` / `PORT` | `127.0.0.1` / `3000` in Compose | Where the built server listens. |

`npm test` runs the transcript and command-parsing tests, and `npm run typecheck`
checks types.

## Deploying it

`docker compose up -d web` builds `web/Dockerfile` and runs it next to the API
on the host network. It binds to loopback for the same reason the API does:
the app has no login. Set `WEB_HOST` to widen it, and only put it where the
network already restricts who can reach it.

`npm run build` produces a Node server in `.output/`, started with
`npm start`. The build target comes from [Nitro](https://nitro.build). Set
`NITRO_PRESET` at build time (for example `bun`, `deno-server`, or a hosting
platform's preset) to target another runtime; the routes and code stay the
same.

## How it is built

TanStack Start with file-based routes in `web/src/routes/`:

- **Chat** renders its data on the server and its interface in the browser
  (`ssr: 'data-only'`), since it is a live stream with scroll anchoring. History
  and transcripts are fully server-rendered. The sidebar's recent list and API
  status stream in after the page shell.
- **Search params** (`q`, `source`, `page` on history; `view`, `turn` on
  transcripts) are validated with zod, and bad values fall back to defaults.
- **Server-only code** is in `web/src/server/*.server.ts`, which the build
  refuses to bundle for the browser. The API URL and key never leave the
  server. Typed server functions in `web/src/server/functions.ts` feed the
  loaders.
- **Streaming** goes through one server route, `POST /api/chat`. It relays the
  API's `/investigate/stream` events as an AI SDK UI message stream, which the
  chat renders with AI Elements (message, tool, confirmation, shimmer,
  prompt input) on shadcn/ui.

The look follows `web/DESIGN.md` (from `npx getdesign@latest add framer`) with
the palette cut to black, white and grays. The sidebar is shadcn's `sidebar-07`
block, collapsing to icons, with the Marconi Lab logo recoloured for the dark
background (`web/public/`).
