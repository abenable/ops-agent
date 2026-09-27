import { useChat } from '@ai-sdk/react'
import { Link, rootRouteId, useNavigate, useRouter } from '@tanstack/react-router'
import type { DynamicToolUIPart, UIMessage } from 'ai'
import { DefaultChatTransport, lastAssistantMessageIsCompleteWithApprovalResponses } from 'ai'
import { BotIcon, CheckIcon, FileTextIcon, RotateCwIcon, SparklesIcon, UserIcon, WrenchIcon, XIcon } from 'lucide-react'
import { Fragment, useEffect, useRef, useState } from 'react'
import {
  Confirmation,
  ConfirmationAccepted,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRejected,
  ConfirmationRequest,
  ConfirmationTitle,
} from '@/components/ai-elements/confirmation'
import { Conversation, ConversationContent, ConversationScrollButton } from '@/components/ai-elements/conversation'
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message'
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputProvider,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputController,
} from '@/components/ai-elements/prompt-input'
import { Shimmer } from '@/components/ai-elements/shimmer'
import { Suggestion, Suggestions } from '@/components/ai-elements/suggestion'
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from '@/components/ai-elements/tool'
import { PageHeader } from '@/components/page-header'
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Command, CommandGroup, CommandItem, CommandList } from '@/components/ui/command'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Kbd } from '@/components/ui/kbd'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { COMMANDS, parseCommand } from '@/lib/commands'
import type { AgentTool } from '@/lib/transcript'
import { cn } from '@/lib/utils'

const SUGGESTIONS = ['What is down right now?', 'Why did a container restart recently?', '/status', '/containers']

type Container = { name: string; state: string; status: string; image?: string }

function ContainerTable({ containers }: { containers: Array<Container> }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Container</TableHead>
          <TableHead>State</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {containers.map((c) => (
          <TableRow key={c.name}>
            <TableCell className="font-mono">{c.name}</TableCell>
            <TableCell className={c.state === 'running' ? undefined : 'text-destructive'}>{c.state}</TableCell>
            <TableCell className="text-muted-foreground">{c.status}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function output(part: DynamicToolUIPart) {
  if (part.state !== 'output-available') return undefined
  const value = part.output as { containers?: Array<Container> } | string
  if (typeof value === 'object' && Array.isArray(value.containers) && typeof value.containers[0] === 'object') {
    return <ContainerTable containers={value.containers} />
  }
  return typeof value === 'string' ? <pre className="p-3 font-mono whitespace-pre-wrap">{value}</pre> : value
}

type Approve = (response: { id: string; approved: boolean }) => void

const hasContent = (m: UIMessage) => m.parts.some((p) => (p.type === 'text' && p.text) || p.type === 'dynamic-tool')

function ask(part: DynamicToolUIPart) {
  const container = <code className="font-mono">{(part.input as { container?: string } | undefined)?.container}</code>
  if (part.toolName === 'watch') return <>Pin {container} into monitoring? Status updates will include it.</>
  if (part.toolName === 'unwatch') return <>Stop watching {container}? It drops out of status updates.</>
  if (part.toolName === 'status') return <>Check the health of every container and endpoint?</>
  if (part.toolName === 'containers') return <>List every container and its state?</>
  return (
    <>
      Run <code className="font-mono">{part.toolName}</code>? It only reads.
    </>
  )
}

function ToolPart({ part, onApprove }: { part: DynamicToolUIPart; onApprove: Approve }) {
  return (
    <>
      <Confirmation approval={part.approval} state={part.state}>
        <ConfirmationTitle>{ask(part)}</ConfirmationTitle>
        <ConfirmationRequest>
          <ConfirmationActions>
            <ConfirmationAction variant="outline" onClick={() => onApprove({ id: part.approval!.id, approved: false })}>
              Deny
            </ConfirmationAction>
            <ConfirmationAction onClick={() => onApprove({ id: part.approval!.id, approved: true })}>
              Approve
            </ConfirmationAction>
          </ConfirmationActions>
        </ConfirmationRequest>
        <ConfirmationAccepted>
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <CheckIcon className="size-4" /> Approved
          </span>
        </ConfirmationAccepted>
        <ConfirmationRejected>
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <XIcon className="size-4" /> Denied, not run
          </span>
        </ConfirmationRejected>
      </Confirmation>
      {part.state !== 'approval-requested' && part.state !== 'output-denied' && (
        <Tool defaultOpen={part.state === 'output-error'}>
          <ToolHeader type="dynamic-tool" toolName={part.toolName} state={part.state} />
          <ToolContent>
            {part.input != null && Object.keys(part.input).length > 0 ? <ToolInput input={part.input} /> : null}
            <ToolOutput output={output(part)} errorText={part.state === 'output-error' ? part.errorText : undefined} />
          </ToolContent>
        </Tool>
      )}
    </>
  )
}

function RoleAvatar({ role }: { role: UIMessage['role'] }) {
  return (
    <Avatar className={cn(role === 'user' && 'mt-1.5')}>
      <AvatarFallback>{role === 'user' ? <UserIcon className="size-4" /> : <BotIcon className="size-4" />}</AvatarFallback>
    </Avatar>
  )
}

function ChatMessage({ message, animating, onApprove }: { message: UIMessage; animating: boolean; onApprove: Approve }) {
  return (
    <div className={cn('flex items-start gap-3', message.role === 'user' && 'flex-row-reverse')}>
      <RoleAvatar role={message.role} />
      <Message from={message.role} className="min-w-0">
      <MessageContent>
        {message.parts.map((part, i) => {
          if (part.type === 'text') {
            return message.role === 'user' ? (
              <p key={i} className="whitespace-pre-wrap">
                {part.text}
              </p>
            ) : (
              <MessageResponse key={i} isAnimating={animating}>
                {part.text}
              </MessageResponse>
            )
          }
          if (part.type === 'dynamic-tool') return <ToolPart key={part.toolCallId} part={part} onApprove={onApprove} />
          return null
        })}
      </MessageContent>
      </Message>
    </div>
  )
}

function CommandHints() {
  const { textInput } = usePromptInputController()
  const typed = textInput.value
  if (!typed.startsWith('/') || typed.includes(' ')) return null
  const matches = COMMANDS.filter((c) => `/${c.name}`.startsWith(typed.toLowerCase()))
  if (!matches.length) return null
  return (
    <Command shouldFilter={false} className="mb-2 h-auto rounded-xl border animate-in fade-in-0 slide-in-from-bottom-1">
      <CommandList>
        <CommandGroup heading="Commands">
          {matches.map((c) => (
            <CommandItem
              key={c.name}
              value={c.name}
              onSelect={() => textInput.setInput(/[<[]/.test(c.usage) ? `/${c.name} ` : `/${c.name}`)}
            >
              <span className="font-mono">{c.usage}</span>
              <span className="truncate text-muted-foreground">{c.description}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </Command>
  )
}

function Intro({ onPick }: { onPick: (text: string) => void }) {
  return (
    <Empty className="min-h-[60dvh]">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SparklesIcon />
        </EmptyMedia>
        <EmptyTitle className="font-heading text-3xl tracking-tight">Ask Oracle about the lab</EmptyTitle>
        <EmptyDescription>
          It reads Docker, Prometheus, and Loki to answer, and never changes anything. Type <Kbd>/</Kbd> for commands.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Suggestions>
          {SUGGESTIONS.map((s) => (
            <Suggestion key={s} suggestion={s} onClick={onPick} />
          ))}
        </Suggestions>
      </EmptyContent>
    </Empty>
  )
}

function ApprovalDialog({ pending, onApprove }: { pending: Array<DynamicToolUIPart>; onApprove: Approve }) {
  const key = pending.map((p) => p.toolCallId).join()
  const [dismissed, setDismissed] = useState('')
  const decide = (approved: boolean) => pending.forEach((p) => onApprove({ id: p.approval!.id, approved }))
  return (
    <AlertDialog open={pending.length > 0 && dismissed !== key} onOpenChange={(open) => !open && setDismissed(key)}>
      <AlertDialogContent className="sm:max-w-lg">
        <AlertDialogHeader>
          <AlertDialogTitle>
            Allow Oracle to run {pending.length === 1 ? 'this tool' : `these ${pending.length} tools`}?
          </AlertDialogTitle>
          <AlertDialogDescription>Nothing runs until you decide. You can also answer from the chat.</AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex max-h-[50dvh] flex-col gap-3 overflow-y-auto">
          {pending.map((part) => (
            <div key={part.toolCallId} className="flex flex-col gap-2 rounded-lg border bg-muted/40 p-3">
              <div className="flex items-center gap-2">
                <WrenchIcon className="size-4 text-muted-foreground" />
                <span className="text-sm">{ask(part)}</span>
                <div className="ml-auto flex shrink-0 gap-2">
                  <Button size="sm" variant="outline" onClick={() => onApprove({ id: part.approval!.id, approved: false })}>
                    Deny
                  </Button>
                  <Button size="sm" onClick={() => onApprove({ id: part.approval!.id, approved: true })}>
                    Approve
                  </Button>
                </div>
              </div>
              {part.input != null && Object.keys(part.input).length > 0 ? (
                <pre className="overflow-x-auto font-mono text-xs text-muted-foreground">{JSON.stringify(part.input, null, 2)}</pre>
              ) : null}
            </div>
          ))}
        </div>
        {pending.length > 1 && (
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => decide(false)}>Deny all</AlertDialogCancel>
            <AlertDialogAction onClick={() => decide(true)}>Approve all</AlertDialogAction>
          </AlertDialogFooter>
        )}
      </AlertDialogContent>
    </AlertDialog>
  )
}

const BACKENDS = { docker: 'Docker', prometheus: 'Prometheus', loki: 'Loki' } as const
const TOOLS_KEY = 'oracle.tools'

function initialTools(tools: Array<AgentTool>) {
  try {
    const saved = JSON.parse(localStorage.getItem(TOOLS_KEY) ?? 'null')
    if (Array.isArray(saved)) return new Set(tools.map((t) => t.name).filter((n) => saved.includes(n)))
  } catch {}
  return new Set(tools.map((t) => t.name))
}

function ToolsMenu({ tools, enabled, onChange }: { tools: Array<AgentTool>; enabled: Set<string>; onChange: (next: Set<string>) => void }) {
  const set = (next: Set<string>) => {
    onChange(next)
    try {
      localStorage.setItem(TOOLS_KEY, JSON.stringify([...next]))
    } catch {}
  }
  const toggle = (name: string, on: boolean) => {
    const next = new Set(enabled)
    if (on) next.add(name)
    else next.delete(name)
    set(next)
  }
  const backends = (Object.keys(BACKENDS) as Array<keyof typeof BACKENDS>).filter((b) => tools.some((t) => t.backend === b))
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <PromptInputButton>
          <WrenchIcon />
          <span className="tabular-nums">
            Tools {enabled.size}/{tools.length}
          </span>
        </PromptInputButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80">
        {backends.map((backend, i) => (
          <Fragment key={backend}>
            {i > 0 && <DropdownMenuSeparator />}
            <DropdownMenuGroup>
              <DropdownMenuLabel>{BACKENDS[backend]}</DropdownMenuLabel>
              {tools
                .filter((t) => t.backend === backend)
                .map((t) => (
                  <DropdownMenuCheckboxItem
                    key={t.name}
                    checked={enabled.has(t.name)}
                    onCheckedChange={(on) => toggle(t.name, on === true)}
                    onSelect={(e) => e.preventDefault()}
                  >
                    <span className="flex min-w-0 flex-col">
                      <span className="font-mono text-xs">{t.name}</span>
                      <span className="truncate text-xs text-muted-foreground">{t.description}</span>
                    </span>
                  </DropdownMenuCheckboxItem>
                ))}
            </DropdownMenuGroup>
          </Fragment>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault()
              set(new Set(tools.map((t) => t.name)))
            }}
          >
            Enable all
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault()
              set(new Set())
            }}
          >
            Disable all
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function Chat({
  threadId,
  initialMessages,
  tools,
  ask,
}: {
  threadId: string
  initialMessages: Array<UIMessage>
  tools: Array<AgentTool> | null
  ask?: string
}) {
  const router = useRouter()
  const navigate = useNavigate()
  const [enabled, setEnabled] = useState(() => initialTools(tools ?? []))
  const enabledRef = useRef(enabled)
  enabledRef.current = enabled
  const [transport] = useState(
    () =>
      new DefaultChatTransport({
        api: '/api/chat',
        body: () => ({ tools: [...enabledRef.current] }),
      }),
  )
  const { messages, sendMessage, status, stop, error, regenerate, addToolApprovalResponse } = useChat({
    id: threadId,
    messages: initialMessages,
    transport,
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses,
    // A thread's first answer is what puts it in the sidebar; later turns don't change the list.
    onFinish: ({ messages: all }) => {
      if (all.filter((m) => m.role === 'user').length === 1) {
        router.invalidate({ filter: (match) => match.routeId === rootRouteId })
      }
    },
  })
  const send = (text: string) => sendMessage({ text })
  const asked = useRef(false)
  useEffect(() => {
    if (!ask || asked.current) return
    asked.current = true
    if (tools && initialMessages.length === 0) send(ask)
    navigate({ to: '/c/$threadId', params: { threadId }, search: {}, replace: true })
  }, [ask])
  const shown = messages.filter((m) => m.role === 'user' || hasContent(m))
  const last = messages.at(-1)
  const thinking =
    (status === 'submitted' || status === 'streaming') && !(last?.role === 'assistant' && hasContent(last))
  const pending =
    last?.role === 'assistant'
      ? last.parts.filter((p): p is DynamicToolUIPart => p.type === 'dynamic-tool' && p.state === 'approval-requested')
      : []
  const title = messages
    .filter((m) => m.role === 'user')
    .flatMap((m) => m.parts.flatMap((p) => (p.type === 'text' ? [p.text] : [])))
    .find((text) => !parseCommand(text))

  return (
    <div className="flex h-dvh flex-col">
      <PageHeader crumbs={[{ label: 'Chat', link: { to: '/' } }, { label: title ?? 'New conversation' }]}>
        {messages.length > 0 && (
          <Button asChild variant="ghost" size="sm">
            <Link to="/transcripts/$threadId" params={{ threadId }}>
              <FileTextIcon data-icon="inline-start" />
              Transcript
            </Link>
          </Button>
        )}
      </PageHeader>
      <Conversation>
        <ConversationContent className="mx-auto w-full max-w-3xl">
          {messages.length === 0 ? (
            <Intro onPick={(text) => tools && send(text)} />
          ) : (
            shown.map((message) => (
              <ChatMessage
                key={message.id}
                message={message}
                animating={status === 'streaming' && message === last}
                onApprove={addToolApprovalResponse}
              />
            ))
          )}
          {thinking && (
            <div className="flex items-start gap-3">
              <RoleAvatar role="assistant" />
              <Shimmer className="mt-1.5 text-sm">Investigating…</Shimmer>
            </div>
          )}
          {error && (
            <Alert variant="destructive">
              <AlertTitle>The agent couldn't answer</AlertTitle>
              <AlertDescription>{error.message}</AlertDescription>
              <AlertAction>
                <Button variant="outline" size="sm" onClick={() => regenerate()}>
                  <RotateCwIcon data-icon="inline-start" />
                  Retry
                </Button>
              </AlertAction>
            </Alert>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
      <ApprovalDialog pending={pending} onApprove={addToolApprovalResponse} />
      <div className="mx-auto w-full max-w-3xl px-4 pb-4">
        {!tools && (
          <Alert variant="destructive" className="mb-3">
            <AlertTitle>The agent API can't ask before running tools</AlertTitle>
            <AlertDescription>
              It is older than this web app, so the chat won't send anything. Restart it with{' '}
              <code className="font-mono">uv run python -m agent api --host 127.0.0.1</code>.
            </AlertDescription>
          </Alert>
        )}
        <PromptInputProvider>
          <CommandHints />
          <PromptInput
            onSubmit={({ text }) => {
              if (text.trim()) send(text.trim())
            }}
          >
            <PromptInputBody>
              <PromptInputTextarea
                placeholder={pending.length ? 'Approve or deny the pending tool calls first' : 'Ask about a container, or type / for commands'}
                maxLength={2000}
              />
            </PromptInputBody>
            <PromptInputFooter>
              <PromptInputTools>
                {tools && tools.length > 0 && <ToolsMenu tools={tools} enabled={enabled} onChange={setEnabled} />}
                <span className="px-2 text-xs text-muted-foreground">Every tool call asks first</span>
              </PromptInputTools>
              <PromptInputSubmit status={status} onStop={stop} disabled={!tools || pending.length > 0} />
            </PromptInputFooter>
          </PromptInput>
        </PromptInputProvider>
      </div>
    </div>
  )
}
