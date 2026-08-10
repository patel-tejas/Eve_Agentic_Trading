import { groq } from "@ai-sdk/groq";
import { defineAgent } from "eve";

/**
 * Eve: the quant research agent for the AI Quant Trading Platform.
 * All numbers come from the quant engine via the `quant` MCP connection —
 * this agent orchestrates tool calls, it never computes.
 */
export default defineAgent({
  model: groq(process.env.EVE_MODEL ?? "llama-3.3-70b-versatile"),
});