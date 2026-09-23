import { gql } from "urql";

export const FEATURE_FINDINGS_QUERY = gql`
  query FeatureFindings($featureName: String!) {
    featureFindings(featureName: $featureName)
  }
`;

export const DEFECT_DRAFT_QUERY = gql`
  query DefectDraft($featureName: String!, $findingId: String!) {
    defectDraft(featureName: $featureName, findingId: $findingId)
  }
`;

export const EVIDENCE_FILE_QUERY = gql`
  query EvidenceFile($featureName: String!, $findingId: String!, $evidenceId: String!, $sourcePath: String!) {
    evidenceFile(featureName: $featureName, findingId: $findingId, evidenceId: $evidenceId, sourcePath: $sourcePath)
  }
`;

export const DEFECT_REPORT_QUERY = gql`
  query DefectReport(
    $features: [String!]
    $severity: [String!]
    $status: [String!]
    $source: [String!]
    $lifecycle: [String!]
    $search: String!
  ) {
    defectReport(
      features: $features
      severity: $severity
      status: $status
      source: $source
      lifecycle: $lifecycle
      search: $search
    )
  }
`;

export const DEFECT_REPORT_EXPORT_QUERY = gql`
  query DefectReportExport(
    $displayedRevision: String!
    $format: String!
    $features: [String!]
    $severity: [String!]
    $status: [String!]
    $source: [String!]
    $lifecycle: [String!]
    $search: String!
  ) {
    defectReportExport(
      displayedRevision: $displayedRevision
      format: $format
      features: $features
      severity: $severity
      status: $status
      source: $source
      lifecycle: $lifecycle
      search: $search
    )
  }
`;

export const DECIDE_FINDING_MUTATION = gql`
  mutation DecideFinding($input: FindingDecisionInput!) {
    decideFinding(input: $input)
  }
`;

export const FILE_FINDING_DEFECT_MUTATION = gql`
  mutation FileFindingDefect($input: FileFindingDefectInput!) {
    fileFindingDefect(input: $input)
  }
`;

export const GROUP_FINDINGS_MUTATION = gql`
  mutation GroupFindings($input: GroupFindingsInput!) {
    groupFindings(input: $input)
  }
`;

export const APPEND_DEFECT_EVIDENCE_MUTATION = gql`
  mutation AppendDefectEvidence($input: AppendDefectEvidenceInput!) {
    appendDefectEvidence(input: $input)
  }
`;

export interface Evidence {
  id: string;
  source: string;
  producer: string;
  item_key: string;
  task_id: string | null;
  artifact_path: string;
  summary: string;
  observed: string | null;
  expected: string | null;
  reproduction: string | null;
  files: string[];
  confidence: string;
  severity: string | null;
}

export interface Finding {
  id: string;
  revision: string;
  title: string;
  evidence: Evidence[];
  stale: boolean;
  resolution: string;
  recommended_action: string;
  allowed_actions: string[];
  linked_defect_slug: string | null;
}

export interface FindingView {
  feature: string;
  decision_revision: number;
  findings: Finding[];
  warnings: string[];
}

export interface DraftView {
  draft: {
    title: string;
    severity: string | null;
    severity_confirmed: boolean;
    related_features: string[];
    observed: string;
    expected: string;
    reproduction: string;
    reproducibility: string;
    last_known_working: string;
    environment: string;
    error_output: string;
    context: string;
  };
  source_feature: string;
  finding_revision: string;
  decision_revision: number;
  provenance: { finding_id: string; evidence_ids: string[]; evidence_paths: string[] };
  missing_fields: string[];
  duplicates: Array<{ slug: string; title: string; status: string; canonical_path: string | null }>;
  warnings: string[];
}

export interface EvidenceFileView {
  success: boolean;
  code: string;
  errors: Array<{ field: string; message: string }>;
  path?: string;
  content?: string;
  start_line?: number;
  end_line?: number;
  highlight_line?: number | null;
  truncated?: boolean;
}
