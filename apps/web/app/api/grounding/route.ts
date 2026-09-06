/**
 * Grounding check for a completed answer.
 *
 * The client already holds both halves — the assistant's text and the tool
 * outputs it rendered — so the check runs after the turn rather than inside
 * the stream. That keeps the streaming path untouched and makes the whole
 * thing verifiable with curl.
 */

import { checkGrounding } from "@/lib/quant";

export const runtime = "nodejs";

export async function POST(req: Request) {
  let answer: string;
  let toolResults: unknown[];
  try {
    const body = (await req.json()) as {
      answer?: unknown;
      toolResults?: unknown;
    };
    if (typeof body.answer !== "string") {
      return Response.json(
        { error: "'answer' must be a string" },
        { status: 400 },
      );
    }
    answer = body.answer;
    toolResults = Array.isArray(body.toolResults) ? body.toolResults : [];
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 });
  }

  try {
    return Response.json(await checkGrounding(answer, toolResults));
  } catch (err) {
    return Response.json(
      {
        error:
          err instanceof Error ? err.message : "grounding check unavailable",
      },
      { status: 503 },
    );
  }
}
