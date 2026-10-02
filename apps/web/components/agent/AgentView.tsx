"use client";

/**
 * The Agent tab: what Eve is, whether it can run right now, and what it can
 * reach. Everything here comes from /api/status; nothing is hard-coded except
 * the strategy defaults and guardrails, which mirror the chat route's system
 * prompt.
 */

import { useState, type ReactNode } from "react";

import { humanizeTool } from "@/components/chat/Message";
import { EveMark, IconCalendar, IconChart, IconRetry, IconSearch, IconShield, IconTool } from "@/components/ui/icons";
import { STRATEGY_DEFAULTS, type Status } from "@/lib/types";

const GUARDRAILS = [
  {
    title: "AI orchestrates, Python calculates",
    body: "Eve never computes a P&L, return or ratio. Every figure must come from a tool result in the same conversation.",
  },
  {
    title: "Numbers are checked after every answer",
    body: "A grounding pass traces each figure back to a tool output and flags any that don't match.",
  },
  {
    title: "Search luck is corrected",
    body: "Raw parameter-search winners are reported as uncorrected. Validation adds deflated Sharpe, a bootstrap interval and PBO.",
  },
  {
    title: "Side effects ask first",
    body: "Downloading or processing data is withheld unless enabled, and Eve confirms before calling either.",
  },
];

export default function AgentView({
  status,
  loading,
  onRefresh,
  onStartChat,
}: {
  status: Status | null;
  loading: boolean;
  onRefresh: () => void;
  onStartChat: () => void;
}) {
  const bridgeOk = status?.bridge.ok ?? false;
  const modelOk = status?.model.ok ?? false;
  const months = Object.entries(status?.months ?? {}).sort(([a], [b]) => b.localeCompare(a));
  const tools = status?.tools ?? [];

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-measure flex-col gap-section px-page py-section">
        {/* ── identity ─────────────────────────────────── */}
        <header className="flex flex-wrap items-start gap-card" style={{ animation: "fade-up 400ms cubic-bezier(0.23,1,0.32,1) both" }}>
          <EveMark size={44} />
          <div className="min-w-0 flex-1">
            <h1 className="text-[22px] font-semibold tracking-tight text-ink">Eve</h1>
            <p className="mt-1 max-w-lg text-[14px] leading-6 text-ink-2">
              Research assistant for NIFTY index futures. Eve plans the analysis and calls the quant engine; the engine does
              the maths.
            </p>
          </div>
          <div className="flex gap-tight">
            <button
              type="button"
              onClick={onRefresh}
              className="flex h-9 items-center gap-1.5 rounded-control bg-surface px-3 text-[13px] font-medium text-ink-2 shadow-card transition-colors hover:text-ink"
            >
              <span className={loading ? "animate-spin" : ""}>
                <IconRetry size={14} />
              </span>
              Refresh
            </button>
            <button
              type="button"
              onClick={onStartChat}
              className="flex h-9 items-center rounded-control bg-ink px-3.5 text-[13px] font-medium text-surface transition-transform active:scale-[0.98]"
            >
              Start a chat
            </button>
          </div>
        </header>

        {/* ── health ───────────────────────────────────── */}
        <Section title="Status">
          <div className="grid grid-cols-1 gap-stack sm:grid-cols-2">
            <HealthCard
              label="Quant engine"
              ok={bridgeOk}
              pending={!status}
              value={bridgeOk ? `${status?.bridge.tools ?? tools.length} tools online` : "Offline"}
              detail={bridgeOk ? status?.bridge.url : status?.bridge.error ?? "Checking…"}
              fix={!bridgeOk && status ? <Code>uv run python -m mcp.quant_server.http_bridge</Code> : undefined}
            />
            <HealthCard
              label="Model"
              ok={modelOk}
              pending={!status}
              value={status ? `${status.model.provider} · ${status.model.id}` : "Checking…"}
              detail={status?.model.detail}
              fix={
                !modelOk && status ? (
                  <>
                    Set <Code>GROQ_API_KEY</Code> in <Code>apps/web/.env.local</Code> and restart. Keys at{" "}
                    <a className="text-accent-ink underline underline-offset-2" href="https://console.groq.com/keys" target="_blank" rel="noreferrer">
                      console.groq.com/keys
                    </a>
                  </>
                ) : undefined
              }
            />
          </div>
        </Section>

        {/* ── data ─────────────────────────────────────── */}
        <Section title="Research data" icon={<IconCalendar size={15} />} meta={months.length ? `${months.length} months` : undefined}>
          {months.length > 0 ? (
            <div className="overflow-hidden rounded-card bg-surface shadow-card">
              <table className="w-full text-[13px] tabular-nums">
                <thead>
                  <tr className="bg-inset text-left text-[12px] text-ink-3">
                    <th className="px-card py-tight font-medium">Month</th>
                    {["1m", "5m", "15m"].map((tf) => (
                      <th key={tf} className="px-card py-tight text-right font-medium">
                        {tf} bars
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {months.map(([month, tfs]) => (
                    <tr key={month} className="border-t border-line">
                      <td className="px-card py-tight font-mono font-medium text-ink">{month}</td>
                      {["1m", "5m", "15m"].map((tf) => (
                        <td key={tf} className="px-card py-tight text-right text-ink-2">
                          {tfs[tf]?.toLocaleString() ?? <span className="text-ink-3">–</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>{bridgeOk ? "No processed months found." : "Start the quant engine to list processed months."}</Empty>
          )}
        </Section>

        {/* ── strategy defaults ─────────────────────────── */}
        <Section title="Strategy defaults" icon={<IconChart size={15} />} meta="EMA crossover + angle">
          <div className="grid grid-cols-2 gap-tight sm:grid-cols-3">
            {STRATEGY_DEFAULTS.map((d) => (
              <div key={d.label} className="flex flex-col gap-0.5 rounded-card bg-surface px-card py-stack shadow-card">
                <span className="text-[12px] text-ink-3">{d.label}</span>
                <span className="truncate font-mono text-[14px] font-medium text-ink">{d.value}</span>
              </div>
            ))}
          </div>
        </Section>

        {/* ── tools ────────────────────────────────────── */}
        <Section title="Tools" icon={<IconTool size={15} />} meta={tools.length ? `${tools.length} available` : undefined}>
          {tools.length > 0 ? <ToolList tools={tools} /> : <Empty>{bridgeOk ? "The engine returned no tools." : "Tools appear here once the engine is running."}</Empty>}
        </Section>

        {/* ── guardrails ───────────────────────────────── */}
        <Section title="Guardrails" icon={<IconShield size={15} />}>
          <div className="grid grid-cols-1 gap-tight sm:grid-cols-2">
            {GUARDRAILS.map((g) => (
              <div key={g.title} className="flex flex-col gap-1 rounded-card bg-surface p-card shadow-card">
                <span className="text-[13px] font-medium text-ink">{g.title}</span>
                <span className="text-[12.5px] leading-5 text-ink-2">{g.body}</span>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, icon, meta, children }: { title: string; icon?: ReactNode; meta?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-stack">
      <div className="flex items-center gap-1.5 text-ink-2">
        {icon && <span className="text-ink-3">{icon}</span>}
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
        {meta && <span className="ml-auto text-[12px] text-ink-3">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

function HealthCard({
  label,
  ok,
  pending,
  value,
  detail,
  fix,
}: {
  label: string;
  ok: boolean;
  pending: boolean;
  value: string;
  detail?: string;
  fix?: ReactNode;
}) {
  const tone = pending ? "bg-ink-3" : ok ? "bg-green" : "bg-red";
  return (
    <div className="flex flex-col gap-tight rounded-card bg-surface p-card shadow-card">
      <div className="flex items-center gap-2">
        <span className="text-[12px] text-ink-3">{label}</span>
        <span
          className={`ml-auto flex h-5 items-center gap-1.5 rounded-full px-2 text-[11.5px] font-medium ${
            pending ? "bg-field text-ink-3" : ok ? "bg-green-tint text-green" : "bg-red-tint text-red"
          }`}
        >
          <span className={`size-1.5 rounded-full ${tone}`} />
          {pending ? "Checking" : ok ? "Ready" : "Needs setup"}
        </span>
      </div>
      <span className="truncate text-[15px] font-medium text-ink">{value}</span>
      {detail && <span className="truncate text-[12px] text-ink-3" title={detail}>{detail}</span>}
      {fix && <div className="rounded-control bg-inset p-stack text-[12.5px] leading-5 text-ink-2 shadow-hairline">{fix}</div>}
    </div>
  );
}

function ToolList({ tools }: { tools: { name: string; description: string }[] }) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const visible = tools.filter((t) => !q || t.name.includes(q) || t.description.toLowerCase().includes(q));

  return (
    <div className="flex flex-col overflow-hidden rounded-card bg-surface shadow-card">
      <label className="flex h-10 items-center gap-2 border-b border-line px-card text-ink-3">
        <IconSearch size={14} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter tools"
          aria-label="Filter tools"
          className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3"
        />
      </label>
      <ul className="flex flex-col">
        {visible.map((t) => (
          <li key={t.name} className="flex flex-col gap-0.5 border-b border-line px-card py-stack last:border-b-0">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-[13px] font-medium text-ink">{humanizeTool(t.name)}</span>
              <span className="font-mono text-[11.5px] text-ink-3">{t.name}</span>
            </div>
            <p className="line-clamp-2 text-[12.5px] leading-5 text-ink-2">{firstParagraph(t.description)}</p>
          </li>
        ))}
        {visible.length === 0 && <li className="px-card py-stack text-[12.5px] text-ink-3">No tools match “{query}”.</li>}
      </ul>
    </div>
  );
}

/** Tool docstrings run long; the first paragraph is the summary. */
function firstParagraph(text: string) {
  return text.split(/\n\s*\n/)[0].replace(/\s+/g, " ").trim();
}

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded-[5px] bg-field px-1.5 py-px font-mono text-[11.5px] text-ink">{children}</code>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-card bg-surface px-card py-stack text-[13px] text-ink-3 shadow-card">{children}</div>;
}
