import { gql } from "urql";

// ── Ceremony lifecycle ──────────────────────────────────────────

export type CeremonyStatus =
  | "DRAFTING"
  | "COMMITTED"
  | "RATIFIED"
  | "REJECTED"
  | "ABANDONED";

export interface RevisionSummary {
  revisionId: string;
  parentId: string | null;
  status: CeremonyStatus;
  specContentHash: string;
  contextPackageHash: string;
  validationHash: string;
  createdAt: string;
  reason: string | null;
}

export interface CeremonyInfo {
  featureName: string;
  currentRevision: RevisionSummary;
  revisionCount: number;
  author: string;
  authorEmail: string;
  createdAt: string;
  isMultiplayer: boolean;
}

// ── Intent ──────────────────────────────────────────────────────

export interface Intent {
  text: string;
  author: string;
  authorEmail: string;
  createdAt: string;
  featureName: string;
}

// ── Context package ─────────────────────────────────────────────

export interface CodebaseItem {
  path: string;
  description: string;
  nodeIds: string[];
}

export interface LearningItem {
  text: string;
  sourceFeature: string;
  confidence: string;
}

export interface DefectItem {
  name: string;
  severity: string;
  status: string;
  relatedFiles: string[];
}

export interface KnowledgeItem {
  text: string;
  confidence: string;
  source: string;
}

export interface RelatedFeature {
  name: string;
  state: string;
  overlapFiles: string[];
}

export interface AuditHistoryItem {
  featureName: string;
  finding: string;
  severity: string;
  section: string;
}

export interface ContextPackage {
  intent: string;
  featureName: string;
  scopedArea: string[];
  codebase: CodebaseItem[];
  learnings: LearningItem[];
  defects: DefectItem[];
  projectKnowledge: KnowledgeItem[];
  visionStatus: string;
  visionContent: string | null;
  relatedFeatures: RelatedFeature[];
  auditHistory: AuditHistoryItem[];
  assembledAt: string;
  sourcesStatus: Record<string, string>;
}

// ── Validation ──────────────────────────────────────────────────

export interface ValidationIssue {
  id: string;
  dimension: string;
  severity: string;
  message: string;
  section: string | null;
  line: number | null;
  crossRefSpec: string | null;
  crossRefSection: string | null;
}

export interface ValidationDimension {
  name: string;
  status: string;
  issues: ValidationIssue[];
  checkedAt: string | null;
  tier: number;
}

export interface ValidationState {
  dimensions: ValidationDimension[];
  passCount: number;
  warnCount: number;
  failCount: number;
}

// ── Spec draft ──────────────────────────────────────────────────

export interface SpecDraft {
  featureName: string;
  specType: string;
  content: string;
  filePath: string;
  templateName: string;
  generatedAt: string | null;
  childSpecs: SpecDraft[];
}

// ── Suggestions ─────────────────────────────────────────────────

export interface SuggestionResolution {
  action: string;
  resolvedBy: string;
  resolvedByEmail: string;
  resolvedAt: string;
  reason: string | null;
}

export interface SuggestionReply {
  id: string;
  author: string;
  authorEmail: string;
  text: string;
  createdAt: string;
}

export interface Suggestion {
  id: string;
  author: string;
  authorEmail: string;
  revisionId: string;
  sectionId: string;
  sectionTitle: string;
  sectionContentHash: string;
  text: string;
  status: string;
  outdated: boolean;
  createdAt: string;
  updatedAt: string | null;
  resolution: SuggestionResolution | null;
  thread: SuggestionReply[];
}

export interface DismissedSummary {
  count: number;
  reasons: string[];
}

export interface SuggestionHistory {
  received: number;
  accepted: number;
  dismissed: DismissedSummary;
}

// ── Commit & ratification ───────────────────────────────────────

export interface CommitRecord {
  featureName: string;
  specType: string;
  revisionId: string;
  claimant: string;
  claimantEmail: string;
  committedAt: string;
  validationStateRef: string;
  contextPackageRef: string;
  suggestionHistory: SuggestionHistory;
  specPath: string;
  decompositionRef: string | null;
  isMultiplayer: boolean;
  ratificationThreshold: number;
  ratificationStatus: string;
}

// ── Per-spec ownership ───────────────────────────────────────────

export interface SpecClaimInfo {
  specType: string;
  claimant: string;
  claimantEmail: string;
  claimedAt: string;
  lastActivityAt: string;
  releasedAt: string | null;
}

export interface VerdictEntry {
  id: string;
  revisionId: string;
  actor: string;
  actorEmail: string;
  verdict: string;
  comment: string | null;
  timestamp: string;
}

export interface RatificationState {
  featureName: string;
  revisionId: string;
  status: string;
  ratificationCount: number;
  threshold: number;
  verdicts: VerdictEntry[];
  isAuthor: boolean;
  hasVoted: boolean;
}

// ── Queries ─────────────────────────────────────────────────────

export interface CeremonyInfoData {
  ceremonyInfo: CeremonyInfo | null;
}

export const CEREMONY_INFO_QUERY = gql`
  query CeremonyInfo($featureName: String!) {
    ceremonyInfo(featureName: $featureName) {
      featureName
      currentRevision {
        revisionId
        parentId
        status
        specContentHash
        contextPackageHash
        validationHash
        createdAt
        reason
      }
      revisionCount
      author
      authorEmail
      createdAt
      isMultiplayer
    }
  }
`;

// ── Current actor ───────────────────────────────────────────────

export interface CurrentActor {
  name: string;
  email: string;
}

export interface CurrentActorData {
  currentActor: CurrentActor;
}

export const CURRENT_ACTOR_QUERY = gql`
  query CurrentActor {
    currentActor {
      name
      email
    }
  }
`;
