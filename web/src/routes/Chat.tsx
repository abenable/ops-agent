import { useEffect, useLayoutEffect, useRef, useState, type ComponentProps } from "react";
import { BotIcon, EraserIcon, SendIcon, SquareIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { streamAgent, type AgentEvent } from "../api";
import { Bubble, BubbleContent, BubbleGroup } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from "@/components/ui/input-group";
import { Markdown } from "@/components/markdown";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Message, MessageAvatar, MessageContent, MessageFooter } from "@/components/ui/message";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Spinner } from "@/components/ui/spinner";

type ToolStep = { step: number; name: string; args: unknown; result?: string };

type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
  tools?: ToolStep[];
  incidentId?: string;
  error?: boolean;
};

type HistoryTurn = { role: "user" | "assistant"; content: string };

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const historyRef = useRef<HistoryTurn[]>([]);
  const idRef = useRef(1);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const baseHeightRef = useRef(0);
  const [multiLine, setMultiLine] = useState(false);

  useEffect(() => {
    if (taRef.current) baseHeightRef.current = taRef.current.offsetHeight;
  }, []);

  const send = async () => {
    const q = input.trim();
    if (!q || running) return;

    const uid = idRef.current++;
    const aid = idRef.current++;
    const history = historyRef.current.slice();
    let finalContent = "";

    setMessages((m) => [
      ...m,
      { id: uid, role: "user", content: q },
      { id: aid, role: "assistant", content: "", tools: [] },
    ]);
    setInput("");
    setRunning(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const applyToTurn = (fn: (msg: Message) => Message) =>
      setMessages((m) => m.map((msg) => (msg.id === aid ? fn(msg) : msg)));

    try {
      await streamAgent(
        "/ask/stream",
        { question: q, history },
        (e: AgentEvent) => {
          switch (e.type) {
            case "tool_call":
              applyToTurn((msg) => ({
                ...msg,
                tools: [...(msg.tools ?? []), { step: e.step, name: e.name, args: e.args }],
              }));
              break;
            case "tool_result": {
              applyToTurn((msg) => {
                const tools = [...(msg.tools ?? [])];
                const t = [...tools].reverse().find((s) => s.step === e.step && s.name === e.name);
                if (t) t.result = e.result;
                return { ...msg, tools };
              });
              break;
            }
            case "done": {
              if ("incident_id" in e) {
                finalContent = e.summary;
                applyToTurn((msg) => ({ ...msg, content: e.summary, incidentId: e.incident_id }));
              } else {
                finalContent = e.content;
                applyToTurn((msg) => ({ ...msg, content: e.content }));
              }
              break;
            }
            case "error":
              applyToTurn((msg) => ({ ...msg, content: e.message, error: true }));
              break;
          }
        },
        ctrl.signal,
      );
    } catch (err) {
      if (!ctrl.signal.aborted) {
        applyToTurn((msg) => ({ ...msg, content: String(err), error: true }));
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
      if (finalContent) {
        historyRef.current = [...historyRef.current, { role: "user", content: q }, { role: "assistant", content: finalContent }];
      }
    }
  };

  const stop = () => abortRef.current?.abort();

  const clear = () => {
    abortRef.current?.abort();
    historyRef.current = [];
    setMessages([]);
    setRunning(false);
  };

  return (
    <div className="mx-auto flex h-[calc(100svh-6.5rem)] min-h-[28rem] w-full max-w-3xl flex-col">
      <div className="flex items-center justify-between gap-4 pb-3">
        <div className="flex flex-col gap-1">
          <h1 className="font-heading text-xl font-semibold tracking-tight">Chat with the agent</h1>
          <p className="text-sm text-muted-foreground">
            Ask about the stack — the agent investigates with live tool calls and remembers the conversation.
          </p>
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={clear} disabled={running}>
            <EraserIcon />
            New chat
          </Button>
        )}
      </div>

      <MessageScrollerProvider autoScroll scrollPreviousItemPeek={64}>
        <div className="flex min-h-0 flex-1 flex-col">
          {messages.length === 0 ? (
            <Empty className="h-full min-h-64">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <SendIcon />
                </EmptyMedia>
                <EmptyTitle>Ask anything</EmptyTitle>
                <EmptyDescription>
                  Example: "Why is the agent_api service slow?" or "Investigate the n8n endpoint."
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <MessageScroller className="flex-1">
              <MessageScrollerViewport className="no-scrollbar">
                <MessageScrollerContent aria-busy={running} className="gap-5">
                  {messages.map((msg) => (
                    <MessageScrollerItem
                      key={msg.id}
                      messageId={String(msg.id)}
                      scrollAnchor={msg.role === "user"}
                    >
                      <MessageView msg={msg} />
                    </MessageScrollerItem>
                  ))}
                </MessageScrollerContent>
              </MessageScrollerViewport>
              <MessageScrollerButton />
            </MessageScroller>
          )}

          <div className="flex flex-col gap-2 py-2">
            <InputGroup
              className={cn(
                "bg-card px-2 transition-[border-radius] duration-150",
                multiLine ? "rounded-2xl" : "rounded-full",
              )}
            >
              <InputGroupTextarea
                ref={taRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  if (baseHeightRef.current === 0) {
                    baseHeightRef.current = e.target.offsetHeight;
                  }
                  setMultiLine(e.target.offsetHeight > baseHeightRef.current + 2);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                rows={1}
                disabled={running}
                placeholder="Ask about the stack… (Enter to send, Shift+Enter for a newline)"
                className="max-h-40 min-h-9 px-3 font-mono"
              />
              <InputGroupAddon align="inline-end" className="self-end py-0">
                {running ? (
                  <InputGroupButton
                    variant="outline"
                    size="icon-sm"
                    aria-label="Stop"
                    onClick={stop}
                    className="rounded-full"
                  >
                    <SquareIcon />
                  </InputGroupButton>
                ) : (
                  <InputGroupButton
                    variant="default"
                    size="icon-sm"
                    aria-label="Send"
                    disabled={!input.trim()}
                    onClick={send}
                    className="rounded-full"
                  >
                    <SendIcon />
                  </InputGroupButton>
                )}
              </InputGroupAddon>
            </InputGroup>
            <div className="flex items-center gap-2 px-1">
              <span className="text-xs text-muted-foreground">
                {historyRef.current.length > 0
                  ? `${historyRef.current.length / 2} turns of context`
                  : "agent has no memory yet"}
              </span>
            </div>
          </div>
        </div>
      </MessageScrollerProvider>
    </div>
  );
}

function AdaptiveBubble({
  variant,
  align,
  content,
  markdown,
}: {
  variant: ComponentProps<typeof Bubble>["variant"];
  align?: ComponentProps<typeof Bubble>["align"];
  content: string;
  markdown?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [multiLine, setMultiLine] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const style = getComputedStyle(el);
    const lineH = parseFloat(style.lineHeight) || 20;
    const oneLine = lineH + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    setMultiLine(el.offsetHeight > oneLine + 2);
  }, [content]);

  return (
    <Bubble variant={variant} align={align}>
      <BubbleContent
        ref={ref}
        className={cn(
          "px-4 py-1.5 leading-snug transition-[border-radius] duration-150",
          !markdown && "whitespace-pre-wrap",
          multiLine ? "rounded-2xl" : "rounded-full",
        )}
      >
        {markdown ? <Markdown>{content}</Markdown> : content}
      </BubbleContent>
    </Bubble>
  );
}

function MessageView({ msg }: { msg: Message }) {
  if (msg.role === "user") {
    return (
      <Message align="end">
        <MessageContent className="gap-2">
          <AdaptiveBubble variant="default" align="end" content={msg.content} />
        </MessageContent>
      </Message>
    );
  }

  const thinking = !msg.content && !msg.error;

  return (
    <Message>
      <MessageAvatar className="size-10">
        <BotIcon className="size-5" />
      </MessageAvatar>
      <MessageContent className="gap-2">
        {msg.error ? (
          <AdaptiveBubble variant="destructive" content={msg.content} markdown />
        ) : (
          <BubbleGroup>
            {thinking && (
              <Marker role="status">
                <MarkerIcon>
                  <Spinner />
                </MarkerIcon>
                <MarkerContent className="shimmer">Investigating the stack…</MarkerContent>
              </Marker>
            )}
            {msg.content && <AdaptiveBubble variant="secondary" content={msg.content} markdown />}
            {msg.incidentId && (
              <MessageFooter>Persisted as incident {msg.incidentId}</MessageFooter>
            )}
            {msg.tools && msg.tools.length > 0 && (
              <Bubble variant="muted">
                <BubbleContent className="px-0 py-0">
                  <details className="group px-3 py-1.5">
                    <summary className="flex cursor-pointer list-none items-center gap-2 text-xs text-muted-foreground">
                      {msg.tools.length} tool call{msg.tools.length === 1 ? "" : "s"}
                    </summary>
                    <div className="flex flex-col gap-1.5 pt-1.5">
                      {msg.tools.map((t, i) => (
                        <ToolStepView key={i} t={t} />
                      ))}
                    </div>
                  </details>
                </BubbleContent>
              </Bubble>
            )}
          </BubbleGroup>
        )}
      </MessageContent>
    </Message>
  );
}

function ToolStepView({ t }: { t: ToolStep }) {
  return (
    <details>
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs">
        <span className="font-mono text-muted-foreground">step {t.step}</span>
        <code className="font-mono font-medium">{t.name}()</code>
      </summary>
      <div className="mt-1.5 flex flex-col gap-1.5">
        <pre className="overflow-x-auto rounded-md bg-background p-2 font-mono text-[11px] text-muted-foreground">
          {JSON.stringify(t.args, null, 2)}
        </pre>
        {t.result && (
          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md bg-background p-2 font-mono text-[11px] text-muted-foreground">
            {t.result}
          </pre>
        )}
      </div>
    </details>
  );
}
