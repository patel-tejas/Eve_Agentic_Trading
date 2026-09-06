"use client";

/**
 * Chat over the deterministic quant engine.
 *
 * Tool calls are rendered rather than hidden: the whole premise is that every
 * number traces to a `quant/` computation, so the user can see which tool
 * produced it and expand the raw JSON to check.
 */

import { useChat } from "@ai-sdk/react";
import {
  getToolName,
  isToolUIPart,
  type DynamicToolUIPart,
  type ToolUIPart,
  type UIMessage,
} from "ai";
import { useEffect, useRef, useState } from "react";

// `isToolUIPart` narrows to this union: a tool defined from the bridge
// manifest can arrive as either a static or a dynamic tool part.
type AnyToolPart = ToolUIPart | DynamicToolUIPart;

type GroundingReport = {
  grounded: boolean;
  total_claims: number;
  grounded_claims: number;
  ungrounded_claims: number;
  summary: string;
  ungrounded: { text: string; line: number; context: string }[];
};

type Status = {
  bridge: { url: string; ok: boolean; tools?: number; error?: string };
  model: {
    id: string;
    provider: string;
    ok: boolean;
    keyPresent: boolean;
    detail: string;
  };
  months: Record<string, Record<string, number>>;
};

const EXAMPLES = [
  "What research months are available?",
  "Backtest EMA 9/15 on July 2026, 15m",
  "Compare 1m, 5m and 15m for July 2026",
  "Run a parameter search on 15m July and show the top 5",
];

export default function Home() {
  const [status, setStatus] = useState<Status | null>(null);
  const [input, setInput] = useState("");
  const { messages, sendMessage, status: chatStatus, error, stop } = useChat();
  const [grounding, setGrounding] = useState<Record<string, GroundingReport>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  const busy = chatStatus === "submitted" || chatStatus === "streaming";

  useEffect(() => {
    fetch("/api/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

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
    sendMessage({ text: trimmed });
    setInput("");
  }

  return (
    <div className="flex h-dvh flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <header className="flex shrink-0 items-center justify-between border-b border-zinc-200 px-5 py-3 dark:border-zinc-800">
        <div className="flex items-baseline gap-2">
          <h1 className="text-sm font-semibold tracking-tight">
            NIFTY Quant Research
          </h1>
          <span className="text-xs text-zinc-500">Eve</span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <StatusDot
            ok={status?.bridge.ok ?? false}
            label={
              status?.bridge.ok
                ? `engine · ${status.bridge.tools} tools`
                : "engine offline"
            }
            title={status?.bridge.error ?? status?.bridge.url}
          />
          <StatusDot
            ok={status?.model.ok ?? false}
            label={`${status?.model.provider ?? "groq"} · ${
              status?.model.id ?? "…"
            }`}
            title={status?.model.detail ?? "checking…"}
          />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-56 shrink-0 overflow-y-auto border-r border-zinc-200 p-4 text-xs md:block dark:border-zinc-800">
          <h2 className="mb-2 font-semibold text-zinc-500 uppercase tracking-wide">
            Processed months
          </h2>
          {status && Object.keys(status.months).length > 0 ? (
            <ul className="space-y-2">
              {Object.entries(status.months).map(([month, timeframes]) => (
                <li key={month}>
                  <div className="font-mono font-medium">{month}</div>
                  <div className="text-zinc-500">
                    {Object.entries(timeframes)
                      .map(([tf, bars]) => `${tf}: ${bars?.toLocaleString()}`)
                      .join(" · ")}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-zinc-500">
              {status?.bridge.ok
                ? "No processed months found."
                : "Start the quant bridge to list months."}
            </p>
          )}

          <h2 className="mt-6 mb-2 font-semibold text-zinc-500 uppercase tracking-wide">
            Defaults
          </h2>
          <dl className="space-y-1 font-mono text-zinc-500">
            <div>fast_ema 9</div>
            <div>slow_ema 15</div>
            <div>angle 30.0°</div>
            <div>lookback 1</div>
          </dl>
        </aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6">
            <div className="mx-auto flex max-w-3xl flex-col gap-5">
              {messages.length === 0 && (
                <EmptyState
                  onPick={submit}
                  bridgeOk={status?.bridge.ok ?? false}
                  modelOk={status?.model.ok ?? false}
                  modelDetail={status?.model.detail}
                />
              )}
              {messages.map((message) => (
                <Message
                  key={message.id}
                  message={message}
                  grounding={grounding[message.id]}
                />
              ))}
              {chatStatus === "submitted" && (
                <div className="text-xs text-zinc-500">Thinking…</div>
              )}
              {error && (
                <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                  {error.message}
                </div>
              )}
            </div>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(input);
            }}
            className="shrink-0 border-t border-zinc-200 px-4 py-3 dark:border-zinc-800"
          >
            <div className="mx-auto flex max-w-3xl gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about a month, a backtest, a parameter sweep…"
                className="flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
              />
              {busy ? (
                <button
                  type="button"
                  onClick={stop}
                  className="rounded-md border border-zinc-300 px-4 py-2 text-sm dark:border-zinc-700"
                >
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim()}
                  className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
                >
                  Send
                </button>
              )}
            </div>
            <p className="mx-auto mt-2 max-w-3xl text-[11px] text-zinc-500">
              Every figure comes from the Python engine. Research only — not
              investment advice.
            </p>
          </form>
        </main>
      </div>
    </div>
  );
}

function StatusDot({
  ok,
  label,
  title,
}: {
  ok: boolean;
  label: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className="flex items-center gap-1.5 text-zinc-600 dark:text-zinc-400"
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
      />
      {label}
    </span>
  );
}

function EmptyState({
  onPick,
  bridgeOk,
  modelOk,
  modelDetail,
}: {
  onPick: (text: string) => void;
  bridgeOk: boolean;
  modelOk: boolean;
  modelDetail?: string;
}) {
  return (
    <div className="flex flex-col gap-4 py-8">
      <div>
        <h2 className="text-base font-semibold">Ask the quant engine.</h2>
        <p className="mt-1 text-sm text-zinc-500">
          The model calls the deterministic Python tools and reports what they
          return. It never calculates a number itself.
        </p>
      </div>

      {(!bridgeOk || !modelOk) && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <p className="font-medium">Setup needed</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {!bridgeOk && (
              <li>
                Start the engine:{" "}
                <code className="font-mono">
                  uv run python -m mcp.quant_server.http_bridge
                </code>
              </li>
            )}
            {!modelOk && (
              <li>
                {modelDetail ?? "Model not configured."} Edit{" "}
                <code className="font-mono">apps/web/.env.local</code> and
                restart the dev server. Keys:{" "}
                <a
                  className="underline"
                  href="https://console.groq.com/keys"
                  target="_blank"
                  rel="noreferrer"
                >
                  console.groq.com/keys
                </a>
              </li>
            )}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            onClick={() => onPick(example)}
            className="rounded-full border border-zinc-300 px-3 py-1.5 text-xs text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}

function Message({
  message,
  grounding,
}: {
  message: UIMessage;
  grounding?: GroundingReport;
}) {
  const isUser = message.role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div className={isUser ? "max-w-[80%]" : "w-full"}>
        {!isUser && (
          <div className="mb-1 text-[11px] font-medium text-zinc-500">Eve</div>
        )}
        <div
          className={
            isUser
              ? "rounded-2xl bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900"
              : "space-y-2 text-sm leading-relaxed"
          }
        >
          {message.parts.map((part, i) => {
            if (part.type === "text") {
              return (
                <p key={i} className="whitespace-pre-wrap">
                  {part.text}
                </p>
              );
            }
            if (isToolUIPart(part)) {
              return <ToolCall key={i} part={part} />;
            }
            return null;
          })}
          {!isUser && grounding && <GroundingBadge report={grounding} />}
        </div>
      </div>
    </div>
  );
}

/**
 * Whether the numbers in this answer trace to the tool results above it.
 *
 * Advisory: it reports, it does not block. The system prompt tells the model
 * never to compute a figure itself; this is what checks that it didn't.
 */
function GroundingBadge({ report }: { report: GroundingReport }) {
  if (report.total_claims === 0) return null;

  if (report.grounded) {
    return (
      <div
        title={report.summary}
        className="flex items-center gap-1.5 text-[11px] text-emerald-700 dark:text-emerald-400"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        {report.total_claims} figures traced to tool results
      </div>
    );
  }

  return (
    <details className="rounded-md border border-amber-300 bg-amber-50 text-[11px] text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
      <summary className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1.5">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
        {report.ungrounded_claims} of {report.total_claims} figures do not trace
        to a tool result
      </summary>
      <ul className="space-y-1 border-t border-amber-300 px-2.5 py-1.5 dark:border-amber-900">
        {report.ungrounded.map((claim, i) => (
          <li key={i}>
            <span className="font-mono font-medium">{claim.text}</span>
            <span className="opacity-70"> — line {claim.line}: {claim.context}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function ToolCall({ part }: { part: AnyToolPart }) {
  const name = getToolName(part);
  const done = part.state === "output-available";
  const failed =
    part.state === "output-error" ||
    (done &&
      typeof part.output === "object" &&
      part.output !== null &&
      "error" in part.output);

  return (
    <details className="rounded-md border border-zinc-200 bg-white text-xs dark:border-zinc-800 dark:bg-zinc-900">
      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            failed ? "bg-red-500" : done ? "bg-emerald-500" : "bg-amber-500"
          }`}
        />
        <span className="font-mono font-medium">{name}</span>
        <span className="text-zinc-500">
          {failed ? "failed" : done ? "ok" : "running…"}
        </span>
      </summary>
      <div className="space-y-2 border-t border-zinc-200 px-3 py-2 dark:border-zinc-800">
        <Block label="input" value={part.input} />
        {part.state === "output-available" && (
          <Block label="output" value={part.output} />
        )}
        {part.state === "output-error" && (
          <Block label="error" value={part.errorText} />
        )}
      </div>
    </details>
  );
}

function Block({ label, value }: { label: string; value: unknown }) {
  if (value === undefined) return null;
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div>
      <div className="mb-1 text-[10px] uppercase tracking-wide text-zinc-500">
        {label}
      </div>
      <pre className="max-h-64 overflow-auto rounded bg-zinc-50 p-2 font-mono text-[11px] dark:bg-zinc-950">
        {text}
      </pre>
    </div>
  );
}
