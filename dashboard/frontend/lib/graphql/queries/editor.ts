import { gql } from "urql";

// ── Types ──────────────────────────────────────────────────────────

export interface SpecEntry {
  path: string;
  specType: string;
  feature: string | null;
  lifecycleState: string;
  completeness: number | null;
  sectionCount: number;
  updatedAt: string;
}

export interface SpecGroup {
  feature: string;
  specs: SpecEntry[];
  ghosts: string[];
}

export interface SpecSection {
  heading: string;
  headingLevel: number;
  tier: string;
  ordinal: number;
  lineStart: number;
  lineEnd: number;
}

export interface StructuredSpec {
  path: string;
  specType: string;
  feature: string | null;
  lifecycleState: string;
  completeness: number | null;
  sections: SpecSection[];
  content: string;
  headerLines: string[];
}

export interface AuditCheck {
  checkId: string;
  description: string;
  dimension: string;
  passed: boolean;
}

export interface AuditResult {
  specPath: string;
  completeness: number;
  checks: AuditCheck[];
}

export interface SpecRelation {
  source: string;
  target: string;
  relType: string;
  evidence: string | null;
}

export interface SpecSearchResult {
  path: string;
  specType: string;
  feature: string | null;
  snippet: string;
}

export interface SpecMutationResult {
  success: boolean;
  path: string | null;
  error: string | null;
}

export interface SpecChangedEvent {
  path: string;
  action: string;
}

export interface SpecTreeData {
  specTree: SpecGroup[];
}

export interface SpecData {
  spec: StructuredSpec | null;
}

export interface SpecAuditData {
  specAudit: AuditResult | null;
}

export interface RelatedSpecsData {
  relatedSpecs: SpecRelation[];
}

export interface SpecSearchData {
  specSearch: SpecSearchResult[];
}

// ── Queries ────────────────────────────────────────────────────────

export const SPEC_TREE_QUERY = gql`
  query SpecTree($feature: String) {
    specTree(feature: $feature) {
      feature
      specs {
        path
        specType
        feature
        lifecycleState
        completeness
        sectionCount
        updatedAt
      }
      ghosts
    }
  }
`;

export const SPEC_QUERY = gql`
  query Spec($path: String!) {
    spec(path: $path) {
      path
      specType
      feature
      lifecycleState
      completeness
      sections {
        heading
        headingLevel
        tier
        ordinal
        lineStart
        lineEnd
      }
      content
      headerLines
    }
  }
`;

export const SPEC_AUDIT_QUERY = gql`
  query SpecAudit($path: String!) {
    specAudit(path: $path) {
      specPath
      completeness
      checks {
        checkId
        description
        dimension
        passed
      }
    }
  }
`;

export const RELATED_SPECS_QUERY = gql`
  query RelatedSpecs($path: String!) {
    relatedSpecs(path: $path) {
      source
      target
      relType
      evidence
    }
  }
`;

export const SPEC_SEARCH_QUERY = gql`
  query SpecSearch($query: String!, $limit: Int) {
    specSearch(query: $query, limit: $limit) {
      path
      specType
      feature
      snippet
    }
  }
`;

// ── Mutations ──────────────────────────────────────────────────────

export const CREATE_SPEC_MUTATION = gql`
  mutation CreateSpec($name: String!, $specType: String!, $feature: String) {
    createSpec(name: $name, specType: $specType, feature: $feature) {
      success
      path
      error
    }
  }
`;

export const UPDATE_SPEC_CONTENT_MUTATION = gql`
  mutation UpdateSpecContent($path: String!, $content: String!) {
    updateSpecContent(path: $path, content: $content) {
      success
      path
      error
    }
  }
`;

export const DELETE_SPEC_MUTATION = gql`
  mutation DeleteSpec($path: String!) {
    deleteSpec(path: $path) {
      success
      path
      error
    }
  }
`;

// ── Intelligence queries ───────────────────────────────────────────

export interface Lesson {
  id: string;
  feature: string;
  observationType: string;
  detail: string;
  stage: string;
  weight: number;
  relevance: number;
}

export interface Convention {
  id: string;
  convention: string;
  scope: string[];
  confidence: string;
  tags: string[];
  adherence: number;
  relevance: number;
}

export interface ClusterContext {
  id: string;
  label: string;
  fileCount: number;
  symbolCount: number;
  cohesion: number;
}

export interface CodebaseStats {
  nodes: number;
  files: number;
  clusters: number;
  totalClusters: number;
  totalNodes: number;
}

export interface CodebaseContext {
  clusters: ClusterContext[];
  stats: CodebaseStats;
}

export const LESSONS_QUERY = gql`
  query LessonsForSpec($path: String!, $limit: Int) {
    lessonsForSpec(path: $path, limit: $limit) {
      id
      feature
      observationType
      detail
      stage
      weight
      relevance
    }
  }
`;

export const CONVENTIONS_QUERY = gql`
  query ConventionsForSpec($path: String!, $limit: Int) {
    conventionsForSpec(path: $path, limit: $limit) {
      id
      convention
      scope
      confidence
      tags
      adherence
      relevance
    }
  }
`;

export const CODEBASE_CONTEXT_QUERY = gql`
  query CodebaseContext($path: String!) {
    codebaseContext(path: $path) {
      clusters {
        id
        label
        fileCount
        symbolCount
        cohesion
      }
      stats {
        nodes
        files
        clusters
        totalClusters
        totalNodes
      }
    }
  }
`;

// ── Traceability + Feature Health ───────────────────────────────────

export interface CoveredRequirement {
  requirement: string;
  evidence: string;
}

export interface SpecTraceability {
  requirementsFound: number;
  coverageRatio: number;
  covered: CoveredRequirement[];
  uncovered: string[];
}

export interface ObservationTypeCount {
  type: string;
  count: number;
}

export interface ObservationSummary {
  total: number;
  types: ObservationTypeCount[];
}

export interface ContractEntity {
  name: string;
  type: string;
}

export interface TaskDetail {
  id: string;
  title: string;
  status: string;
  retryCount: number;
  filesTouched: number;
  reviewVerdict: string | null;
  findingCount: number | null;
}

export interface Highlight {
  type: string;
  stage: string;
  weight: number;
  detail: string;
}

export interface FeatureHealth {
  feature: string;
  status: string;
  observationSummary: ObservationSummary | null;
  contractEntities: ContractEntity[];
  tasks: TaskDetail[];
  highlights: Highlight[];
}

export const SPEC_TRACEABILITY_QUERY = gql`
  query SpecTraceability($path: String!) {
    specTraceability(path: $path) {
      requirementsFound
      coverageRatio
      covered {
        requirement
        evidence
      }
      uncovered
    }
  }
`;

export const FEATURE_HEALTH_QUERY = gql`
  query FeatureHealth($path: String!) {
    featureHealth(path: $path) {
      feature
      status
      observationSummary {
        total
        types {
          type
          count
        }
      }
      contractEntities {
        name
        type
      }
      tasks {
        id
        title
        status
        retryCount
        filesTouched
        reviewVerdict
        findingCount
      }
      highlights {
        type
        stage
        weight
        detail
      }
    }
  }
`;

// ── Assist ─────────────────────────────────────────────────────────

export interface LLMModel {
  id: string;
  provider: string;
  label: string;
}

export interface UnconfiguredProvider {
  provider: string;
  label: string;
  envVar: string;
}

export interface AmbiguityIssue {
  criterionText: string;
  missingCondition: string;
  severity: string;
  suggestedClause: string;
}

export interface AmbiguityReport {
  issues: AmbiguityIssue[];
  summary: string;
}

export interface FixSuggestionResult {
  section: string;
  issue: string;
  oldText: string;
  newText: string;
  rationale: string;
  severity: string;
}

export interface SpecDraftResult {
  content: string;
  sectionCount: number;
}

export const AVAILABLE_MODELS_QUERY = gql`
  query AvailableModels {
    availableModels {
      id
      provider
      label
    }
    unconfiguredProviders {
      provider
      label
      envVar
    }
  }
`;

export const CEREMONY_MODELS_QUERY = gql`
  query CeremonyModels {
    ceremonyModels {
      id
      provider
      label
    }
  }
`;

export const DETECT_AMBIGUITIES_MUTATION = gql`
  mutation DetectAmbiguities($path: String!, $model: String!) {
    detectAmbiguities(path: $path, model: $model) {
      issues {
        criterionText
        missingCondition
        severity
        suggestedClause
      }
      summary
    }
  }
`;

export const SUGGEST_FIX_MUTATION = gql`
  mutation SuggestFix($specPath: String!, $sectionText: String!, $issueDescription: String!, $model: String!) {
    suggestFix(specPath: $specPath, sectionText: $sectionText, issueDescription: $issueDescription, model: $model) {
      section
      issue
      oldText
      newText
      rationale
      severity
    }
  }
`;

export const BUILD_SPEC_DRAFT_MUTATION = gql`
  mutation BuildSpecDraft($problemStatement: String!, $specType: String!, $model: String!) {
    buildSpecDraft(problemStatement: $problemStatement, specType: $specType, model: $model) {
      content
      sectionCount
    }
  }
`;

// ── Audit (SPEED-native types, read from disk) ─────────────────────

export interface AuditIssue {
  level: number;
  severity: string;
  section: string;
  message: string;
}

export interface AuditLinkedSpecs {
  prd: string | null;
  design: string | null;
  parentRfc: string | null;
  childRfcs: string[];
}

export interface AuditSuggestedChild {
  name: string;
  sections: number[];
  dependsOn: string[];
  testableOutput: string;
}

export interface AuditSizing {
  estimatedTasks: number;
  recommendation: string;
  rationale: string;
  suggestedChildren: AuditSuggestedChild[];
}

export interface SpeedAuditResult {
  status: string;
  specType: string;
  specFile: string;
  linkedSpecs: AuditLinkedSpecs | null;
  issues: AuditIssue[];
  sizing: AuditSizing | null;
  stale: boolean;
  ranAt: string;
  feature: string;
}

export interface AuditRunStatus {
  success: boolean;
  error: string | null;
}

export interface AuditStatus {
  running: boolean;
  startedAt: string;
}

export const AUDIT_STATUS_QUERY = gql`
  query AuditStatus($specPath: String!) {
    auditStatus(specPath: $specPath) {
      running
      startedAt
    }
  }
`;

export const LATEST_AUDIT_QUERY = gql`
  query LatestAudit($specPath: String!) {
    latestAudit(specPath: $specPath) {
      status
      specType
      specFile
      linkedSpecs {
        prd
        design
        parentRfc
        childRfcs
      }
      issues {
        level
        severity
        section
        message
      }
      sizing {
        estimatedTasks
        recommendation
        rationale
        suggestedChildren {
          name
          sections
          dependsOn
          testableOutput
        }
      }
      stale
      ranAt
      feature
    }
  }
`;

export const RECENT_AUDITS_QUERY = gql`
  query RecentAudits($specPath: String!, $limit: Int) {
    recentAudits(specPath: $specPath, limit: $limit) {
      status
      ranAt
      issues {
        level
        severity
        section
        message
      }
      sizing {
        estimatedTasks
        recommendation
        rationale
        suggestedChildren {
          name
          sections
          dependsOn
          testableOutput
        }
      }
      stale
      feature
    }
  }
`;

export const RUN_AUDIT_MUTATION = gql`
  mutation RunAudit($path: String!) {
    runAudit(path: $path) {
      success
      error
    }
  }
`;

export const GIT_BRANCH_QUERY = gql`
  query GitBranch {
    gitBranch
  }
`;

// ── Subscriptions ──────────────────────────────────────────────────

export const SPEC_CHANGED_SUBSCRIPTION = gql`
  subscription SpecChanged {
    specChanged {
      path
      action
    }
  }
`;

export const AUDIT_COMPLETED_SUBSCRIPTION = gql`
  subscription AuditCompleted($feature: String) {
    auditCompleted(feature: $feature) {
      feature
      file
    }
  }
`;
