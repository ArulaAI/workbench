import { gql } from "urql";
import type {
  CeremonyInfo,
  ContextPackage,
  CodebaseItem,
  LearningItem,
  DefectItem,
  KnowledgeItem,
  RelatedFeature,
  AuditHistoryItem,
} from "./ceremony";

// ── Result types ──────────────────────────────────────────────

export interface DeclareIntentResult {
  featureName: string;
  contextPackage: ContextPackage;
  ceremony: CeremonyInfo;
}

export interface SourceStatus {
  name: string;
  status: string; // "ok" | "error" | "empty"
  error: string | null;
}

export interface AssemblyStatus {
  status: string; // "idle" | "assembling" | "complete"
  sources: SourceStatus[];
}

export interface ContextHistory {
  snapshot: ContextPackage | null;
  current: ContextPackage | null;
  currentAssemblyStatus: string; // "ok" | "error"
  currentAssemblyError: string | null;
  ceremony: CeremonyInfo | null;
}

// ── Mutation response types ───────────────────────────────────

export interface DeclareIntentData {
  declareIntent: DeclareIntentResult;
}

export interface DeclareIntentVars {
  text: string;
  featureName: string;
  model?: string;
}

export interface RefineIntentData {
  refineIntent: DeclareIntentResult;
}

export interface RefineIntentVars {
  featureName: string;
  text: string;
  model?: string;
}

// ── Query response types ──────────────────────────────────────

export interface ContextPackageData {
  contextPackage: ContextPackage | null;
}

export interface ContextPackageVars {
  featureName: string;
}

export interface AssemblyStatusData {
  contextAssemblyStatus: AssemblyStatus;
}

export interface AssemblyStatusVars {
  featureName: string;
}

export interface ContextHistoryData {
  contextHistory: ContextHistory | null;
}

export interface ContextHistoryVars {
  featureName: string;
}

// ── Context package fragment ──────────────────────────────────

const CONTEXT_PACKAGE_FIELDS = `
  fragment ContextPackageFields on ContextPackage {
    intent
    featureName
    scopedArea
    codebase { path description nodeIds }
    learnings { text sourceFeature confidence }
    defects { name severity status relatedFiles }
    projectKnowledge { text confidence source }
    visionStatus
    visionContent
    relatedFeatures { name state overlapFiles }
    auditHistory { featureName finding severity section }
    assembledAt
    sourcesStatus
    scopingMethod
    lowConfidence
    blufSummary
  }
`;

// ── Mutations ─────────────────────────────────────────────────

export const DECLARE_INTENT_MUTATION = gql`
  ${CONTEXT_PACKAGE_FIELDS}
  mutation DeclareIntent($text: String!, $featureName: String!, $model: String) {
    declareIntent(text: $text, featureName: $featureName, model: $model) {
      featureName
      contextPackage { ...ContextPackageFields }
      ceremony {
        featureName
        currentRevision {
          revisionId
          status
          createdAt
        }
        revisionCount
        author
        authorEmail
        createdAt
        isMultiplayer
      }
    }
  }
`;

export const REFINE_INTENT_MUTATION = gql`
  ${CONTEXT_PACKAGE_FIELDS}
  mutation RefineIntent($featureName: String!, $text: String!, $model: String) {
    refineIntent(featureName: $featureName, text: $text, model: $model) {
      featureName
      contextPackage { ...ContextPackageFields }
      ceremony {
        featureName
        currentRevision {
          revisionId
          status
          createdAt
        }
        revisionCount
        author
        authorEmail
        createdAt
        isMultiplayer
      }
    }
  }
`;

// ── Subscriptions ────────────────────────────────────────────

export interface ContextAssemblyEvent {
  feature: string;
  source: string; // "codebase" | "learnings" | ... | "complete"
  status: string; // "ok" | "empty" | "error"
  error: string | null;
}

export interface ContextAssemblyProgressData {
  contextAssemblyProgress: ContextAssemblyEvent;
}

export const CONTEXT_ASSEMBLY_PROGRESS_SUBSCRIPTION = gql`
  subscription ContextAssemblyProgress($feature: String!) {
    contextAssemblyProgress(feature: $feature) {
      feature
      source
      status
      error
    }
  }
`;

// ── Queries ───────────────────────────────────────────────────

export const CONTEXT_PACKAGE_QUERY = gql`
  ${CONTEXT_PACKAGE_FIELDS}
  query ContextPackage($featureName: String!) {
    contextPackage(featureName: $featureName) {
      ...ContextPackageFields
    }
  }
`;

export const CONTEXT_ASSEMBLY_STATUS_QUERY = gql`
  query ContextAssemblyStatus($featureName: String!) {
    contextAssemblyStatus(featureName: $featureName) {
      status
      sources {
        name
        status
        error
      }
    }
  }
`;

export const CONTEXT_HISTORY_QUERY = gql`
  ${CONTEXT_PACKAGE_FIELDS}
  query ContextHistory($featureName: String!) {
    contextHistory(featureName: $featureName) {
      snapshot { ...ContextPackageFields }
      current { ...ContextPackageFields }
      currentAssemblyStatus
      currentAssemblyError
      ceremony {
        featureName
        currentRevision {
          revisionId
          status
          createdAt
        }
        revisionCount
        author
        authorEmail
        createdAt
        isMultiplayer
      }
    }
  }
`;
