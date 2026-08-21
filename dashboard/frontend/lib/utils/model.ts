/**
 * Model display utilities.
 *
 * Model IDs arrive in two formats:
 * - Bare names from JSONL ingestion (no provider prefix, no version date)
 * - Provider-prefixed from discovery: "provider/model-name"
 * Both formats are handled.
 */

// Design system palette from globals.css — no model-specific mapping.
const PALETTE = [
  "#8b5cf6", // --color-violet
  "#00d4aa", // --color-accent
  "#4ba6ee", // --color-blue
  "#44cc77", // --color-emerald
  "#f0b232", // --color-amber
  "#ff6699", // --color-rose
  "#44ddee", // --color-cyan
];

export function getModelColor(id: string): string {
  // Stable hash -> palette index. Same model always gets the same color.
  let h = 0;
  for (let i = 0; i < id.length; i++)
    h = ((h << 5) - h + id.charCodeAt(i)) | 0;
  return PALETTE[((h % PALETTE.length) + PALETTE.length) % PALETTE.length];
}

export function shortModel(model: string): string {
  // Strip provider prefix: "anthropic/claude-opus-4-6" -> "claude-opus-4-6"
  const stripped = model.includes("/") ? model.split("/").pop()! : model;
  // Strip ollama tag: "mistral:latest" -> "mistral"
  return stripped.split(":")[0] || model;
}
