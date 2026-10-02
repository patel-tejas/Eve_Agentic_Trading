/** Shapes shared by the client views. Server-only types live in `lib/quant.ts`. */

import type { UIMessage } from "ai";

export type GroundingReport = {
  grounded: boolean;
  total_claims: number;
  grounded_claims: number;
  ungrounded_claims: number;
  summary: string;
  ungrounded: { text: string; line: number; context: string }[];
};

export type Status = {
  bridge: { url: string; ok: boolean; tools?: number; error?: string };
  model: {
    id: string;
    provider: string;
    ok: boolean;
    keyPresent: boolean;
    detail: string;
  };
  months: Record<string, Record<string, number>>;
  /** Tool names and descriptions from the bridge manifest; empty when it is down. */
  tools?: { name: string; description: string }[];
};

/** One saved conversation in the sidebar history (kept in localStorage). */
export type ChatRecord = {
  id: string;
  title: string;
  updatedAt: number;
  messages: UIMessage[];
};

/** Strategy defaults the system prompt pins (see app/api/chat/route.ts). */
export const STRATEGY_DEFAULTS: { label: string; value: string }[] = [
  { label: "Fast EMA", value: "9" },
  { label: "Slow EMA", value: "15" },
  { label: "Angle threshold", value: "30.0°" },
  { label: "Angle lookback", value: "1" },
  { label: "Signal mode", value: "crossover_and_angle" },
];
