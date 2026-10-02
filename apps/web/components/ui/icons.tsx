/* ─────────────────────────────────────────────────────────
 * ICONS — one stroke style for the whole app (24px grid,
 * round caps, currentColor) so nothing pulls in a second
 * icon family.
 * ───────────────────────────────────────────────────────── */

import type { ReactNode } from "react";

export function Icon({
  children,
  size = 16,
  strokeWidth = 1.8,
  className,
}: {
  children: ReactNode;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {children}
    </svg>
  );
}

type P = { size?: number; className?: string; strokeWidth?: number };

export const IconEdit = (p: P) => (
  <Icon {...p}>
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
  </Icon>
);
export const IconChat = (p: P) => (
  <Icon {...p}>
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12Z" />
  </Icon>
);
export const IconSpark = (p: P) => (
  <Icon {...p}>
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
  </Icon>
);
export const IconSearch = (p: P) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Icon>
);
export const IconX = (p: P) => (
  <Icon {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Icon>
);
export const IconChevronDown = (p: P) => (
  <Icon {...p}>
    <path d="m6 9 6 6 6-6" />
  </Icon>
);
export const IconChevronRight = (p: P) => (
  <Icon {...p}>
    <path d="m9 6 6 6-6 6" />
  </Icon>
);
export const IconSidebar = (p: P) => (
  <Icon {...p}>
    <rect x="3" y="4" width="18" height="16" rx="3" />
    <path d="M9 4v16" />
  </Icon>
);
export const IconPlus = (p: P) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);
export const IconArrowUp = (p: P) => (
  <Icon {...p}>
    <path d="M12 19V5M5 12l7-7 7 7" />
  </Icon>
);
export const IconStop = (p: P) => (
  <svg width={p.size ?? 12} height={p.size ?? 12} viewBox="0 0 24 24" aria-hidden="true" className={p.className}>
    <rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor" />
  </svg>
);
export const IconCopy = (p: P) => (
  <Icon {...p}>
    <rect x="9" y="9" width="12" height="12" rx="2.5" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </Icon>
);
export const IconCheck = (p: P) => (
  <Icon {...p}>
    <path d="M20 6 9 17l-5-5" />
  </Icon>
);
export const IconRetry = (p: P) => (
  <Icon {...p}>
    <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
  </Icon>
);
export const IconReply = (p: P) => (
  <Icon {...p}>
    <path d="M9 10l-5 5 5 5" />
    <path d="M20 4v7a4 4 0 0 1-4 4H4" />
  </Icon>
);
export const IconCalendar = (p: P) => (
  <Icon {...p}>
    <rect x="3" y="5" width="18" height="16" rx="3" />
    <path d="M3 10h18M8 3v4M16 3v4" />
  </Icon>
);
export const IconChart = (p: P) => (
  <Icon {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </Icon>
);
export const IconTool = (p: P) => (
  <Icon {...p}>
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4Z" />
  </Icon>
);
export const IconShield = (p: P) => (
  <Icon {...p}>
    <path d="M12 3 4 6v6c0 4.4 3.4 8.3 8 9 4.6-.7 8-4.6 8-9V6Z" />
    <path d="m9 12 2 2 4-4" />
  </Icon>
);
export const IconSun = (p: P) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Icon>
);
export const IconMoon = (p: P) => (
  <Icon {...p}>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
  </Icon>
);
export const IconTrash = (p: P) => (
  <Icon {...p}>
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />
  </Icon>
);

/** Eve's mark: a candle inside a rounded square. */
export const EveMark = ({ size = 20 }: { size?: number }) => (
  <span
    className="flex shrink-0 items-center justify-center rounded-[7px] bg-ink text-surface"
    style={{ width: size, height: size }}
    aria-hidden="true"
  >
    <svg width={size * 0.6} height={size * 0.6} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
      <path d="M7 4v16M17 6v12" />
      <rect x="4.5" y="8" width="5" height="7" rx="1" fill="currentColor" stroke="none" />
      <rect x="14.5" y="10" width="5" height="5" rx="1" />
    </svg>
  </span>
);
