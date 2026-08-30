/**
 * Environment status for the header: is the engine up, is the model usable?
 *
 * "Usable" means validated, not merely present. An API key that exists but is
 * rejected, or a model id Groq has retired, both fail at the first message —
 * so both are checked here, before the user types anything.
 */

import { bridgeStatus, BRIDGE_URL } from "@/lib/quant";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DEFAULT_MODEL = "llama-3.3-70b-versatile";

type ModelStatus = {
  id: string;
  provider: "groq";
  /** A key is present AND Groq accepted it AND the model id exists. */
  ok: boolean;
  keyPresent: boolean;
  detail: string;
};

/**
 * Ask Groq whether the key works and the model still exists.
 *
 * Groq retires model ids periodically; catching that here turns a mid-chat
 * failure into a header warning. Cached briefly so typical polling does not
 * add a request per page load.
 */
async function checkModel(): Promise<ModelStatus> {
  const id = process.env.EVE_MODEL || DEFAULT_MODEL;
  const apiKey = process.env.GROQ_API_KEY;
  const base = process.env.GROQ_BASE_URL ?? "https://api.groq.com/openai/v1";

  if (!apiKey) {
    return {
      id,
      provider: "groq",
      ok: false,
      keyPresent: false,
      detail: "GROQ_API_KEY is not set in apps/web/.env.local",
    };
  }

  try {
    const res = await fetch(`${base}/models`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(5000),
      next: { revalidate: 60 },
    });

    if (res.status === 401 || res.status === 403) {
      return {
        id,
        provider: "groq",
        ok: false,
        keyPresent: true,
        detail: "Groq rejected this API key. Replace it in apps/web/.env.local.",
      };
    }
    if (!res.ok) {
      return {
        id,
        provider: "groq",
        ok: false,
        keyPresent: true,
        detail: `Groq returned ${res.status} when listing models.`,
      };
    }

    const body = (await res.json()) as { data?: { id: string }[] };
    const ids = (body.data ?? []).map((m) => m.id);
    // A custom base URL is usually a mock or proxy that may not implement
    // /models faithfully; don't fail the id check on its say-so.
    if (ids.length > 0 && !ids.includes(id) && !process.env.GROQ_BASE_URL) {
      return {
        id,
        provider: "groq",
        ok: false,
        keyPresent: true,
        detail: `Key is valid, but "${id}" is not in this account's model list. Set EVE_MODEL to a current id.`,
      };
    }
    return {
      id,
      provider: "groq",
      ok: true,
      keyPresent: true,
      detail: "Key validated and model available.",
    };
  } catch (err) {
    return {
      id,
      provider: "groq",
      ok: false,
      keyPresent: true,
      detail: `Could not reach Groq: ${
        err instanceof Error ? err.message : String(err)
      }`,
    };
  }
}

export async function GET() {
  const [bridge, model] = await Promise.all([bridgeStatus(), checkModel()]);

  let months: Record<string, Record<string, number>> = {};
  if (bridge.ok) {
    try {
      const res = await fetch(`${BRIDGE_URL}/tools/list_research_months`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        const body = (await res.json()) as {
          result?: { months?: Record<string, Record<string, number>> };
        };
        months = body.result?.months ?? {};
      }
    } catch {
      // A month listing is a nicety; the header still renders without it.
    }
  }

  // Note: the key itself is never returned — only whether it works.
  return Response.json({ bridge: { url: BRIDGE_URL, ...bridge }, model, months });
}
