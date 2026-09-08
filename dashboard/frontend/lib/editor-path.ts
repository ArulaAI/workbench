/** Convert absolute or project-relative paths to the editor API's specs/... form. */
export function toRelativeSpecPath(path: string): string {
  const idx = path.indexOf("specs/");
  return idx >= 0 ? path.slice(idx) : path;
}

/** Read and validate an editor deep link without allowing paths outside specs/. */
export function editorPathFromSearch(search: string): string | null {
  const requested = new URLSearchParams(search).get("path");
  if (!requested) return null;
  const path = toRelativeSpecPath(requested).replace(/^\/+/, "");
  if (!path.startsWith("specs/") || !path.endsWith(".md") || path.includes("..")) {
    return null;
  }
  return path;
}

export function specTypeForPath(path: string): string {
  if (path.includes("/tech/") || path.endsWith("/rfc.md")) return "rfc";
  if (path.includes("/design/") || path.endsWith("/design.md")) return "dsn";
  if (path.includes("/defects/")) return "defect";
  return "prd";
}
