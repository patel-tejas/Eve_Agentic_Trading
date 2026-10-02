"use client";

import { useRef, useState, type ReactNode } from "react";

/* ─────────────────────────────────────────────────────────
 * GLIDE MENU — one highlight that slides to the hovered row
 * instead of each row toggling its own background. Rows opt
 * in with a data attribute (default `[data-row]`).
 * ───────────────────────────────────────────────────────── */

export default function GlideMenu({
  children,
  className = "",
  highlightClassName = "rounded-[8px] bg-hover-2",
  rowSelector = "[data-row], [data-menu-row]",
}: {
  children: ReactNode;
  className?: string;
  highlightClassName?: string;
  rowSelector?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ top: number; left: number; width: number; height: number } | null>(null);
  const [visible, setVisible] = useState(false);

  const track = (target: EventTarget | null) => {
    const root = ref.current;
    if (!root || !(target instanceof Element)) return;
    const row = target.closest(rowSelector) as HTMLElement | null;
    if (!row || !root.contains(row)) {
      setVisible(false);
      return;
    }
    const rootRect = root.getBoundingClientRect();
    const rect = row.getBoundingClientRect();
    setBox({
      top: rect.top - rootRect.top,
      left: rect.left - rootRect.left,
      width: rect.width,
      height: rect.height,
    });
    setVisible(true);
  };

  return (
    <div
      ref={ref}
      className={`relative ${className}`}
      onPointerOver={(event) => track(event.target)}
      onPointerLeave={() => setVisible(false)}
    >
      <span
        aria-hidden
        className={`pointer-events-none absolute ${highlightClassName}`}
        style={{
          top: box?.top ?? 0,
          left: box?.left ?? 0,
          width: box?.width ?? 0,
          height: box?.height ?? 0,
          opacity: visible && box ? 1 : 0,
          transition: box
            ? "top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), width 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease"
            : "opacity 150ms ease",
        }}
      />
      {children}
    </div>
  );
}
