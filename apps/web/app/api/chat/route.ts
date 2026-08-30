/**
 * Chat endpoint: Groq drives a tool loop over the deterministic quant engine.
 *
 * The model never computes a number. Every figure in an answer comes from a
 * tool result produced by `quant/` — that is the repo's stated architecture
 * principle, and the system prompt below makes it an explicit instruction.
 */

import { createGroq } from "@ai-sdk/groq";
import { convertToModelMessages, stepCountIs, streamText, type UIMessage } from "ai";

import { buildTools, fetchManifest, WRITE_TOOLS } from "@/lib/quant";

// The tool loop calls a local Python service; keep it on Node, not Edge.
export const runtime = "nodejs";
export const maxDuration = 300;

const DEFAULT_MODEL = "llama-3.3-70b-versatile";

const SYSTEM_PROMPT = `You are Eve, the research assistant for an AI quant trading platform that studies NIFTY index futures (Indian equity derivatives) with an EMA crossover + angle strategy.

THE ONE RULE: you orchestrate, the Python engine calculates.
- NEVER compute, estimate, or infer a P&L, return, Sharpe, win rate, drawdown or any other figure yourself.
- Every number you state must come from a tool result in THIS conversation. If you have not called a tool, you do not know the answer — call one.
- If a tool fails, say what failed and why. Never fill the gap with a plausible-looking number.

DATA
- Processed months live on disk. Call list_research_months first when you don't know what is available.
- Timeframes are "1m", "5m", "15m". Months are "YYYY-MM" strings.
- Amounts are Indian rupees. Write them as ₹41,200 (Indian digit grouping is fine).

STRATEGY DEFAULTS (phase 04)
- fast_ema 9, slow_ema 15, angle_threshold 30.0, angle_lookback 1, signal_mode "crossover_and_angle".
- Use these unless the user asks for something else. Say which parameters you used.

SIDE EFFECTS — ask first
- ${WRITE_TOOLS.join(" and ")} change state (${WRITE_TOOLS[0]} calls the broker API, ${WRITE_TOOLS[1]} writes parquet files).
- Describe what you are about to do and get explicit confirmation before calling either. Everything else is read-only; just call it.

COST
- parameter_search and walk_forward_test sweep a grid and get slow on 1m data (8,000+ bars). Prefer 15m for exploration, or narrow the grid with the fast_emas / slow_emas / angle_thresholds / angle_lookbacks arguments.

STYLE
- Lead with the answer, then the evidence. Short paragraphs or a compact markdown table.
- Always state the month, timeframe and parameters a result came from — a number without its window is not a result.
- This is research, not investment advice. Do not recommend trades.`;

function errorResponse(message: string, hint: string, status = 500) {
  return new Response(JSON.stringify({ error: message, hint }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export async function POST(req: Request) {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) {
    return errorResponse(
      "GROQ_API_KEY is not set.",
      "Add it to apps/web/.env.local and restart `npm run dev`. Get a key at https://console.groq.com/keys",
      503,
    );
  }

  let messages: UIMessage[];
  try {
    ({ messages } = (await req.json()) as { messages: UIMessage[] });
  } catch {
    return errorResponse("Request body was not valid JSON.", "", 400);
  }

  // Fetched per request so a tool added in Python shows up on the next turn
  // without restarting Next. It is a localhost call on a tiny payload.
  let tools;
  try {
    tools = buildTools(await fetchManifest());
  } catch (err) {
    return errorResponse(
      err instanceof Error ? err.message : "Quant bridge unreachable.",
      "Start the engine: uv run python -m mcp.quant_server.http_bridge",
      503,
    );
  }

  // GROQ_BASE_URL lets a corporate proxy -- or a local mock during testing --
  // stand in for api.groq.com without touching this file.
  const groq = createGroq({
    apiKey,
    ...(process.env.GROQ_BASE_URL ? { baseURL: process.env.GROQ_BASE_URL } : {}),
  });
  const model = process.env.EVE_MODEL || DEFAULT_MODEL;

  const result = streamText({
    model: groq(model),
    system: SYSTEM_PROMPT,
    messages: await convertToModelMessages(messages),
    tools,
    // Without a multi-step stop condition the run ends at the first tool call
    // and the user sees raw JSON instead of an answer. 12 leaves room for a
    // list -> inspect -> backtest -> compare chain.
    stopWhen: stepCountIs(12),
    temperature: 0.2,
  });

  return result.toUIMessageStreamResponse({
    onError: (error) => {
      // Surfaced in the UI, so make it actionable rather than "[object Object]".
      const message = error instanceof Error ? error.message : String(error);
      if (/api key|unauthorized|401|invalid_api_key/i.test(message)) {
        return "Groq rejected the API key. Check GROQ_API_KEY in apps/web/.env.local.";
      }
      if (/model|404|does not exist|decommission/i.test(message)) {
        return `Groq rejected the model "${model}". Set EVE_MODEL in apps/web/.env.local to a current model id.`;
      }
      return message;
    },
  });
}
