export type Kind = "prd" | "design" | "rfc";
export const kinds: Kind[] = ["prd", "design", "rfc"];
export const labels: Record<Kind, string> = { prd: "PRD", design: "Design spec", rfc: "RFC" };
export type Item = { id: string; statement: string; verification: string; references: string[] };
export type Section = { id: string; title: string; body: string; items: Item[]; source_ids: string[]; protected: boolean; needs_review: boolean; unverified_source_ids?: string[] };
export type Source = { id: string; label: string; sha256: string; truncated: boolean; text: string };
export type Version = { id: string; number: number; created_at: string; author: string; summary: string; pins: Partial<Record<Kind, string>> };
export type Snapshot = Version & {
  kind: Kind; parent_id: string | null; sections: Section[]; assumptions: string[];
  questions: { id: string; question: string; why: string; blocking: boolean }[];
  coverage: { module: string; status: "material" | "not_material" | "unresolved"; rationale: string }[];
  sources: Source[]; model: string; protected_sections_kept: string[];
};
export type Document = { head: string | null; published: string | null; versions: Version[]; snapshot: Snapshot | null; stale: Kind[]; blockers: string[] };
export type Operation = { id: string; kind: Kind; status: "queued" | "running" | "completed" | "failed" | "interrupted" | "cancelled"; text: string; error: string | null; version_id: string | null };
export type Comment = { id: string; kind: Kind; section_id: string; version_id: string; text: string; quote: string; blocking: boolean; status: "open" | "addressed" | "resolved" | "dismissed"; outdated: boolean; addressed_version: string | null; dispositions: {status: string; reason: string}[] };
export type Feature = {
  id: string; title: string; brief: string; context: string; revision: number; updated_at: string;
  documents: Record<Kind, Document>; operations: Operation[]; comments: Comment[];
  messages: { id: string; role: string; kind: Kind; text: string; section_id: string | null; operation_id: string; version_id?: string }[];
};
export type Command = { action: string; kind?: Kind; text?: string; section_id?: string; version_id?: string; comment_id?: string; quote?: string; blocking?: boolean; items?: Item[] };
