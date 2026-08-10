"use client";

import { useEffect, useMemo, useState } from "react";
import { useEveAgent } from "eve/react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type MetricRow = { label: string; value: string };

const METRIC_LABELS: Record<string, string> = {
  total_trades: "Trades",
  win_rate: "Win rate",
  gross_pnl: "Gross P&L",
  net_pnl: "Net P&L",
  profit_factor: "Profit factor",
  avg_trade_pnl: "Avg trade P&L",
  avg_holding_periods: "Avg holding (bars)",
  max_drawdown_pct: "Max drawdown",
  max_drawdown_duration_bars: "DD duration (bars)",
  sharpe: "Sharpe",
  sortino: "Sortino",
  calmar: "Calmar",
  trading_days: "Trading days",
};

function fmt(value: unknown, key: string): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (["net_pnl", "gross_pnl", "avg_trade_pnl"].includes(key)) {
      const sign = value < 0 ? "" : "+";
      return `${sign}\u20B9${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
    }
    if (["win_rate", "max_drawdown_pct"].includes(key)) {
      return `${(value * 100).toFixed(1)}%`;
    }
    return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }
  return String(value);
}

function MetricsGrid({ metrics }: { metrics: Record<string, unknown> }) {
  const rows: MetricRow[] = Object.entries(METRIC_LABELS)
    .filter(([key]) => key in metrics)
    .map(([key, label]) => ({ label, value: fmt(metrics[key], key) }));
  if (rows.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {rows.map((row) => (
        <div key={row.label} className="rounded-lg bg-zinc-900 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-zinc-500">
            {row.label}
          </div>
          <div className="text-sm font-medium text-zinc-100">{row.value}</div>
        </div>
      ))}
    </div>
  );
}

function EquityChart({ curve }: { curve: Array<{ timestamp: string; equity: number }> }) {
  const data = curve.map((point) => ({
    ...point,
    time: point.timestamp.slice(11, 16),
  }));
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#10b981" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#27272a" strokeDasharray="3 3" />
          <XAxis dataKey="time" stroke="#71717a" fontSize={10} tickCount={6} />
          <YAxis
            stroke="#71717a"
            fontSize={10}
            tickFormatter={(v: number) => `${(v / 1_000_000).toFixed(2)}M`}
            width={56}
            domain={["dataMin", "dataMax"]}
          />
          <Tooltip
            contentStyle={{ background: "#18181b", border: "1px solid #3f3f46" }}
            labelStyle={{ color: "#a1a1aa" }}
            formatter={(value) => [
              `\u20B9${Number(value).toLocaleString("en-IN")}`,
              "Equity",
            ]}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke="#10b981"
            strokeWidth={2}
            fill="url(#equityFill)"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function CompareTable({ table }: { table: Record<string, Record<string, Record<string, unknown>>> }) {
  const timeframes = useMemo(() => {
    const set = new Set<string>();
    Object.values(table).forEach((variant) => Object.keys(variant).forEach((tf) => set.add(tf)));
    return Array.from(set).sort(
      (a, b) => Number(String(a).replace("m", "")) - Number(String(b).replace("m", "")),
    );
  }, [table]);
  if (timeframes.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500">
            <th className="py-1.5 pr-3">Variant</th>
            {timeframes.map((tf) => (
              <th key={tf} className="px-3 py-1.5">
                {tf}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.entries(table).map(([variant, rows]) => (
            <tr key={variant} className="border-b border-zinc-900">
              <td className="py-1.5 pr-3 font-medium text-zinc-300">Variant {variant}</td>
              {timeframes.map((tf) => {
                const cell = rows[tf];
                if (!cell) return <td key={tf} className="px-3 py-1.5 text-zinc-600">—</td>;
                const net = Number(cell.net_pnl ?? 0);
                return (
                  <td key={tf} className="px-3 py-1.5">
                    <div className={net > 0 ? "text-emerald-400" : net < 0 ? "text-rose-400" : "text-zinc-400"}>
                      {fmt(cell.net_pnl, "net_pnl")}
                    </div>
                    <div className="text-[10px] text-zinc-500">
                      {Number(cell.total_trades ?? 0)} trades · PF {fmt(cell.profit_factor, "profit_factor")}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunsTable({ runs }: { runs: Array<Record<string, unknown>> }) {
  const cols = [
    ["month", "Month"],
    ["timeframe", "TF"],
    ["variant", "Var"],
    ["signal_mode", "Mode"],
    ["total_trades", "Trades"],
    ["win_rate", "Win"],
    ["net_pnl", "Net P&L"],
    ["profit_factor", "PF"],
    ["sharpe", "Sharpe"],
  ] as const;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500">
            {cols.map(([key, label]) => (
              <th key={key} className="px-2 py-1.5">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run, i) => (
            <tr key={i} className="border-b border-zinc-900">
              {cols.map(([key]) => {
                const value = run[key];
                if (key === "net_pnl") {
                  const net = Number(value ?? 0);
                  return (
                    <td
                      key={key}
                      className={`px-2 py-1.5 ${net > 0 ? "text-emerald-400" : net < 0 ? "text-rose-400" : "text-zinc-400"}`}
                    >
                      {fmt(value, key)}
                    </td>
                  );
                }
                if (key === "win_rate") {
                  return (
                    <td key={key} className="px-2 py-1.5 text-zinc-300">
                      {fmt(value, key)}
                    </td>
                  );
                }
                return (
                  <td key={key} className="px-2 py-1.5 text-zinc-300">
                    {fmt(value, key)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({ trades }: { trades: Array<Record<string, unknown>> }) {
  const cols = [
    ["direction", "Dir"],
    ["entry_time", "Entry"],
    ["exit_time", "Exit"],
    ["entry_price", "Entry Px"],
    ["exit_price", "Exit Px"],
    ["gross_pnl", "Gross"],
    ["net_pnl", "Net"],
  ] as const;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500">
            {cols.map(([key, label]) => (
              <th key={key} className="px-2 py-1.5">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, i) => {
            const net = Number(trade.net_pnl ?? 0);
            return (
              <tr key={i} className="border-b border-zinc-900">
                <td className="px-2 py-1.5">
                  <span className={trade.direction === "LONG" ? "text-emerald-400" : "text-rose-400"}>
                    {String(trade.direction)}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-zinc-300">{String(trade.entry_time ?? "").slice(5, 16)}</td>
                <td className="px-2 py-1.5 text-zinc-300">{String(trade.exit_time ?? "").slice(5, 16)}</td>
                <td className="px-2 py-1.5 text-zinc-300">{fmt(trade.entry_price, "entry_price")}</td>
                <td className="px-2 py-1.5 text-zinc-300">{fmt(trade.exit_price, "exit_price")}</td>
                <td className="px-2 py-1.5 text-zinc-300">{fmt(trade.gross_pnl, "net_pnl")}</td>
                <td className={`px-2 py-1.5 ${net > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  {fmt(trade.net_pnl, "net_pnl")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ToolResultView({ result }: { result: unknown }) {
  if (result == null || typeof result !== "object") return null;
  const payload = result as Record<string, unknown>;

  const curves: Array<{ timestamp: string; equity: number }> = Array.isArray(
    payload.equity_curve,
  )
    ? (payload.equity_curve as Array<{ timestamp: string; equity: number }>)
    : [];
  const hasMetrics = payload.metrics != null && typeof payload.metrics === "object";

  const view = (() => {
    if (hasMetrics) return <MetricsGrid metrics={payload.metrics as Record<string, unknown>} />;
    if (payload.comparison_table != null)
      return <CompareTable table={payload.comparison_table as never} />;
    if (Array.isArray(payload.runs)) return <RunsTable runs={payload.runs as never} />;
    if (Array.isArray(payload.trades)) return <TradesTable trades={payload.trades as never} />;
    return null;
  })();

  if (curves.length > 0 && !hasMetrics) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-2">
        <EquityChart curve={curves} />
      </div>
    );
  }

  if (!view && curves.length === 0) return null;

  return (
    <div className="space-y-3">
      {curves.length > 0 && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-2">
          <EquityChart curve={curves} />
        </div>
      )}
      {view}
    </div>
  );
}

type LoosePart = {
  type?: string;
  text?: string;
  toolCallId?: string;
  toolName?: string;
  args?: unknown;
  result?: unknown;
  isError?: boolean;
};

type LooseMessage = {
  id?: string;
  role?: string;
  parts?: LoosePart[];
};

function MessageView({ message }: { message: LooseMessage }) {
  const toolNames = useMemo(() => {
    const map = new Map<string, string>();
    (message.parts ?? []).forEach((part) => {
      if (part.type === "tool-call" && part.toolCallId) {
        map.set(part.toolCallId, part.toolName ?? "");
      }
    });
    return map;
  }, [message.parts]);

  const isUser = message.role === "user";
  return (
    <article className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] space-y-2.5 rounded-2xl px-4 py-3 ${
          isUser ? "rounded-br-sm bg-emerald-600/15 text-zinc-100" : "bg-zinc-900 text-zinc-200"
        }`}
      >
        {(message.parts ?? []).map((part, index) => {
          if (part.type === "text") {
            return (
              <p key={index} className="whitespace-pre-wrap text-sm leading-relaxed">
                {part.text}
              </p>
            );
          }
          if (part.type === "tool-call") {
            const name = part.toolName ?? "";
            const args = (part.args ?? {}) as Record<string, unknown>;
            const month = (args.month as string) ?? "";
            const tf = (args.timeframe as string) ?? "";
            return (
              <div key={index} className="flex items-center gap-2 text-xs text-zinc-500">
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-emerald-400/90">
                  {name}
                </span>
                {month && <span>{month}</span>}
                {tf && <span className="font-mono">{tf}</span>}
              </div>
            );
          }
          if (part.type === "tool-result") {
            const name = (part.toolName ?? toolNames.get(part.toolCallId ?? "")) ?? "";
            if (part.isError) {
              return (
                <div key={index} className="rounded-lg border border-rose-900 bg-rose-950/40 p-2 text-xs text-rose-300">
                  {String((part.result as { error?: string })?.error ?? "Tool failed")}
                </div>
              );
            }
            return (
              <div key={index} className="space-y-1">
                {name && (
                  <div className="text-[10px] uppercase tracking-wide text-zinc-500">
                    {name}
                  </div>
                )}
                <ToolResultView result={part.result} />
              </div>
            );
          }
          return null;
        })}
        {message.parts?.length === 0 && (
          <p className="text-sm text-zinc-400">
            {isUser ? "" : "Thinking…"}
          </p>
        )}
      </div>
    </article>
  );
}

const SUGGESTIONS = [
  "Backtest August 2026 on 5m with the default strategy",
  "Compare variants A/B/C across timeframes for August 2026",
  "Which recorded configs beat the baseline?",
];

type SavedChat = {
  events?: unknown[];
  session?: unknown;
};

export default function EveChat() {
  const [saved] = useState<SavedChat>(() => {
    if (typeof window === "undefined") return {};
    try {
      const raw = localStorage.getItem("eve-chat");
      return raw ? (JSON.parse(raw) as SavedChat) : {};
    } catch {
      return {};
    }
  });

  const agent = useEveAgent({
    initialEvents: (saved.events as never[]) ?? [],
    initialSession: saved.session as never,
    onFinish(snapshot) {
      try {
        localStorage.setItem(
          "eve-chat",
          JSON.stringify({ events: snapshot.events, session: snapshot.session }),
        );
      } catch {
        /* storage full/unavailable — ignore */
      }
    },
  });

  const isBusy = agent.status === "submitted" || agent.status === "streaming";
  const messages = agent.data.messages;

  useEffect(() => {
    if (agent.error) console.error("eve agent error:", agent.error);
  }, [agent.error]);

  return (
    <main className="mx-auto flex h-screen max-w-4xl flex-col bg-zinc-950 px-4 text-zinc-200">
      <header className="flex items-center justify-between py-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-zinc-50">Eve · Quant Research</h1>
          <p className="text-xs text-zinc-500">
            EMA 9/15 + angle strategy · NIFTY futures · deterministic engine
          </p>
        </div>
        <button
          onClick={() => {
            agent.reset();
            try {
              localStorage.removeItem("eve-chat");
            } catch {
              /* ignore */
            }
          }}
          className="rounded-lg border border-zinc-800 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-zinc-600 hover:text-zinc-200"
        >
          New session
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto pb-4">
        {messages.length === 0 ? (
          <div className="mt-16 flex flex-col items-center gap-4 text-center">
            <p className="max-w-md text-sm text-zinc-500">
              Ask Eve to run research on the quant engine. Results — metrics,
              comparisons, trades and equity curves — render right in the chat.
            </p>
            <div className="flex flex-col gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => void agent.send(suggestion)}
                  disabled={isBusy}
                  className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2 text-left text-sm text-zinc-300 transition-colors hover:border-emerald-700 hover:text-emerald-300 disabled:opacity-50"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message) => <MessageView key={message.id} message={message as never} />)
        )}
        {agent.status === "error" && (
          <div className="rounded-lg border border-rose-900 bg-rose-950/40 p-3 text-xs text-rose-300">
            {agent.error instanceof Error ? agent.error.message : String(agent.error)}
          </div>
        )}
      </div>

      <form
        className="border-t border-zinc-900 py-4"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const message = String(form.get("message") ?? "").trim();
          if (message.length === 0 || isBusy) return;
          void agent.send(message);
          event.currentTarget.reset();
        }}
      >
        <div className="flex items-end gap-2">
          <textarea
            name="message"
            rows={1}
            placeholder={
              isBusy
                ? "Eve is working…"
                : 'Try "Backtest August 2026 on 5m"'
            }
            disabled={isBusy}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                const form = event.currentTarget.closest("form");
                if (form) {
                  form.requestSubmit();
                }
              }
            }}
            className="min-h-[44px] flex-1 resize-none rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-700 focus:outline-none disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={isBusy}
            className="h-[44px] rounded-xl bg-emerald-600 px-5 text-sm font-medium text-zinc-950 transition-colors hover:bg-emerald-500 disabled:opacity-50"
          >
            {isBusy ? "…" : "Send"}
          </button>
        </div>
      </form>
    </main>
  );
}