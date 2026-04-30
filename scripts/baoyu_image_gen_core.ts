import path from "node:path";
import { homedir } from "node:os";
import { readFile } from "node:fs/promises";

export type Provider = "openai" | "gemini-proxy";
export type Quality = "normal" | "2k";

export type CliArgs = {
  prompt: string | null;
  promptFiles: string[];
  imagePath: string | null;
  provider: Provider | null;
  model: string | null;
  aspectRatio: string | null;
  size: string | null;
  quality: Quality;
  referenceImages: string[];
  n: number;
  json: boolean;
  help: boolean;
};

type OpenAIImageResult = {
  data?: Array<{ url?: string; b64_json?: string }>;
};

type ChatCompletionResult = {
  choices?: Array<{
    message?: {
      content?: unknown;
      images?: Array<{ url?: string; b64_json?: string; b64?: string }>;
      image_url?: { url?: string };
    };
  }>;
  candidates?: Array<{
    content?: {
      parts?: Array<{
        inlineData?: { data?: string };
        text?: string;
      }>;
    };
  }>;
};

export async function loadEnv(): Promise<void> {
  const cwd = process.cwd();
  const home = homedir();
  const envFiles = [
    path.join(home, ".wechat-publisher", "image-gen.env"),
    path.join(cwd, ".image-gen.env"),
    path.join(cwd, ".env"),
  ];

  for (const file of envFiles) {
    const entries = await loadEnvFile(file);
    for (const [key, value] of Object.entries(entries)) {
      if (!process.env[key]) process.env[key] = value;
    }
  }
}

async function loadEnvFile(filePath: string): Promise<Record<string, string>> {
  try {
    const content = await readFile(filePath, "utf8");
    const env: Record<string, string> = {};

    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq < 0) continue;
      const key = trimmed.slice(0, eq).trim();
      let value = trimmed.slice(eq + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      env[key] = value;
    }

    return env;
  } catch {
    return {};
  }
}

export function detectProvider(args: CliArgs): Provider {
  if (args.provider) return args.provider;
  if (process.env.GEMINI_PROXY_API_KEY) return "gemini-proxy";
  if (process.env.OPENAI_API_KEY) return "openai";
  throw new Error(
    "No image provider configured. Set GEMINI_PROXY_API_KEY or OPENAI_API_KEY."
  );
}

export function getDefaultModel(provider: Provider): string {
  if (provider === "gemini-proxy") {
    return process.env.GEMINI_PROXY_IMAGE_MODEL || "gemini-2.5-flash";
  }
  return process.env.OPENAI_IMAGE_MODEL || "gpt-image-1";
}

export async function buildPrompt(args: CliArgs): Promise<string> {
  if (args.prompt) return args.prompt;
  if (args.promptFiles.length > 0) {
    const parts: string[] = [];
    for (const file of args.promptFiles) {
      parts.push(await readFile(file, "utf8"));
    }
    return parts.join("\n\n").trim();
  }

  if (!process.stdin.isTTY) {
    try {
      const stdin = await Bun.stdin.text();
      if (stdin.trim()) return stdin.trim();
    } catch {}
  }

  throw new Error("Prompt is required.");
}

export function normalizeOutputImagePath(filePath: string): string {
  const full = path.resolve(filePath);
  return path.extname(full) ? full : `${full}.png`;
}

export async function generateImage(
  provider: Provider,
  model: string,
  prompt: string,
  args: CliArgs
): Promise<Uint8Array> {
  if (provider === "gemini-proxy") {
    return generateWithGeminiProxy(prompt, model, args);
  }
  return generateWithOpenAI(prompt, model, args);
}

async function generateWithOpenAI(
  prompt: string,
  model: string,
  args: CliArgs
): Promise<Uint8Array> {
  const baseURL = (process.env.OPENAI_BASE_URL || "https://api.openai.com/v1").replace(/\/$/, "");
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) throw new Error("OPENAI_API_KEY is required");

  const body: Record<string, unknown> = {
    model,
    prompt: applyPromptHints(prompt, args),
    size: args.size || getOpenAISize(args.aspectRatio, args.quality),
    n: args.n,
  };

  const res = await fetch(`${baseURL}/images/generations`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    throw new Error(`OpenAI image API error: ${await res.text()}`);
  }

  return extractImageBytes(await res.json() as OpenAIImageResult);
}

async function generateWithGeminiProxy(
  prompt: string,
  model: string,
  args: CliArgs
): Promise<Uint8Array> {
  const baseURL = normalizeGeminiProxyBaseUrl(process.env.GEMINI_PROXY_BASE_URL);
  const apiKey = process.env.GEMINI_PROXY_API_KEY;
  if (!baseURL) throw new Error("GEMINI_PROXY_BASE_URL is required");
  if (!apiKey) throw new Error("GEMINI_PROXY_API_KEY is required");

  const content: Array<Record<string, unknown>> = [];
  for (const file of args.referenceImages) {
    const { dataUrl } = await readImageAsDataUrl(file);
    content.push({ type: "image_url", image_url: { url: dataUrl } });
  }
  content.push({
    type: "text",
    text: buildGeminiProxyPrompt(prompt, args),
  });

  const body = {
    model,
    messages: [{ role: "user", content }],
  };

  const res = await fetch(`${baseURL}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    throw new Error(`Gemini proxy API error: ${await res.text()}`);
  }

  return extractImageBytes(await res.json() as ChatCompletionResult);
}

function normalizeGeminiProxyBaseUrl(raw: string | undefined): string | null {
  const trimmed = raw?.trim();
  if (!trimmed) return null;
  const withoutSlash = trimmed.replace(/\/+$/, "");
  return withoutSlash.endsWith("/v1") ? withoutSlash : `${withoutSlash}/v1`;
}

function buildGeminiProxyPrompt(prompt: string, args: CliArgs): string {
  const parts = [
    "Generate exactly one image.",
    "Return image data directly if the proxy supports it.",
    "Preferred response order: base64 image, image URL, then nothing else.",
    applyPromptHints(prompt, args),
  ];
  return parts.join("\n");
}

function applyPromptHints(prompt: string, args: CliArgs): string {
  let result = prompt.trim();
  if (args.aspectRatio) result += `\nAspect ratio: ${args.aspectRatio}.`;
  if (args.quality === "2k") result += "\nHigh resolution target: 2048px.";
  if (args.size) result += `\nTarget size: ${args.size}.`;
  return result;
}

function getOpenAISize(aspectRatio: string | null, quality: Quality): string {
  const base = quality === "2k" ? 2048 : 1024;
  if (!aspectRatio) return `${base}x${base}`;
  if (aspectRatio === "16:9") return quality === "2k" ? "2048x1024" : "1792x1024";
  if (aspectRatio === "9:16") return quality === "2k" ? "1024x2048" : "1024x1792";
  return `${base}x${base}`;
}

async function readImageAsDataUrl(filePath: string): Promise<{ dataUrl: string }> {
  const bytes = await readFile(filePath);
  const ext = path.extname(filePath).toLowerCase();
  const mime =
    ext === ".jpg" || ext === ".jpeg" ? "image/jpeg" :
    ext === ".webp" ? "image/webp" :
    ext === ".gif" ? "image/gif" :
    "image/png";
  return { dataUrl: `data:${mime};base64,${bytes.toString("base64")}` };
}

function extractImageBytes(payload: unknown): Promise<Uint8Array> {
  const direct = extractInlineImage(payload);
  if (direct) return Promise.resolve(direct);

  const url = extractImageUrl(payload);
  if (url) return downloadImage(url);

  throw new Error("Cannot extract image data from response.");
}

function extractInlineImage(payload: unknown): Uint8Array | null {
  const dataUrl = findString(payload, (value) => value.startsWith("data:image/"));
  const base64Value = dataUrl ?? findString(payload, (value) => isLikelyImageBase64(value));
  if (!base64Value) return null;
  const raw = base64Value.startsWith("data:image/")
    ? base64Value.slice(base64Value.indexOf(",") + 1)
    : base64Value;
  return Uint8Array.from(Buffer.from(raw, "base64"));
}

function extractImageUrl(payload: unknown): string | null {
  return findString(payload, (value) =>
    value.startsWith("https://") &&
    (value.includes(".png") || value.includes(".jpg") || value.includes(".jpeg") || value.includes(".webp") || value.includes("image"))
  );
}

function findString(value: unknown, match: (text: string) => boolean): string | null {
  if (typeof value === "string") return match(value) ? value : null;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findString(item, match);
      if (found) return found;
    }
    return null;
  }
  if (value && typeof value === "object") {
    for (const child of Object.values(value as Record<string, unknown>)) {
      const found = findString(child, match);
      if (found) return found;
    }
  }
  return null;
}

function isLikelyImageBase64(value: string): boolean {
  if (value.length < 256) return false;
  if (value.length % 4 !== 0) return false;
  if (!/^[A-Za-z0-9+/=\r\n]+$/.test(value)) return false;
  const prefix = Buffer.from(value.slice(0, 64), "base64");
  return (
    prefix.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff])) ||
    prefix.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) ||
    prefix.subarray(0, 4).toString("ascii") === "RIFF"
  );
}

async function downloadImage(url: string): Promise<Uint8Array> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to download image from ${url}`);
  }
  return new Uint8Array(await res.arrayBuffer());
}
