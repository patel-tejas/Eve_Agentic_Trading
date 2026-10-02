"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import GlideMenu from "@/components/ui/GlideMenu";
import {
  EveMark,
  IconChat,
  IconChevronDown,
  IconEdit,
  IconMoon,
  IconSearch,
  IconSidebar,
  IconSpark,
  IconSun,
  IconTrash,
  IconX,
} from "@/components/ui/icons";

/* ─────────────────────────────────────────────────────────
 * SIDEBAR NAV
 * Eve's app shell: new chat, the Chat / Agent views,
 * searchable chat history, a theme switch, and a collapse
 * that keeps every icon in the same column.
 * ───────────────────────────────────────────────────────── */

export type SidebarRecent = { id: string; label: string };
export type View = "chat" | "agent";

const NAV_ITEMS: { key: View; label: string; icon: ReactNode }[] = [
  { key: "chat", label: "Chat", icon: <IconChat size={17} /> },
  { key: "agent", label: "Agent", icon: <IconSpark size={17} /> },
];

const SIDEBAR_MOTION = {
  expandedWidth: 248,
  collapsedWidth: 52,
  duration: 280,
  copyDuration: 180,
  copyOffset: 8,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
};

/* ─────────────────────────────────────────────────────────
 * CHAT SEARCH STORYBOARD
 *
 *   0ms   search is triggered; Chats label begins fading
 *   0ms   field grows right → left from the search control
 * 180ms   field fills the row; cursor is focused and ready
 * ───────────────────────────────────────────────────────── */
const CHAT_SEARCH_MOTION = {
  duration: 180,
  closedWidth: 32,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
};

function GlideGroup({ children }: { children: ReactNode }) {
  return (
    <GlideMenu rowSelector="[data-row]" highlightClassName="rounded-control bg-hover-2" className="group/glide flex flex-col gap-px">
      {children}
    </GlideMenu>
  );
}

function RailButton({
  icon,
  label,
  active = false,
  badge,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
  badge?: ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      data-row
      type="button"
      title={label}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={`sidebar-row relative z-10 mx-2 flex h-9 items-center rounded-control px-2 text-left
        transition-[width,background-color,color,transform] duration-150 active:scale-[0.98]
        ${active ? "bg-hover-2 group-hover/glide:bg-transparent" : ""}`}
    >
      <span className={`flex size-5 shrink-0 items-center justify-center ${active ? "text-ink" : "text-ink-2"}`}>{icon}</span>
      <span className={`sidebar-copy ml-2 min-w-0 flex-1 truncate text-[14px] font-medium ${active ? "text-ink" : "text-ink-2"}`}>
        {label}
      </span>
      {badge && <span className="sidebar-copy mr-1 shrink-0">{badge}</span>}
    </button>
  );
}

export default function SidebarNav({
  view,
  onNavigate,
  recents,
  activeChatId,
  onNewChat,
  onPick,
  onDelete,
  agentOk,
  theme,
  onToggleTheme,
}: {
  view: View;
  onNavigate: (view: View) => void;
  recents: SidebarRecent[];
  activeChatId: string | null;
  onNewChat: () => void;
  onPick: (id: string) => void;
  onDelete: (id: string) => void;
  /** engine and model both ready */
  agentOk: boolean;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}) {
  // Phones start on the icon rail so the conversation keeps the width.
  // (The shell renders client-only, so window is available here.)
  const [collapsed, setCollapsed] = useState(() => window.matchMedia("(max-width: 767px)").matches);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  const visibleRecents = recents.filter((item) => item.label.toLowerCase().includes(query.trim().toLowerCase()));

  const collapse = () => {
    setCollapsed(true);
    setSearchOpen(false);
    setQuery("");
  };

  return (
    <aside
      data-sidebar-collapsed={collapsed}
      aria-label="Eve navigation"
      className="relative flex h-full shrink-0 overflow-hidden border-r border-line bg-canvas transition-[width]"
      style={
        {
          width: collapsed ? SIDEBAR_MOTION.collapsedWidth : SIDEBAR_MOTION.expandedWidth,
          transitionDuration: `${SIDEBAR_MOTION.duration}ms`,
          transitionTimingFunction: SIDEBAR_MOTION.easing,
          "--sidebar-copy-duration": `${SIDEBAR_MOTION.copyDuration}ms`,
          "--sidebar-copy-offset": `${SIDEBAR_MOTION.copyOffset}px`,
          "--sidebar-easing": SIDEBAR_MOTION.easing,
        } as CSSProperties
      }
    >
      <div className="flex min-h-0 shrink-0 flex-col py-2.5" style={{ width: SIDEBAR_MOTION.expandedWidth }}>
        {/* ── brand + collapse ─────────────────────────── */}
        <div className="relative mb-2 h-10 shrink-0">
          <div className="sidebar-workspace-control absolute top-1 left-2 flex h-8 items-center gap-2 px-2">
            <EveMark size={20} />
            <span className="sidebar-copy flex min-w-0 flex-col leading-tight">
              <span className="text-[14px] font-semibold text-ink">Eve</span>
            </span>
            <span className="sidebar-copy text-[12px] text-ink-3">NIFTY research</span>
          </div>

          <button
            type="button"
            aria-label="Collapse sidebar"
            aria-hidden={collapsed}
            tabIndex={collapsed ? -1 : 0}
            onClick={collapse}
            className="sidebar-collapse-control absolute top-1 right-2 flex size-8 items-center justify-center rounded-control text-ink-3 transition-[opacity,background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
          >
            <IconSidebar size={17} />
          </button>
          <button
            type="button"
            aria-label="Expand sidebar"
            aria-hidden={!collapsed}
            tabIndex={collapsed ? 0 : -1}
            onClick={() => setCollapsed(false)}
            className="sidebar-expand-control absolute top-1 left-2 flex size-9 items-center justify-center rounded-control text-ink-3 transition-[opacity,background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
          >
            <IconSidebar size={17} />
          </button>
        </div>

        {/* ── primary nav ──────────────────────────────── */}
        <GlideGroup>
          <RailButton icon={<IconEdit size={17} />} label="New chat" onClick={onNewChat} />
          {NAV_ITEMS.map((item) => (
            <RailButton
              key={item.key}
              icon={item.icon}
              label={item.label}
              active={view === item.key}
              onClick={() => onNavigate(item.key)}
              badge={
                item.key === "agent" ? (
                  <span
                    title={agentOk ? "Engine and model ready" : "Setup needed"}
                    className={`block size-1.5 rounded-full ${agentOk ? "bg-green" : "bg-amber"}`}
                  />
                ) : undefined
              }
            />
          ))}
        </GlideGroup>

        {/* ── chat history ─────────────────────────────── */}
        <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
          <div className="sidebar-copy relative mx-2 mb-1 h-8">
            <div
              aria-hidden={searchOpen}
              className={`absolute inset-0 flex items-center gap-1.5 px-2 text-[12.5px] font-medium text-ink-3 transition-[opacity,transform] ${
                searchOpen ? "pointer-events-none -translate-x-1 opacity-0" : "translate-x-0 opacity-100"
              }`}
              style={{ transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms`, transitionTimingFunction: CHAT_SEARCH_MOTION.easing }}
            >
              <IconChevronDown size={14} />
              <span>Chats</span>
            </div>

            <button
              type="button"
              aria-label="Search chats"
              aria-expanded={searchOpen}
              onClick={() => setSearchOpen(true)}
              className={`absolute top-0 right-0 z-10 flex size-8 items-center justify-center rounded-control text-ink-3 transition-[opacity,background-color,color,transform] hover:bg-hover-2 hover:text-ink active:scale-[0.96] ${
                searchOpen ? "pointer-events-none opacity-0" : "opacity-100"
              }`}
              style={{ transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms` }}
            >
              <IconSearch size={15} />
            </button>

            <div
              className={`absolute top-0 right-0 z-20 flex h-8 items-center overflow-hidden rounded-control bg-field text-ink-3 shadow-hairline transition-[width,opacity] focus-within:text-ink-2 ${
                searchOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
              }`}
              style={{
                width: searchOpen ? "100%" : CHAT_SEARCH_MOTION.closedWidth,
                transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms`,
                transitionTimingFunction: CHAT_SEARCH_MOTION.easing,
              }}
            >
              <span className="ml-2 flex shrink-0 items-center justify-center">
                <IconSearch size={14} />
              </span>
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setSearchOpen(false);
                    setQuery("");
                  }
                }}
                placeholder="Search chats"
                aria-label="Search chat history"
                className="ml-1.5 min-w-0 flex-1 bg-transparent text-[13px] font-medium text-ink outline-none placeholder:text-ink-3"
              />
              <button
                type="button"
                aria-label="Close chat search"
                onClick={() => {
                  setSearchOpen(false);
                  setQuery("");
                }}
                className="flex size-8 shrink-0 items-center justify-center rounded-control text-ink-3 transition-[background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
              >
                <IconX size={14} />
              </button>
            </div>
          </div>

          <GlideGroup>
            {visibleRecents.map((item) => {
              const active = view === "chat" && item.id === activeChatId;
              return (
                <div key={item.id} className="group/row sidebar-copy relative">
                  <button
                    data-row
                    type="button"
                    title={item.label}
                    onClick={() => onPick(item.id)}
                    className={`relative z-10 mx-2 flex h-8 w-[calc(100%-1rem)] items-center rounded-control pr-8 pl-2 text-left transition-[background-color,transform] duration-150 active:scale-[0.98] ${
                      active ? "bg-hover-2 group-hover/glide:bg-transparent" : ""
                    }`}
                  >
                    <span className={`min-w-0 flex-1 truncate text-[13.5px] ${active ? "font-medium text-ink" : "text-ink-2"}`}>
                      {item.label}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete “${item.label}”`}
                    onClick={() => onDelete(item.id)}
                    className="absolute top-1 right-3 z-20 flex size-6 items-center justify-center rounded-chip text-ink-3 opacity-0 transition-[opacity,background-color,color] duration-150 group-hover/row:opacity-100 hover:bg-hover-2 hover:text-ink focus-visible:opacity-100"
                  >
                    <IconTrash size={13} />
                  </button>
                </div>
              );
            })}
            {recents.length === 0 && (
              <div className="sidebar-copy mx-2 px-2 py-2 text-[12.5px] text-ink-3">Your chats will show up here.</div>
            )}
            {query && recents.length > 0 && visibleRecents.length === 0 && (
              <div className="sidebar-copy mx-2 px-2 py-2 text-[12.5px] text-ink-3">No chats found</div>
            )}
          </GlideGroup>
        </div>

        {/* ── footer ───────────────────────────────────── */}
        <div className="mt-2 border-t border-line pt-2">
          <GlideGroup>
            <RailButton
              icon={theme === "dark" ? <IconSun size={17} /> : <IconMoon size={17} />}
              label={theme === "dark" ? "Light theme" : "Dark theme"}
              onClick={onToggleTheme}
            />
          </GlideGroup>
        </div>
      </div>
    </aside>
  );
}
