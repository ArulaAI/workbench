const graphql = process.env.NEXT_PUBLIC_GRAPHQL_URL || "http://127.0.0.1:4440/graphql";
export const studioUrl = process.env.NEXT_PUBLIC_STUDIO_URL || graphql.replace(/\/graphql\/?$/, "/studio");

export class StudioAPIError extends Error {
  constructor(message: string, public status: number) {super(message);}
}

export async function api<T>(path: string, body?: unknown, signal?: AbortSignal, method?: "DELETE"): Promise<T> {
  const response = await fetch(studioUrl + path, {
    method: method || (body === undefined ? "GET" : "POST"), signal,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok) {
    const detail = result.detail;
    throw new StudioAPIError(typeof detail === "string" ? detail : Array.isArray(detail)
      ? detail.map((d: { msg: string }) => d.msg).join("; ") : "The workspace could not be saved.", response.status);
  }
  return result as T;
}
