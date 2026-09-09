export type Kind = "prd" | "design" | "rfc";
export type SourceMode = "brief" | "prd" | "design" | "prd_design";
export const kinds: Kind[] = ["prd", "design", "rfc"];
export const labels: Record<Kind, string> = { prd: "PRD", design: "Design spec", rfc: "RFC" };
export type Item = { id: string; statement: string; verification: string; references: string[] };
export type Section = { id: string; title: string; body: string; items: Item[]; source_ids: string[]; protected: boolean; needs_review: boolean; unverified_source_ids?: string[] };
export type Source = { id: string; label: string; sha256: string; truncated: boolean; text: string };
export type Version = { id: string; number: number; created_at: string; author: string; summary: string; pins: Partial<Record<Kind, string>> };
export type Snapshot = Version & {
  source_mode?: SourceMode;
  kind: Kind; parent_id: string | null; sections: Section[]; assumptions: string[];
  questions: { id: string; question: string; why: string; blocking: boolean }[];
  coverage: { module: string; status: "material" | "not_material" | "unresolved"; rationale: string }[];
  sources: Source[]; model: string; protected_sections_kept: string[];
};
export type PublicationReview = {
  id: "success" | "open_questions"; title: string; sections: {id: string; title: string}[];
  findings: {location: string; anchor: string; excerpt: string}[]; requires_deferral: boolean; legacy_published?: boolean;
  acknowledgement: {version_id: string; disposition: "confirmed" | "deferred"; note: string; created_at: string} | null;
};
export type Document = { head: string | null; published: string | null; versions: Version[]; snapshot: Snapshot | null; stale: Kind[]; published_stale?: Kind[]; blockers: string[]; publication_review?: PublicationReview[] };
export type Operation = { created_at?: string; started_at?: string; timeout_seconds?: number; id: string; kind: Kind; action?: string; status: "queued" | "running" | "completed" | "failed" | "interrupted" | "cancelled"; text: string; error: string | null; version_id: string | null };
export type ClarificationAnswer = { choice: "option-1" | "option-2" | "option-3" | "custom"; text: string; saved_at: string };
export type ClarificationQuestion = { id: string; question: string; why: string; options: {label: string; description: string}[] };
export type Intake = { status: "checking" | "awaiting_answers" | "ready"; summary: string; questions: ClarificationQuestion[]; answers: Record<string, ClarificationAnswer>; pins?: Partial<Record<Kind, string>> };
export type Comment = { id: string; kind: Kind; section_id: string; version_id: string; text: string; quote: string; blocking: boolean; status: "open" | "addressed" | "resolved" | "dismissed"; outdated: boolean; addressed_version: string | null; dispositions: {status: string; reason: string}[] };
export type Feature = {
  id: string; title: string; brief: string; context: string; revision: number; updated_at: string;
  documents: Record<Kind, Document>; operations: Operation[]; comments: Comment[];
  intake?: Intake;
  initial_kind?: Kind; intakes?: Partial<Record<Kind, Intake>>;
  messages: { id: string; role: string; kind: Kind; text: string; section_id: string | null; operation_id: string; version_id?: string }[];
};
export type Command = { action: string; kind?: Kind; text?: string; section_id?: string; version_id?: string; comment_id?: string; quote?: string; blocking?: boolean; items?: Item[]; question_id?: string; choice?: ClarificationAnswer["choice"]; review_group?: PublicationReview["id"]; disposition?: "confirmed" | "deferred"; source_mode?: SourceMode };
export const intakeFor = (feature: Feature, kind: Kind) => feature.intakes?.[kind] || (kind === "prd" ? feature.intake : undefined);
