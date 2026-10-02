"use client";

/**
 * Eve's app shell: sidebar (new chat, Chat / Agent, history) beside the
 * active view. Conversations are kept in this browser's localStorage; the
 * server stays stateless. Rendered client-only (see app/page.tsx), so state
 * can initialise straight from storage.
 */

import type { UIMessage } from "ai";
import { useCallback, useEffect, useState } from "react";

import AgentView from "@/components/agent/AgentView";
import ChatView from "@/components/chat/ChatView";
import SidebarNav, { type View } from "@/components/shell/SidebarNav";
import type { ChatRecord, Status } from "@/lib/types";

const STORAGE_KEY = "eve.chats.v1";
const THEME_KEY = "eve.theme";
const MAX_CHATS = 40;

function newId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function titleFrom(messages: UIMessage[]) {
  const first = messages.find((m) => m.role === "user");
  const text = first?.parts
    .filter((p) => p.type === "text")
    .map((p) => (p as { text: string }).text)
    .join(" ")
    .trim();
  if (!text) return "New chat";
  return text.length > 48 ? `${text.slice(0, 47)}…` : text;
}

function loadChats(): ChatRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ChatRecord[]) : [];
  } catch {
    return [];
  }
}

function saveChats(chats: ChatRecord[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(chats.slice(0, MAX_CHATS)));
  } catch {
    // Full or blocked storage only costs history, never the live chat.
  }
}

export default function AppShell() {
  const [status, setStatus] = useState<Status | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [view, setView] = useState<View>("chat");
  const [chats, setChats] = useState<ChatRecord[]>(loadChats);
  const [activeId, setActiveId] = useState<string>(newId);
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );

  const fetchStatus = useCallback(() => {
    fetch("/api/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setStatusLoading(false));
  }, []);

  const refreshStatus = () => {
    setStatusLoading(true);
    fetchStatus();
  };

  useEffect(fetchStatus, [fetchStatus]);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {}
  };

  const onMessagesChange = useCallback(
    (messages: UIMessage[]) => {
      if (messages.length === 0) return;
      setChats((prev) => {
        const existing = prev.find((c) => c.id === activeId);
        const record: ChatRecord = {
          id: activeId,
          title: existing?.title && existing.title !== "New chat" ? existing.title : titleFrom(messages),
          updatedAt: Date.now(),
          messages,
        };
        const next = [record, ...prev.filter((c) => c.id !== activeId)];
        saveChats(next);
        return next;
      });
    },
    [activeId],
  );

  const startNewChat = () => {
    setActiveId(newId());
    setView("chat");
  };

  const deleteChat = (id: string) => {
    setChats((prev) => {
      const next = prev.filter((c) => c.id !== id);
      saveChats(next);
      return next;
    });
    if (id === activeId) setActiveId(newId());
  };

  const active = chats.find((c) => c.id === activeId);
  const agentOk = (status?.bridge.ok ?? false) && (status?.model.ok ?? false);

  return (
    <div className="flex h-dvh overflow-hidden bg-canvas text-ink">
      <SidebarNav
        view={view}
        onNavigate={setView}
        recents={chats.map((c) => ({ id: c.id, label: c.title }))}
        activeChatId={activeId}
        onNewChat={startNewChat}
        onPick={(id) => {
          setActiveId(id);
          setView("chat");
        }}
        onDelete={deleteChat}
        agentOk={agentOk}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-stack border-b border-line px-page">
          <h1 className="min-w-0 flex-1 truncate text-[14px] font-medium text-ink">
            {view === "agent" ? "Agent" : (active?.title ?? "New chat")}
          </h1>
          <button
            type="button"
            onClick={() => setView("agent")}
            className="flex h-8 items-center gap-stack rounded-control px-2.5 text-[12px] text-ink-2 transition-colors hover:bg-hover-2"
            title="Open the Agent tab"
          >
            <StatusDot ok={status?.bridge.ok} label="Engine" />
            <StatusDot ok={status?.model.ok} label="Model" />
          </button>
        </header>

        {view === "agent" ? (
          <AgentView status={status} loading={statusLoading} onRefresh={refreshStatus} onStartChat={startNewChat} />
        ) : (
          <ChatView
            key={activeId}
            chatId={activeId}
            initialMessages={active?.messages ?? []}
            status={status}
            onMessagesChange={onMessagesChange}
            onOpenAgent={() => setView("agent")}
          />
        )}
      </main>
    </div>
  );
}

function StatusDot({ ok, label }: { ok?: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`size-1.5 rounded-full ${ok === undefined ? "bg-ink-3" : ok ? "bg-green" : "bg-red"}`} />
      {label}
    </span>
  );
}
