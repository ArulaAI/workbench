import { gql } from "urql";

// ── Types ────────────────────────────────────────────────────────

export interface BootstrapStatus {
  needsBootstrap: boolean;
  graphBuilt: boolean;
  visionCommitted: boolean;
  conventionsCommitted: boolean;
  currentStep: string;
}

export interface GraphBuildResult {
  status: string;
  fileCount: number;
  nodeCount: number;
  message?: string;
}

export interface VisionResult {
  generatedContent: string;
  status: string;
  message?: string;
}

export interface Convention {
  id: string;
  text?: string;
  convention?: string;
  source?: string;
  confidence?: string;
  status: string;
  scope?: string[];
  tags?: string[];
}

export interface VisionDraft {
  content: string;
  status: string;
}

// ── Query/Mutation response types ────────────────────────────────

export interface BootstrapStatusData {
  bootstrapStatus: BootstrapStatus;
}

export interface GraphBuildData {
  startGraphBuild: GraphBuildResult;
}

export interface GenerateVisionData {
  generateVision: VisionResult;
}

export interface CommitVisionData {
  commitVision: { committed: boolean };
}

export interface CommitVisionVars {
  content: string;
}

export interface ExtractConventionsData {
  extractConventions: Convention[];
}

export interface ResolveConventionData {
  resolveConvention: Convention;
}

export interface ResolveConventionVars {
  conventionId: string;
  action: string;
}

export interface CommitConventionsData {
  commitConventions: { committed: boolean; acceptedCount: number };
}

export interface CommitConventionsVars {
  personaInput?: string;
}

export interface CompleteBootstrapData {
  completeBootstrap: { complete: boolean };
}

export interface VisionDraftData {
  visionDraft: VisionDraft;
}

// ── Queries ──────────────────────────────────────────────────────

export const BOOTSTRAP_STATUS_QUERY = gql`
  query BootstrapStatus {
    bootstrapStatus
  }
`;

export const VISION_DRAFT_QUERY = gql`
  query VisionDraft {
    visionDraft
  }
`;

export const DERIVED_CONVENTIONS_QUERY = gql`
  query DerivedConventions {
    derivedConventions
  }
`;

// ── Mutations ────────────────────────────────────────────────────

export const START_GRAPH_BUILD_MUTATION = gql`
  mutation StartGraphBuild {
    startGraphBuild
  }
`;

export const GENERATE_VISION_MUTATION = gql`
  mutation GenerateVision {
    generateVision
  }
`;

export const COMMIT_VISION_MUTATION = gql`
  mutation CommitVision($content: String!) {
    commitVision(content: $content)
  }
`;

export const EXTRACT_CONVENTIONS_MUTATION = gql`
  mutation ExtractConventions {
    extractConventions
  }
`;

export const RESOLVE_CONVENTION_MUTATION = gql`
  mutation ResolveConvention($conventionId: String!, $action: String!) {
    resolveConvention(conventionId: $conventionId, action: $action)
  }
`;

export const COMMIT_CONVENTIONS_MUTATION = gql`
  mutation CommitConventions($personaInput: String) {
    commitConventions(personaInput: $personaInput)
  }
`;

export const COMPLETE_BOOTSTRAP_MUTATION = gql`
  mutation CompleteBootstrap {
    completeBootstrap
  }
`;
