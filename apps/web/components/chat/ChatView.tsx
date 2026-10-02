"use client";

/**
 * Chat over the deterministic quant engine.
 *
 * Mounted once per conversation (keyed by chat id), seeded with the saved
 * messages, and reports every change upward so the shell can persist it.
 */

import { useChat } from "@ai-sdk/react";
import { getToolName, isToolUIPart, type UIMessage } from "ai";
import { useEffect, useRef, useState } from "react";

import { AssistantMessage, humanizeTool, UserMessage } from "@/components/chat/Message";
import PromptBar, { type PromptCommand } from "@/components/chat/PromptBar";
import LoadingState from "@/components/ui/LoadingState";
import { EveMark } from "@/components/ui/icons";
import type { GroundingReport, Status } from "@/lib/types";

function latestMonth(status: Status | null) {
  const months = Object.keys(status?.months ?? {}).sort();
  return months[months.length - 1] ?? "July 2026";
}

function commandsFor(status: Status | null): PromptCommand[] {
  const m = latestMonth(status);
  return [
    { key: "months", name: "/months", desc: "List processed research months", prompt: "What research months are available?" },
    { key: "backtest", name: "/backtest", desc: "EMA 9/15 on one month", prompt: `Backtest EMA 9/15 on ${m}, 15m` },
    { key: "compare", name: "/compare", desc: "1m vs 5m vs 15m", prompt: `Compare 1m, 5m and 15m for ${m}` },
    { key: "search", name: "/search", desc: "Parameter grid, top 5", prompt: `Run a parameter search on 15m ${m} and show the top 5` },
    {
      key: "validate",
      name: "/validate",
      desc: "Search with deflated Sharpe + PBO",
      prompt: `Validate a parameter search on 15m ${m}. Is the winner credible?`,
    },
    { key: "walkforward", name: "/walkforward", desc: "Out-of-sample check", prompt: `Run a walk-forward test on 15m ${m}` },
  ];
}

const STARTERS = [
  { title: "What data is ready?", prompt: "What research months are available?" },
  { title: "Backtest the defaults", prompt: "Backtest EMA 9/15 on July 2026, 15m" },
  { title: "Compare timeframes", prompt: "Compare 1m, 5m and 15m for July 2026" },
  { title: "Search parameters", prompt: "Run a parameter search on 15m July and show the top 5" },
];

export default function ChatView({
  chatId,
  initialMessages,
  status,
  onMessagesChange,
  onOpenAgent,
}: {
  chatId: string;
  initialMessages: UIMessage[];
  status: Status | null;
  onMessagesChange: (messages: UIMessage[]) => void;
  onOpenAgent: () => void;
}) {
  const { messages, sendMessage, regenerate, status: chatStatus, error, stop } = useChat({
    id: chatId,
    messages: initialMessages,
  });
  const [grounding, setGrounding] = useState<Record<string, GroundingReport>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const busy = chatStatus === "submitted" || chatStatus === "streaming";

  useEffect(() => {
    onMessagesChange(messages);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  // Follow the stream unless the reader has scrolled up to look at something.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, chatStatus]);

  // Check the finished answer's numbers against the tool results it was built
  // from. Runs once per assistant message, only after streaming settles, so a
  // half-written number is never judged.
  useEffect(() => {
    if (chatStatus !== "ready") return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant" || grounding[last.id]) return;

    const answer = last.parts
      .filter((p) => p.type === "text")
      .map((p) => (p as { text: string }).text)
      .join("\n");
    if (!answer.trim()) return;

    const toolResults = last.parts
      .filter((p) => isToolUIPart(p) && p.state === "output-available")
      .map((p) => (p as { output: unknown }).output);

    let cancelled = false;
    fetch("/api/grounding", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ answer, toolResults }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((report: GroundingReport | null) => {
        if (!cancelled && report && "grounded" in report) {
          setGrounding((prev) => ({ ...prev, [last.id]: report }));
        }
      })
      .catch(() => {
        // Advisory only: a failed check must never break the conversation.
      });
    return () => {
      cancelled = true;
    };
  }, [messages, chatStatus, grounding]);

  function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    stickToBottom.current = true;
    sendMessage({ text: trimmed });
  }

  const bridgeOk = status?.bridge.ok ?? false;
  const modelOk = status?.model.ok ?? false;
  const commands = commandsFor(status);
  const empty = messages.length === 0;

  // What the loader says: the tool currently running, else "Thinking".
  const last = messages[messages.length - 1];
  const running =
    last?.role === "assistant"
      ? last.parts.filter(isToolUIPart).find((p) => p.state === "input-streaming" || p.state === "input-available")
      : undefined;
  const lastHasText = last?.role === "assistant" && last.parts.some((p) => p.type === "text" && p.text.trim());
  const loaderLabel = running ? `Running ${humanizeTool(getToolName(running))}` : "Thinking";
  const showLoader = chatStatus === "submitted" || (chatStatus === "streaming" && (!!running || !lastHasText));

  const prompt = (
    <PromptBar
      months={status?.months ?? {}}
      commands={commands}
      modelLabel={status?.model.id ?? "checking…"}
      modelOk={modelOk}
      busy={busy}
      tall={empty}
      onSend={submit}
      onStop={stop}
    />
  );

  if (empty) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="mx-auto flex w-full max-w-measure flex-1 flex-col justify-center gap-section px-page py-section">
          <div className="flex flex-col items-start gap-stack" style={{ animation: "fade-up 400ms cubic-bezier(0.23,1,0.32,1) both" }}>
            <EveMark size={36} />
            <div>
              <h1 className="text-[22px] font-semibold tracking-tight text-ink">Ask the quant engine.</h1>
              <p className="mt-1 max-w-lg text-[14px] leading-6 text-ink-2">
                Eve calls the deterministic Python tools and reports what they return. It never calculates a number itself.
              </p>
            </div>
          </div>

          {(!bridgeOk || !modelOk) && status && (
            <button
              type="button"
              onClick={onOpenAgent}
              className="flex items-center gap-2.5 rounded-card bg-amber-tint px-card py-stack text-left text-[13px] text-amber transition-opacity hover:opacity-85"
            >
              <span className="size-1.5 shrink-0 rounded-full bg-amber" />
              <span className="flex-1">
                <span className="font-medium">Setup needed.</span>{" "}
                {!bridgeOk ? "The quant engine is offline." : "The model isn't ready."} Open the Agent tab for the fix.
              </span>
            </button>
          )}

          {prompt}

          <div className="grid grid-cols-1 gap-tight sm:grid-cols-2">
            {STARTERS.map((s, i) => (
              <button
                key={s.title}
                type="button"
                onClick={() => submit(s.prompt)}
                className="flex flex-col gap-0.5 rounded-card bg-surface px-card py-stack text-left shadow-card transition-[box-shadow,transform] duration-150 hover:shadow-raised active:scale-[0.99]"
                style={{ animation: `fade-up 400ms cubic-bezier(0.23,1,0.32,1) ${120 + i * 60}ms both` }}
              >
                <span className="text-[13px] font-medium text-ink">{s.title}</span>
                <span className="truncate text-[12.5px] text-ink-3">{s.prompt}</span>
              </button>
            ))}
          </div>

          <p className="text-center text-[11.5px] text-ink-3">Every figure comes from the Python engine. Research only, not investment advice.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto flex w-full max-w-measure flex-col gap-section px-page py-section">
          {messages.map((message, i) =>
            message.role === "user" ? (
              <UserMessage key={message.id} message={message} />
            ) : (
              <AssistantMessage
                key={message.id}
                message={message}
                grounding={grounding[message.id]}
                streaming={busy && i === messages.length - 1}
                isLast={i === messages.length - 1}
                onRetry={() => regenerate()}
                onFollowUp={submit}
              />
            ),
          )}
          {showLoader && (
            <div className="pl-9">
              <LoadingState label={loaderLabel} variant={running ? "Drive" : "Dots"} />
            </div>
          )}
          {error && (
            <div className="rounded-card bg-red-tint px-card py-stack text-[13px] text-red">
              <span className="font-medium">Something went wrong.</span> {error.message}
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 bg-gradient-to-t from-canvas via-canvas to-transparent pt-2">
        <div className="mx-auto w-full max-w-measure px-page pb-stack">
          {prompt}
          <p className="mt-tight text-center text-[11.5px] text-ink-3">
            Every figure comes from the Python engine. Research only, not investment advice.
          </p>
        </div>
      </div>
    </div>
  );
}
