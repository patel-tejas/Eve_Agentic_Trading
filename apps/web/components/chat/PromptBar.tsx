"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { IconArrowUp, IconCalendar, IconChart, IconPlus, IconStop } from "@/components/ui/icons";

/* ─────────────────────────────────────────────────────────
 * PROMPT BAR
 * Eve's composer. Type @ to tag a processed month, / for a
 * research command; ↑↓ + Enter to pick, Esc to dismiss.
 * Enter sends, Shift+Enter adds a line. While Eve works the
 * send button becomes Stop.
 * ───────────────────────────────────────────────────────── */

export type PromptCommand = { key: string; name: string; desc: string; prompt: string };

type Row = { key: string; name: string; desc: string; kind: "month" | "command" };

/* the last @word or /word being typed, if any */
function parseToken(draft: string): { kind: "at" | "slash"; query: string; start: number } | null {
  const match = /(^|\s)([@/])([\w-]*)$/.exec(draft);
  if (!match) return null;
  return {
    kind: match[2] === "@" ? "at" : "slash",
    query: match[3].toLowerCase(),
    start: match.index + match[1].length,
  };
}

export default function PromptBar({
  months,
  commands,
  modelLabel,
  modelOk,
  busy,
  tall = false,
  placeholder = "Ask Eve about a month, a backtest, a parameter sweep…",
  onSend,
  onStop,
}: {
  /** processed months, offered in the @ menu: { "2026-07": { "1m": 8000, … } } */
  months: Record<string, Record<string, number>>;
  /** research shortcuts offered in the / menu */
  commands: PromptCommand[];
  modelLabel: string;
  modelOk: boolean;
  busy: boolean;
  /** hero sizing for the empty state: taller input, roomier padding */
  tall?: boolean;
  placeholder?: string;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [dismissed, setDismissed] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [engaged, setEngaged] = useState(false);
  const [rowBox, setRowBox] = useState<{ top: number; height: number } | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const token = dismissed ? null : parseToken(draft);
  const menu: "at" | "slash" | null = plusOpen ? "slash" : token?.kind ?? null;
  const query = plusOpen ? "" : token?.query ?? "";

  const monthRows: Row[] = Object.entries(months)
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([month, tfs]) => ({
      key: month,
      name: month,
      desc: Object.keys(tfs).join(" · ") || "no timeframes",
      kind: "month",
    }));

  const rows: Row[] =
    menu === "at"
      ? monthRows.filter((r) => r.name.includes(query))
      : menu === "slash"
        ? commands
            .filter((c) => c.name.slice(1).startsWith(query))
            .map((c) => ({ key: c.key, name: c.name, desc: c.desc, kind: "command" }))
        : [];

  // A new menu or query starts the highlight back at the top row.
  const menuKey = `${menu}:${query}`;
  const [prevMenuKey, setPrevMenuKey] = useState(menuKey);
  if (prevMenuKey !== menuKey) {
    setPrevMenuKey(menuKey);
    setActive(0);
    setEngaged(false);
  }

  /* a single highlight glides to the active row */
  useLayoutEffect(() => {
    const target = rowRefs.current[active];
    if (target) setRowBox({ top: target.offsetTop, height: target.offsetHeight });
  }, [menu, query, active, rows.length]);

  /* grow with the text up to a compact maximum, then scroll */
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const min = tall ? 56 : 24;
    const max = tall ? 200 : 160;
    input.style.height = "0px";
    const h = input.scrollHeight;
    input.style.height = `${Math.min(Math.max(h, min), max)}px`;
    input.style.overflowY = h > max ? "auto" : "hidden";
  }, [draft, tall]);

  /* clicking outside the composer closes the menu */
  useEffect(() => {
    if (!plusOpen) return;
    const close = (event: PointerEvent) => {
      if (!(event.target as Element).closest("[data-promptbar]")) setPlusOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [plusOpen]);

  const pick = (row: Row) => {
    const before = token ? draft.slice(0, token.start) : draft;
    if (row.kind === "month") {
      setDraft(`${before}${row.name} `);
    } else {
      const command = commands.find((c) => c.key === row.key);
      // a command expands into its full prompt so it can be edited before sending
      setDraft(command ? command.prompt : `${before}${row.name} `);
    }
    setPlusOpen(false);
    setDismissed(false);
    inputRef.current?.focus();
  };

  const canSend = draft.trim().length > 0 && !busy;
  const send = () => {
    if (!canSend) return;
    onSend(draft.trim());
    setDraft("");
    setPlusOpen(false);
  };

  return (
    <div data-promptbar className="relative w-full">
      {/* ── @ / slash menu, growing up from the composer ── */}
      {menu && (
        <div
          onMouseLeave={() => setEngaged(false)}
          className="absolute inset-x-0 bottom-full z-20 mb-2 rounded-card bg-surface p-1 shadow-raised"
          style={{ animation: "pop-in 180ms cubic-bezier(0.23,1,0.32,1) both", transformOrigin: "bottom center" }}
        >
          <span
            aria-hidden
            className="pointer-events-none absolute inset-x-1 rounded-chip bg-hover-2"
            style={{
              top: rowBox?.top ?? 0,
              height: rowBox?.height ?? 0,
              opacity: rowBox && (engaged || rows.length > 0) ? 1 : 0,
              transition:
                "top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease",
            }}
          />
          {rows.map((row, i) => (
            <button
              key={row.key}
              type="button"
              ref={(el) => {
                rowRefs.current[i] = el;
              }}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => {
                setActive(i);
                setEngaged(true);
              }}
              onClick={() => pick(row)}
              className="relative z-10 flex h-9 w-full items-center gap-2.5 rounded-chip px-2 text-left"
            >
              <span className="flex size-5 shrink-0 items-center justify-center text-ink-2">
                {row.kind === "month" ? <IconCalendar size={15} /> : <IconChart size={15} />}
              </span>
              <span className={`shrink-0 text-[13px] font-medium text-ink ${row.kind === "month" ? "font-mono" : ""}`}>
                {row.name}
              </span>
              <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3">{row.desc}</span>
            </button>
          ))}
          {rows.length === 0 && (
            <div className="flex h-9 items-center px-2 text-[12px] text-ink-3">
              {menu === "at" && monthRows.length === 0
                ? "No processed months yet. Start the engine to list them."
                : `No matches for “${query}”`}
            </div>
          )}
          <div className="mt-1 border-t border-line px-2 pt-1.5 pb-1 text-[11px] text-ink-3">
            {menu === "at" ? "Tag a processed month" : "Pick a command, then edit before sending"}
          </div>
        </div>
      )}

      {/* ── composer ───────────────────────────────────── */}
      <div
        role="presentation"
        onClick={() => inputRef.current?.focus()}
        className={`flex cursor-text flex-col gap-tight border border-line bg-surface shadow-card transition-[border-color,box-shadow] duration-150 focus-within:border-line-strong ${
          tall ? "rounded-panel p-stack" : "rounded-card p-tight"
        }`}
      >
        <textarea
          ref={inputRef}
          rows={1}
          value={draft}
          autoFocus
          onChange={(event) => {
            setDraft(event.target.value);
            setDismissed(false);
            setPlusOpen(false);
          }}
          onKeyDown={(event) => {
            if (menu && rows.length > 0) {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                setEngaged(true);
                setActive((current) => (current + (event.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length);
                return;
              }
              if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
                event.preventDefault();
                pick(rows[active]);
                return;
              }
            }
            if (event.key === "Escape") {
              setDismissed(true);
              setPlusOpen(false);
              return;
            }
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              send();
            }
          }}
          placeholder={placeholder}
          aria-label="Message Eve"
          className={`w-full min-w-0 resize-none bg-transparent px-1.5 text-ink outline-none [overflow-wrap:anywhere] placeholder:text-ink-3 ${
            tall ? "pt-1 text-[15px] leading-6" : "pt-1 text-[14px] leading-6"
          }`}
        />

        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Research commands"
            aria-expanded={plusOpen}
            onClick={(event) => {
              event.stopPropagation();
              setPlusOpen((current) => !current);
              inputRef.current?.focus();
            }}
            className={`flex size-8 shrink-0 items-center justify-center rounded-control text-ink-3 transition-[background-color,color,transform] duration-150 hover:bg-hover-2 hover:text-ink active:scale-[0.94] ${
              plusOpen ? "bg-hover-2 text-ink" : ""
            }`}
          >
            <IconPlus size={17} strokeWidth={2} />
          </button>

          <span className="hidden items-center gap-1 text-[12px] text-ink-3 sm:flex">
            <kbd className="rounded-[4px] bg-field px-1 font-mono text-[11px] text-ink-2">@</kbd> month
            <kbd className="ml-1.5 rounded-[4px] bg-field px-1 font-mono text-[11px] text-ink-2">/</kbd> command
          </span>

          <span
            title={modelOk ? "Model ready" : "Model not ready. See the Agent tab."}
            className="ml-auto flex h-8 min-w-0 items-center gap-1.5 rounded-control px-2 text-[12px] font-medium text-ink-2"
          >
            <span className={`size-1.5 shrink-0 rounded-full ${modelOk ? "bg-green" : "bg-red"}`} />
            <span className="truncate">{modelLabel}</span>
          </span>

          {busy ? (
            <button
              type="button"
              aria-label="Stop"
              onClick={(event) => {
                event.stopPropagation();
                onStop();
              }}
              className="flex size-8 shrink-0 items-center justify-center rounded-control bg-ink text-surface transition-transform duration-150 active:scale-[0.94]"
            >
              <IconStop size={12} />
            </button>
          ) : (
            <button
              type="button"
              aria-label="Send"
              disabled={!canSend}
              onClick={(event) => {
                event.stopPropagation();
                send();
              }}
              className="flex size-8 shrink-0 items-center justify-center rounded-control transition-[background-color,color,transform] duration-200 enabled:active:scale-[0.94]"
              style={{
                background: canSend ? "var(--ink)" : "var(--line-strong)",
                color: canSend ? "var(--surface)" : "var(--ink-2)",
              }}
            >
              <IconArrowUp size={16} strokeWidth={2.4} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
