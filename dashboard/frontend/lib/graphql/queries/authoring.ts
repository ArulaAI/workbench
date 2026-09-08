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
  intake
  interview
  selfReview
  resumeStep
  implementation
  planning
  reviewComments
  versions
  publishedRevision
  publishHistory
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

export const AUTHORING_SESSIONS_QUERY = `
  query AuthoringSessions($artifactType: String) {
    authoringSessions(artifactType: $artifactType) {
      status
      message
      sessions {
        featureName
        featureTitle
        artifactType
        status
        revision
        updatedAt
        progress { confirmed total deferred }
        draftAvailable
        artifactPath
        authoringUrl
        message
      }
    }
  }
`;

export const START_AUTHORING_MUTATION = `
  mutation StartAuthoring(
    $featureName: String!
    $featureTitle: String
    $featureDescription: String
    $artifactType: String = "prd"
  ) {
    startAuthoring(
      featureName: $featureName
      featureTitle: $featureTitle
      featureDescription: $featureDescription
      artifactType: $artifactType
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const SUBMIT_AUTHORING_ANSWER_MUTATION = `
  mutation SubmitAuthoringAnswer(
    $featureName: String!
    $questionId: String!
    $answer: String!
    $expectedRevision: Int!
    $artifactType: String = "prd"
  ) {
    submitAuthoringAnswer(
      featureName: $featureName
      questionId: $questionId
      answer: $answer
      expectedRevision: $expectedRevision
      artifactType: $artifactType
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const SUBMIT_AUTHORING_ANSWERS_MUTATION = `
  mutation SubmitAuthoringAnswers(
    $featureName: String!
    $answers: JSON!
    $expectedRevision: Int!
    $artifactType: String = "prd"
  ) {
    submitAuthoringAnswers(
      featureName: $featureName
      answers: $answers
      expectedRevision: $expectedRevision
      artifactType: $artifactType
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
    $artifactType: String = "prd"
  ) {
    selectAuthoringAction(
      featureName: $featureName
      action: $action
      expectedRevision: $expectedRevision
      artifactType: $artifactType
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
    $artifactType: String = "prd"
  ) {
    reviseAuthoringCoverage(
      featureName: $featureName
      coverageId: $coverageId
      answer: $answer
      expectedRevision: $expectedRevision
      artifactType: $artifactType
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const REVISE_AUTHORING_SECTION_MUTATION = `
  mutation ReviseAuthoringSection(
    $featureName: String!
    $sectionTitle: String!
    $body: String!
    $expectedRevision: Int!
    $artifactType: String = "prd"
  ) {
    reviseAuthoringSection(
      featureName: $featureName
      sectionTitle: $sectionTitle
      body: $body
      expectedRevision: $expectedRevision
      artifactType: $artifactType
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const REVISE_AUTHORING_DOCUMENT_MUTATION = `
  mutation ReviseAuthoringDocument(
    $featureName: String!
    $content: String!
    $expectedRevision: Int!
    $artifactType: String = "prd"
  ) {
    reviseAuthoringDocument(
      featureName: $featureName
      content: $content
      expectedRevision: $expectedRevision
      artifactType: $artifactType
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const SUBMIT_AUTHORING_REVIEW_COMMENTS_MUTATION = `
  mutation SubmitAuthoringReviewComments(
    $featureName: String!
    $comments: JSON!
    $expectedRevision: Int!
    $artifactType: String = "prd"
  ) {
    submitAuthoringReviewComments(
      featureName: $featureName
      comments: $comments
      expectedRevision: $expectedRevision
      artifactType: $artifactType
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const ADD_AUTHORING_REVIEW_COMMENT_MUTATION = `
  mutation AddAuthoringReviewComment(
    $featureName: String!
    $comment: JSON!
    $expectedRevision: Int!
    $artifactType: String = "prd"
  ) {
    addAuthoringReviewComment(
      featureName: $featureName
      comment: $comment
      expectedRevision: $expectedRevision
      artifactType: $artifactType
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export const PUBLISH_AUTHORING_DRAFT_MUTATION = `
  mutation PublishAuthoringDraft(
    $featureName: String!
    $expectedRevision: Int!
    $artifactType: String = "prd"
  ) {
    publishAuthoringDraft(
      featureName: $featureName
      expectedRevision: $expectedRevision
      artifactType: $artifactType
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

export interface AuthoringReviewComment {
  id?: string;
  section_title: string;
  comment: string;
  selected_text?: string;
  selection_start?: number;
  selection_end?: number;
  anchor_revision?: number;
  author?: string;
  author_email?: string;
  status?: "open" | "applied" | "resolved";
  created_at?: string;
  saved_revision?: number;
}

export const PREPARE_AUTHORING_COMMIT_MUTATION = `
  mutation PrepareAuthoringCommit($featureName: String!, $artifactType: String = "prd") {
    prepareAuthoringCommit(featureName: $featureName, artifactType: $artifactType) {
      status
      featureName
      featureTitle
      artifactType
      revision
      message
      progress { confirmed total deferred }
      draftAvailable
      artifactPath
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
  max_length?: number;
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
  input_type: "single_select" | "multi_select" | "textarea" | string;
  prompt: string;
  initial_value?: string;
  options?: {
    value: string;
    label: string;
    description?: string | null;
    recommended?: boolean;
  }[];
  submit_action?: string;
  allow_other?: boolean;
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
  source_answer?: string | null;
  source_answers?: Record<string, string>;
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
  intake: {
    feature_title?: string | null;
    feature_description?: string | null;
    captured_at?: string | null;
  } | null;
  interview: InterviewAnswer[] | null;
  selfReview: {
    status?: string;
    pass_count?: number;
    findings?: { message: string; question_id: string | null; kind?: string }[];
  } | null;
  resumeStep: { question_id: string; control_id: string; revision: number } | null;
  implementation: { helper_hash?: string; question_bank_hash?: string } | null;
  planning: {
    mode?: "model" | "fallback";
    planner_version?: string | null;
    model?: string | null;
    generated_at?: string | null;
    analysis_summary?: string | null;
    fallback_reason?: string | null;
    questions?: CurrentQuestion[];
  } | null;
  reviewComments?: AuthoringReviewComment[] | null;
  versions: {
    revision: number;
    content: string;
    created_at?: string | null;
    source?: string | null;
    status?: "draft" | "published" | string | null;
    published_at?: string | null;
  }[] | null;
  publishedRevision: number | null;
  publishHistory: { revision: number; published_at?: string | null }[] | null;
}

export interface InterviewAnswer {
  id: string;
  coverage_id?: string | null;
  prompt: string;
  answer: string | null;
  state: string;
  decision?: string | null;
  confirmed_at?: string | null;
}

export interface AuthoringSessionSummary {
  featureName: string;
  featureTitle: string | null;
  artifactType: string;
  status: string;
  revision: number | null;
  updatedAt: string | null;
  progress: { confirmed: number; total: number; deferred: string[] };
  draftAvailable: boolean;
  artifactPath: string | null;
  authoringUrl: string | null;
  message: string;
}

export interface AuthoringSessionsData {
  authoringSessions: {
    status: string;
    message: string;
    sessions: AuthoringSessionSummary[];
  };
}

export interface AuthoringSessionData {
  authoringSession: AuthoringSession;
}
export interface StartAuthoringData {
  startAuthoring: AuthoringSession;
}

export interface PrepareAuthoringCommitData {
  prepareAuthoringCommit: AuthoringSession;
}
export interface PublishAuthoringDraftData {
  publishAuthoringDraft: AuthoringSession;
}
export interface SubmitAuthoringAnswerData {
  submitAuthoringAnswer: AuthoringSession;
}
export interface SubmitAuthoringAnswersData {
  submitAuthoringAnswers: AuthoringSession;
}
export interface ReplanAuthoringData {
  replanAuthoring: AuthoringSession;
}
export interface SelectAuthoringActionData {
  selectAuthoringAction: AuthoringSession;
}
export interface ReviseAuthoringCoverageData {
  reviseAuthoringCoverage: AuthoringSession;
}
export interface ReviseAuthoringSectionData {
  reviseAuthoringSection: AuthoringSession;
}
export interface AuthoringSessionChangedData {
  authoringSessionChanged: {
    feature: string;
    artifactType: string;
    revision: number | null;
    status: string;
  };
}

export const REPLAN_AUTHORING_MUTATION = `
  mutation ReplanAuthoring(
    $featureName: String!
    $artifactType: String = "prd"
    $expectedRevision: Int!
  ) {
    replanAuthoring(
      featureName: $featureName
      artifactType: $artifactType
      expectedRevision: $expectedRevision
    ) {
      ${SESSION_FIELDS}
    }
  }
`;

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

export function deriveTitleFromDescription(description: string): string {
  const normalized = description.replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  const statedIntent = normalized.match(
    /(?:what\s+(?:i|we)\s+want\s+is(?:\s+that)?|(?:i|we)\s+(?:want|need)(?:\s+to)?(?:\s+an?)?|please)\s+([^.!?]+)/i,
  )?.[1];
  let source = (statedIntent ?? normalized.split(/[.!?]/)[0]).trim();
  const dashboardSubject = source.match(
    /^(?:an?\s+)?dashboard\s+that\s+(?:shows?|displays?|summarizes?)\s+(.+)$/i,
  )?.[1];
  if (dashboardSubject) {
    source = `${dashboardSubject.replace(
      /^(?:an?\s+)?(?:individual|user|customer)(?:'s)?\s+/i,
      "",
    )} dashboard`;
  }
  const concise = source
    .replace(/^(?:build|create|add|introduce|enable|allow)\s+/i, "")
    .split(/\s+/)
    .slice(0, 9)
    .join(" ")
    .replace(/[,;:]$/, "")
    .slice(0, 80)
    .trim();
  if (!concise) return "Untitled feature";
  return concise.charAt(0).toUpperCase() + concise.slice(1);
}

export function isValidSlug(slug: string): boolean {
  return /^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$/.test(slug) && !slug.includes("--");
}
