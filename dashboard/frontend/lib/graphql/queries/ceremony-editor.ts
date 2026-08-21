import { gql } from "urql";
import type {
  SpecDraft,
  ValidationState,
  ValidationDimension,
  ValidationIssue,
} from "./ceremony";

// ── Query response types ──────────────────────────────────────

export interface SpecDraftData {
  specDraft: SpecDraft | null;
}

export interface SpecDraftVars {
  featureName: string;
  specType?: string;
}

export interface AllSpecDraftsData {
  allSpecDrafts: SpecDraft[];
}

export interface AllSpecDraftsVars {
  featureName: string;
}

export interface ValidationStateData {
  validationState: ValidationState | null;
}

export interface ValidationStateVars {
  featureName: string;
  specType?: string;
}

// ── Mutation response types ───────────────────────────────────

export interface GenerateDraftResult {
  featureName: string;
  specType: string;
  status: string; // "generating" | "complete" | "error"
  draft: SpecDraft | null;
  error: string | null;
}

export interface GenerateDraftData {
  generateDraft: GenerateDraftResult;
}

export interface GenerateDraftVars {
  featureName: string;
  specType: string;
  model: string;
  refinement?: string;
}

export interface DraftGenerationEvent {
  feature: string;
  specType: string;
  status: string;
  error: string | null;
}

export interface DraftGenerationProgressData {
  draftGenerationProgress: DraftGenerationEvent;
}

export interface UpdateDraftData {
  updateDraft: SpecDraft;
}

export interface UpdateDraftVars {
  featureName: string;
  specType: string;
  content: string;
}

export interface ValidateDraftData {
  validateDraft: ValidationState;
}

export interface ValidateDraftVars {
  featureName: string;
  specType?: string;
  model?: string;
}

// ── Fragments ─────────────────────────────────────────────────

const SPEC_DRAFT_FIELDS = `
  fragment SpecDraftFields on SpecDraft {
    featureName
    specType
    content
    filePath
    templateName
    generatedAt
    childSpecs {
      featureName
      specType
      content
      filePath
      templateName
      generatedAt
      childSpecs { featureName }
    }
  }
`;

const VALIDATION_STATE_FIELDS = `
  fragment ValidationStateFields on ValidationState {
    dimensions {
      name
      status
      issues {
        id
        dimension
        severity
        message
        section
        line
        crossRefSpec
        crossRefSection
      }
      checkedAt
      tier
    }
    passCount
    warnCount
    failCount
  }
`;

// ── Queries ───────────────────────────────────────────────────

export const SPEC_DRAFT_QUERY = gql`
  ${SPEC_DRAFT_FIELDS}
  query SpecDraft($featureName: String!, $specType: String) {
    specDraft(featureName: $featureName, specType: $specType) {
      ...SpecDraftFields
    }
  }
`;

export const ALL_SPEC_DRAFTS_QUERY = gql`
  ${SPEC_DRAFT_FIELDS}
  query AllSpecDrafts($featureName: String!) {
    allSpecDrafts(featureName: $featureName) {
      ...SpecDraftFields
    }
  }
`;

export const VALIDATION_STATE_QUERY = gql`
  ${VALIDATION_STATE_FIELDS}
  query ValidationState($featureName: String!, $specType: String) {
    validationState(featureName: $featureName, specType: $specType) {
      ...ValidationStateFields
    }
  }
`;

// ── Mutations ─────────────────────────────────────────────────

export const GENERATE_DRAFT_MUTATION = gql`
  mutation GenerateDraft($featureName: String!, $specType: String!, $model: String!, $refinement: String) {
    generateDraft(featureName: $featureName, specType: $specType, model: $model, refinement: $refinement) {
      featureName
      specType
      status
      error
    }
  }
`;

export const DRAFT_GENERATION_PROGRESS_SUBSCRIPTION = gql`
  subscription DraftGenerationProgress($feature: String!) {
    draftGenerationProgress(feature: $feature) {
      feature
      specType
      status
      error
    }
  }
`;

export const UPDATE_DRAFT_MUTATION = gql`
  ${SPEC_DRAFT_FIELDS}
  mutation UpdateDraft($featureName: String!, $specType: String!, $content: String!) {
    updateDraft(featureName: $featureName, specType: $specType, content: $content) {
      ...SpecDraftFields
    }
  }
`;

export const VALIDATE_DRAFT_MUTATION = gql`
  ${VALIDATION_STATE_FIELDS}
  mutation ValidateDraft($featureName: String!, $specType: String, $model: String) {
    validateDraft(featureName: $featureName, specType: $specType, model: $model) {
      ...ValidationStateFields
    }
  }
`;

// ── Decomposition progress ───────────────────────────────────

export interface DecompositionProgressEvent {
  feature: string;
  specType: string;
  stage: string; // loading_specs | assembling_context | calling_architect | parsing_response | running_gate | complete | error
  error: string | null;
  taskCount: number | null;
  elapsedS: number | null;
  model: string | null;
}

export interface DecompositionProgressData {
  decompositionProgress: DecompositionProgressEvent;
}

export const DECOMPOSITION_PROGRESS_SUBSCRIPTION = gql`
  subscription DecompositionProgress($feature: String!) {
    decompositionProgress(feature: $feature) {
      feature
      specType
      stage
      error
      taskCount
      elapsedS
      model
    }
  }
`;

// ── Decomposition ────────────────────────────────────────────

export interface SpecReference {
  spec: string;
  section: string;
  requirement: string;
}

export interface ArchitectTask {
  id: string;
  title: string;
  description: string;
  acceptanceCriteria: string;
  dependsOn: string[];
  agentModel: string;
  filesTouched: string[];
  rationale: string | null;
  assumptions: string[];
  specReferences: SpecReference[];
}

export interface GateResult {
  overall: string;
  warnings: string[];
}

export interface DecompositionResult {
  featureName: string;
  specType: string;
  status: string;
  taskCount: number;
  parallelChains: number;
  longestChain: number;
  tasks: ArchitectTask[];
  gate: GateResult | null;
  error: string | null;
}

export interface DecompositionResultData {
  decompositionResult: DecompositionResult | null;
}

export interface DecomposeDraftData {
  decomposeDraft: DecompositionResult;
}

export interface DecomposeDraftVars {
  featureName: string;
  specType?: string;
  model?: string;
}

export const DECOMPOSITION_RESULT_QUERY = gql`
  query DecompositionResult($featureName: String!) {
    decompositionResult(featureName: $featureName) {
      featureName
      specType
      status
      taskCount
      parallelChains
      longestChain
      tasks {
        id
        title
        description
        acceptanceCriteria
        dependsOn
        agentModel
        filesTouched
        rationale
        assumptions
        specReferences { spec section requirement }
      }
      gate { overall warnings }
      error
    }
  }
`;

export const DECOMPOSE_DRAFT_MUTATION = gql`
  mutation DecomposeDraft($featureName: String!, $specType: String, $model: String) {
    decomposeDraft(featureName: $featureName, specType: $specType, model: $model) {
      featureName
      specType
      status
      taskCount
      parallelChains
      longestChain
      tasks {
        id
        title
        description
        acceptanceCriteria
        dependsOn
        agentModel
        filesTouched
        rationale
        assumptions
        specReferences { spec section requirement }
      }
      gate { overall warnings }
      error
    }
  }
`;

// ── Child RFC generation ─────────────────────────────────────

export interface ChildRfcInput {
  name: string;
  userStoryIds: string[];
  dependsOn?: string[];
}

export interface GenerateChildRfcsVars {
  featureName: string;
  decomposition: { children: ChildRfcInput[] };
  model: string;
}

export interface GenerateChildRfcsData {
  generateChildRfcs: {
    featureName: string;
    status: string;
    drafts: Array<{
      featureName: string;
      specType: string;
      content: string;
      filePath: string;
      templateName: string;
      generatedAt: string | null;
    }>;
    error: string | null;
  };
}

export const GENERATE_CHILD_RFCS_MUTATION = gql`
  mutation GenerateChildRfcs(
    $featureName: String!
    $decomposition: DecompositionInput!
    $model: String!
  ) {
    generateChildRfcs(
      featureName: $featureName
      decomposition: $decomposition
      model: $model
    ) {
      featureName
      status
      drafts {
        featureName
        specType
        content
        filePath
        templateName
        generatedAt
      }
      error
    }
  }
`;
