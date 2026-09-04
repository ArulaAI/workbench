/**
 * Guided authoring GraphQL surface.
 *
 * Every interview field arrives from the packaged helper. The client renders
 * what it is given: it never authors a question, an option label, an ordering,
 * or a gate.
 */

const SESSION_FIELDS = `
  status
  featureName
  featureTitle
  artifactType
  questionBankVersion
  revision
  message
  progress { confirmed total deferred }
  draftAvailable
  artifactPath
  artifactContent
  dashboardUrl
  authoringUrl
  helperPath
  interpreter
  currentQuestion
  coverage
  sections
  selfReview
  resumeStep
  implementation
`;

export const AUTHORING_INTAKE_QUERY = `
  query AuthoringIntake($artifactType: String) {
    authoringIntake(artifactType: $artifactType) {
      status
      artifactType
      nextInput
      message
    }
  }
`;

export const AUTHORING_SESSION_QUERY = `
  query AuthoringSession($featureName: String!, $artifactType: String) {
    authoringSession(featureName: $featureName, artifactType: $artifactType) {
      ${SESSION_FIELDS}
    }
  }
`;

export const START_AUTHORING_MUTATION = `
  mutation StartAuthoring(
    $featureName: String!
    $featureTitle: String
    $featureDescription: String
  ) {
    startAuthoring(
      featureName: $featureName
      featureTitle: $featureTitle
      featureDescription: $featureDescription
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const SUBMIT_AUTHORING_ANSWER_MUTATION = `
  mutation SubmitAuthoringAnswer(
    $featureName: String!
    $answer: String!
    $expectedRevision: Int!
  ) {
    submitAuthoringAnswer(
      featureName: $featureName
      answer: $answer
      expectedRevision: $expectedRevision
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const SELECT_AUTHORING_ACTION_MUTATION = `
  mutation SelectAuthoringAction(
    $featureName: String!
    $action: AuthoringAction!
    $expectedRevision: Int!
  ) {
    selectAuthoringAction(
      featureName: $featureName
      action: $action
      expectedRevision: $expectedRevision
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const REVISE_AUTHORING_COVERAGE_MUTATION = `
  mutation ReviseAuthoringCoverage(
    $featureName: String!
    $coverageId: String!
    $answer: String!
    $expectedRevision: Int!
  ) {
    reviseAuthoringCoverage(
      featureName: $featureName
      coverageId: $coverageId
      answer: $answer
      expectedRevision: $expectedRevision
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const AUTHORING_SESSION_CHANGED_SUBSCRIPTION = `
  subscription AuthoringSessionChanged($feature: String!) {
    authoringSessionChanged(feature: $feature) {
      feature
      artifactType
      revision
      status
    }
  }
`;

export type AuthoringAction = "ACCEPT" | "EDIT" | "REJECT" | "DEFER";

export type ConfidenceLabel =
  | "confirmed"
  | "evidence_backed"
  | "inferred"
  | "unresolved"
  | "not_material"
  | "missing";

export interface IntakeField {
  id: string;
  input_type: string;
  prompt: string;
  description?: string;
  required?: boolean;
  derived_from?: string;
}

export interface IntakeInput {
  id: string;
  input_type: string;
  prompt: string;
  fields?: IntakeField[];
  options?: { value?: string; label?: string; feature_name?: string; path?: string }[];
}

export interface AuthoringIntakeData {
  authoringIntake: {
    status: string;
    artifactType: string | null;
    nextInput: IntakeInput | null;
    message: string;
  };
}

export interface SuggestionSource {
  id: string;
  path: string;
  status?: string;
  excerpt?: string;
}

export interface Suggestion {
  id: string;
  answer: string | null;
  confidence: "grounded" | "partial" | "missing";
  accept_ready?: boolean;
  rejected?: boolean;
  sources: SuggestionSource[];
  gaps: string[];
}

export interface ResponseControl {
  id: string;
  input_type: "single_select" | "textarea" | string;
  prompt: string;
  initial_value?: string;
  options?: { value: string; label: string }[];
  submit_action?: string;
}

export interface CurrentQuestion {
  id: string;
  prompt: string;
  evidence: string;
  purpose?: string | null;
  suggestion: Suggestion | null;
  existing_answer?: string | null;
  follow_up?: { prompt: string; status?: string } | null;
  edit_request?: { initial_value?: string; status?: string } | null;
  response_control: ResponseControl;
  review_findings: { message: string; question_id: string }[];
}

export interface CoverageEntry {
  confidence?: number;
  confidence_label?: ConfidenceLabel;
  impact?: string;
  basis?: string[];
  question_value?: number;
}

export interface SectionProvenanceEntry {
  title: string;
  question_ids: string[];
  coverage_ids: string[];
  state: string;
}

export interface AuthoringSession {
  status: string;
  featureName: string | null;
  featureTitle: string | null;
  artifactType: string | null;
  questionBankVersion: string | null;
  revision: number | null;
  message: string;
  progress: { confirmed: number; total: number; deferred: string[] };
  draftAvailable: boolean;
  artifactPath: string | null;
  artifactContent: string | null;
  dashboardUrl: string | null;
  authoringUrl: string | null;
  helperPath: string | null;
  interpreter: string | null;
  currentQuestion: CurrentQuestion | null;
  coverage: Record<string, CoverageEntry> | null;
  sections: SectionProvenanceEntry[] | null;
  selfReview: {
    status?: string;
    pass_count?: number;
    findings?: { message: string; question_id: string }[];
  } | null;
  resumeStep: { question_id: string; control_id: string; revision: number } | null;
  implementation: { helper_hash?: string; question_bank_hash?: string } | null;
}

export interface AuthoringSessionData {
  authoringSession: AuthoringSession;
}
export interface StartAuthoringData {
  startAuthoring: AuthoringSession;
}
export interface SubmitAuthoringAnswerData {
  submitAuthoringAnswer: AuthoringSession;
}
export interface SelectAuthoringActionData {
  selectAuthoringAction: AuthoringSession;
}
export interface ReviseAuthoringCoverageData {
  reviseAuthoringCoverage: AuthoringSession;
}
export interface AuthoringSessionChangedData {
  authoringSessionChanged: {
    feature: string;
    artifactType: string;
    revision: number | null;
    status: string;
  };
}

export const FEATURE_SLUG_MAX = 50;

/**
 * Mirror of the helper's `_slugify`: lowercase, non-alphanumeric runs become
 * single hyphens, trimmed, capped at 50 characters. Kept in sync by
 * `slug.test.ts`, and the helper validates authoritatively at the write.
 */
export function deriveSlug(title: string): string {
  const lowered = title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return lowered.replace(/^-+|-+$/g, "").slice(0, FEATURE_SLUG_MAX).replace(/-+$/g, "");
}

export function isValidSlug(slug: string): boolean {
  return /^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$/.test(slug) && !slug.includes("--");
}
