"use client";

/**
 * One turn in the conversation.
 *
 * Tool calls are rendered rather than hidden: the whole premise is that every
 * number traces to a `quant/` computation, so the user can see which tool
 * produced it and expand the raw JSON to check.
 */

import { getToolName, isToolUIPart, type DynamicToolUIPart, type ToolUIPart, type UIMessage } from "ai";
import { useEffect, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { LoaderGrid } from "@/components/ui/LoadingState";
import { EveMark, IconCheck, IconChevronRight, IconCopy, IconReply, IconRetry } from "@/components/ui/icons";
import type { GroundingReport } from "@/lib/types";

// `isToolUIPart` narrows to this union: a tool defined from the bridge
// manifest can arrive as either a static or a dynamic tool part.
type AnyToolPart = ToolUIPart | DynamicToolUIPart;

const ACRONYMS = new Set(["ema", "atr", "pbo", "pnl", "oos", "id", "csv"]);

/** "backtest_ema_crossover" → "Backtest EMA crossover" */
export function humanizeTool(name: string) {
  const words = name
    .split("_")
    .map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w))
    .join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function UserMessage({ message }: { message: UIMessage }) {
  const text = message.parts
    .filter((p) => p.type === "text")
    .map((p) => (p as { text: string }).text)
    .join("\n");
  return (
    <div className="flex justify-end pl-12" style={{ animation: "fade-up 300ms cubic-bezier(0.23,1,0.32,1) both" }}>
      <div className="max-w-full rounded-card bg-field px-3.5 py-2 text-[14px] leading-6 whitespace-pre-wrap text-ink">
        {text}
      </div>
    </div>
  );
}

export function AssistantMessage({
  message,
  grounding,
  streaming,
  isLast,
  onRetry,
  onFollowUp,
}: {
  message: UIMessage;
  grounding?: GroundingReport;
  /** this message is still being written */
  streaming: boolean;
  isLast: boolean;
  onRetry: () => void;
  onFollowUp: (text: string) => void;
}) {
  // Consecutive tool parts render as one group of steps; text renders as prose.
  const blocks: ({ kind: "text"; text: string } | { kind: "tools"; parts: AnyToolPart[] })[] = [];
  for (const part of message.parts) {
    if (part.type === "text") {
      if (part.text.trim()) blocks.push({ kind: "text", text: part.text });
    } else if (isToolUIPart(part)) {
      const prev = blocks[blocks.length - 1];
      if (prev?.kind === "tools") prev.parts.push(part);
      else blocks.push({ kind: "tools", parts: [part] });
    }
  }

  const text = blocks
    .filter((b) => b.kind === "text")
    .map((b) => (b as { text: string }).text)
    .join("\n\n");
  const toolNames = message.parts.filter(isToolUIPart).map((p) => getToolName(p));
  const done = !streaming;

  return (
    <div className="flex gap-stack" style={{ animation: "fade-up 300ms cubic-bezier(0.23,1,0.32,1) both" }}>
      <div className="pt-0.5">
        <EveMark size={24} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-stack">
        {blocks.map((block, i) =>
          block.kind === "tools" ? (
            <ToolSteps key={i} parts={block.parts} />
          ) : (
            <Prose key={i} text={block.text} />
          ),
        )}

        {done && text && (
          <div className="-ml-1 flex flex-wrap items-center gap-1" style={{ animation: "fade-in 300ms ease both" }}>
            <CopyButton text={text} />
            {isLast && (
              <ActionButton label="Retry" onClick={onRetry}>
                <IconRetry size={15} />
              </ActionButton>
            )}
            {grounding && <GroundingBadge report={grounding} />}
          </div>
        )}

        {done && isLast && text && <FollowUps toolNames={toolNames} onPick={onFollowUp} />}
      </div>
    </div>
  );
}

function Prose({ text }: { text: string }) {
  return (
    <div className="prose-eve min-w-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="table-wrap">
              <table>{children}</table>
            </div>
          ),
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function ActionButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded-chip text-ink-3 transition-colors duration-100 hover:bg-hover-2 hover:text-ink-2"
    >
      {children}
    </button>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <ActionButton
      label={copied ? "Copied" : "Copy"}
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => setCopied(true), () => {});
      }}
    >
      {copied ? <IconCheck size={15} /> : <IconCopy size={15} />}
    </ActionButton>
  );
}

/* ── tool steps ───────────────────────────────────────── */

function toolState(part: AnyToolPart): "running" | "done" | "failed" {
  if (part.state === "output-error") return "failed";
  if (part.state === "output-available") {
    const out = part.output;
    return typeof out === "object" && out !== null && "error" in out ? "failed" : "done";
  }
  return "running";
}

/** "month 2026-07 · timeframe 15m" — the arguments a reader scans for. */
function summarizeInput(input: unknown) {
  if (!input || typeof input !== "object") return "";
  return Object.entries(input as Record<string, unknown>)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .slice(0, 4)
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${String(v)}`)
    .join(" · ");
}

// Wall-clock timings live outside React state so a re-render (or a message
// re-mounting while it streams) does not restart the clock.
const timings = new Map<string, { start: number; end?: number }>();

function useToolTiming(id: string, running: boolean) {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (running) {
      if (!timings.has(id)) timings.set(id, { start: Date.now() });
      const iv = setInterval(() => setNow(Date.now()), 100);
      return () => clearInterval(iv);
    }
    const t = timings.get(id);
    if (t && !t.end) t.end = Date.now();
  }, [id, running]);

  const t = timings.get(id);
  const end = t?.end ?? now;
  if (!t || end === null) return null;
  const secs = Math.max(0, end - t.start) / 1000;
  return secs < 60 ? `${secs.toFixed(1)}s` : `${Math.floor(secs / 60)}m ${(secs % 60).toFixed(0)}s`;
}

function ToolSteps({ parts }: { parts: AnyToolPart[] }) {
  return (
    <div className="flex flex-col rounded-card bg-inset p-1 shadow-hairline">
      {parts.map((part) => (
        <ToolStep key={part.toolCallId} part={part} />
      ))}
    </div>
  );
}

function ToolStep({ part }: { part: AnyToolPart }) {
  const [open, setOpen] = useState(false);
  const name = getToolName(part);
  const state = toolState(part);
  const elapsed = useToolTiming(part.toolCallId, state === "running");
  const args = summarizeInput(part.input);

  return (
    <div className="flex flex-col">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-9 w-full items-center gap-2.5 rounded-control px-2.5 py-1.5 text-left transition-colors duration-100 hover:bg-hover"
      >
        <span className="flex size-4 shrink-0 items-center justify-center">
          {state === "running" ? (
            <LoaderGrid variant="Orbit" />
          ) : (
            <span className={`size-1.5 rounded-full ${state === "failed" ? "bg-red" : "bg-green"}`} />
          )}
        </span>
        <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-[13px] font-medium text-ink">{humanizeTool(name)}</span>
          {args && <span className="min-w-0 truncate font-mono text-[11.5px] text-ink-3">{args}</span>}
        </span>
        <span
          className={`shrink-0 text-[12px] tabular-nums ${
            state === "failed" ? "text-red" : state === "running" ? "text-ink-2" : "text-ink-3"
          }`}
        >
          {state === "failed" ? "Failed" : state === "running" ? (elapsed ?? "Running") : (elapsed ?? "Done")}
        </span>
        <span className={`shrink-0 text-ink-3 transition-transform duration-200 ${open ? "rotate-90" : ""}`}>
          <IconChevronRight size={14} />
        </span>
      </button>

      <div
        className="grid transition-[grid-template-rows,opacity] duration-300"
        style={{
          gridTemplateRows: open ? "1fr" : "0fr",
          opacity: open ? 1 : 0,
          transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
        }}
      >
        <div className="overflow-hidden">
          <div className="flex flex-col gap-tight px-2.5 pt-1 pb-2.5">
            <JsonBlock label="Input" value={part.input} />
            {part.state === "output-available" && <JsonBlock label="Output" value={part.output} />}
            {part.state === "output-error" && <JsonBlock label="Error" value={part.errorText} />}
          </div>
        </div>
      </div>
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  if (value === undefined) return null;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium text-ink-3">{label}</div>
      <pre className="max-h-64 overflow-auto rounded-control bg-surface p-2.5 font-mono text-[11.5px] leading-relaxed text-ink-2 shadow-hairline">
        {text}
      </pre>
    </div>
  );
}

/* ── grounding ────────────────────────────────────────── */

/**
 * Whether the numbers in this answer trace to the tool results above it.
 *
 * Advisory: it reports, it does not block. The system prompt tells the model
 * never to compute a figure itself; this is what checks that it didn't.
 */
function GroundingBadge({ report }: { report: GroundingReport }) {
  const [open, setOpen] = useState(false);
  if (report.total_claims === 0) return null;

  if (report.grounded) {
    return (
      <span
        title={report.summary}
        className="ml-1 flex h-6 items-center gap-1.5 rounded-full bg-green-tint px-2.5 text-[12px] font-medium text-green"
      >
        <span className="size-1.5 rounded-full bg-green" />
        {report.total_claims} figures traced to tool results
      </span>
    );
  }

  return (
    <div className="w-full">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="ml-1 flex h-6 items-center gap-1.5 rounded-full bg-amber-tint px-2.5 text-[12px] font-medium text-amber"
      >
        <span className="size-1.5 rounded-full bg-amber" />
        {report.ungrounded_claims} of {report.total_claims} figures do not trace to a tool result
        <span className={`transition-transform duration-200 ${open ? "rotate-90" : ""}`}>
          <IconChevronRight size={12} />
        </span>
      </button>
      {open && (
        <ul
          className="mt-tight flex flex-col gap-1 rounded-control bg-inset p-stack text-[12px] text-ink-2 shadow-hairline"
          style={{ animation: "fade-up 250ms cubic-bezier(0.23,1,0.32,1) both" }}
        >
          {report.ungrounded.map((claim, i) => (
            <li key={i}>
              <span className="font-mono font-medium text-ink">{claim.text}</span>
              <span className="text-ink-3"> · line {claim.line}: </span>
              {claim.context}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── follow-ups ───────────────────────────────────────── */

/** Next steps that fit what Eve just ran; research hygiene first. */
function followUpsFor(toolNames: string[]) {
  const used = new Set(toolNames);
  const out: string[] = [];
  if (used.has("parameter_search") && !used.has("validate_parameter_search"))
    out.push("Validate that search with deflated Sharpe and PBO");
  if ([...used].some((n) => n.startsWith("backtest")) && !used.has("backtest_significance"))
    out.push("Is this backtest result statistically significant?");
  if ([...used].some((n) => n.startsWith("backtest") || n.includes("search")) && !used.has("walk_forward_test"))
    out.push("Run a walk-forward test on the same window");
  if (used.has("list_research_months") || used.size === 0)
    out.push("Backtest EMA 9/15 on the latest month, 15m");
  out.push("Compare 1m, 5m and 15m for the same month");
  return [...new Set(out)].slice(0, 3);
}

function FollowUps({ toolNames, onPick }: { toolNames: string[]; onPick: (text: string) => void }) {
  const items = followUpsFor(toolNames);
  return (
    <div className="mt-1">
      <p className="text-[12px] font-medium text-ink-3">Follow-ups</p>
      <div className="mt-1 flex flex-col">
        {items.map((text, i) => (
          <button
            key={text}
            type="button"
            onClick={() => onPick(text)}
            className="-mx-2 flex items-center gap-2 rounded-control border-b border-line px-2 py-2 text-left text-[13px] text-ink-2 transition-colors duration-100 last:border-b-0 hover:bg-hover-2 hover:text-ink"
            style={{ animation: `fade-up 350ms cubic-bezier(0.23,1,0.32,1) ${i * 90}ms both` }}
          >
            <span className="shrink-0 text-ink-3">
              <IconReply size={12} strokeWidth={2} />
            </span>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}
