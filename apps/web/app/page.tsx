"use client";

import dynamic from "next/dynamic";

// The shell reads chat history and the theme from localStorage, so it renders
// on the client only; the server sends the empty canvas.
const AppShell = dynamic(() => import("@/components/shell/AppShell"), {
  ssr: false,
  loading: () => <div className="h-dvh bg-canvas" />,
});

export default function Home() {
  return <AppShell />;
}
