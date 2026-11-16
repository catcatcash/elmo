import { z } from "zod";
import type {
	Provider,
	ProviderOptions,
	ScrapeResult,
	StructuredResearchOptions,
	StructuredResearchResult,
} from "../types";
import { parseSchemaJson } from "./ai-sdk";

const MODEL_VERSION = "gpt-6-luna";

function unwrap(content: string): string {
	const trimmed = content.trim();
	const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
	return (fenced ? fenced[1] : trimmed).trim();
}

async function callCodex(prompt: string, schema?: Record<string, unknown>, model?: string): Promise<string> {
	const url = process.env.CODEX_BRIDGE_URL?.trim();
	const token = process.env.CODEX_BRIDGE_TOKEN?.trim();
	if (!url || !token) throw new Error("Codex CLI bridge is not configured");
	const body: { prompt: string; schema?: Record<string, unknown>; model?: string } = { prompt };
	if (schema) body.schema = schema;
	if (model) body.model = model;
	const res = await fetch(url, {
		method: "POST",
		headers: {
			Authorization: `Bearer ${token}`,
			"Content-Type": "application/json",
		},
		body: JSON.stringify(body),
		signal: AbortSignal.timeout(300_000),
	});
	const data = (await res.json()) as { ok?: boolean; text?: string; error?: string };
	if (!res.ok || !data.ok || typeof data.text !== "string") {
		throw new Error(`Codex CLI failed (${res.status}): ${data.error ?? "no output"}`);
	}
	return data.text;
}

export const codexCli: Provider = {
	id: "codex-cli",
	name: "Codex CLI",
	access: "api",
	docsAnchor: "direct-model-apis",

	isConfigured: () => Boolean(process.env.CODEX_BRIDGE_URL?.trim() && process.env.CODEX_BRIDGE_TOKEN?.trim()),

	async run(_model: string, prompt: string, options?: ProviderOptions): Promise<ScrapeResult> {
		const text = await callCodex(prompt, undefined, options?.version ?? MODEL_VERSION);
		return {
			rawOutput: {
				output: [{ type: "message", content: [{ type: "output_text", text, annotations: [] }] }],
			},
			webQueries: [],
			modelVersion: options?.version ?? MODEL_VERSION,
		};
	},

	async runStructuredResearch<T>({
		prompt,
		schema,
	}: StructuredResearchOptions<T>): Promise<StructuredResearchResult<T>> {
		const jsonSchema = z.toJSONSchema(schema) as Record<string, unknown>;
		const text = await callCodex(prompt, jsonSchema, MODEL_VERSION);
		return {
			object: parseSchemaJson(schema, unwrap(text)),
			modelVersion: MODEL_VERSION,
		};
	},
};
