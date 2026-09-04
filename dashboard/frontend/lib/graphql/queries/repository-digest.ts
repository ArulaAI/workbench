import { gql } from "urql";

export const REPOSITORY_DIGEST_QUERY = gql`
  query RepositoryDigest {
    repositoryDigest {
      schemaVersion
      status
      effectiveState
      generatedAt
      freshness {
        state
        indexedGitHead
        currentGitHead
        generatedAt
        staleReasons
      }
      identity {
        name
        summary
        confidence
        evidence { source path line symbol artifactKey description }
      }
      footprint {
        fileCount
        lineCount
        symbolCount
        domainCount
        languages { name files lines percent }
      }
      domains(limit: 100) {
        id
        label
        summary
        confidence
        fileCount
        symbolCount
        representativeFiles
        representativeSymbols
        dependsOn
        usedBy
        evidence { source path line symbol artifactKey description }
        lane
      }
      relationships(limit: 100) {
        source
        target
        weight
        evidenceType
        sampleReferences { sourceSymbol targetSymbol }
      }
      commands {
        purpose
        command
        workingDirectory
        confidence
        evidence { source path line symbol artifactKey description }
      }
      hotspots(limit: 20) {
        symbolId
        name
        file
        line
        domainId
        reason
        blastRadius
        dependents
      }
      conventions(limit: 10) {
        text
        scope
        confidence
        evidence { source path line symbol artifactKey description }
      }
      risks(limit: 10) {
        type
        description
        severity
        domainId
        evidence { source path line symbol artifactKey description }
      }
      gaps {
        type
        description
        evidence { source path line symbol artifactKey description }
      }
      readiness {
        capability
        status
        reason
        remediation
      }
      warnings
      coverageStats {
        sourceFilesTotal
        sourceFilesParsed
        parseCoveragePct
        symbolsExtracted
        referencesExtracted
      }
      entrypoints {
        name
        file
        kind
      }
      annotatedTree {
        path
        fileCount
        totalLines
        dominantDomainLabel
      }
      readingPath {
        file
        reason
        kind
      }
      approvedKnowledge {
        id
        knowledge
        whyItMatters
        appliesTo
        lastVerified
        stalenessFlag
      }
      pendingKnowledge {
        id
        knowledge
        whyItMatters
        appliesTo
        source
        draftReason
      }
      apiData {
        routes { method path file line handler framework evidence { source path line symbol artifactKey description } }
        entities {
          name file line tableName language columnsInferred
          columns { name type primaryKey }
          relationships { field targetEntity cardinality }
          evidence { source path line symbol artifactKey description }
        }
        persistenceSummary { mode entityCount byLanguage }
      }
      cicd {
        workflows {
          name provider configFile triggers
          jobs { name runsOn needs commands }
          evidence { source path line symbol artifactKey description }
        }
        otherProvidersDetected { provider configFile evidence { source path line symbol artifactKey description } }
      }
      runtimeConfig {
        runtimes { language version sourceFile evidence { source path line symbol artifactKey description } }
        frameworks { name version sourceFile evidence { source path line symbol artifactKey description } }
        configSources { file evidence { source path line symbol artifactKey description } }
        environmentVariables { name sourceFile looksSensitive evidence { source path line symbol artifactKey description } }
      }
      security {
        secretIndicators { category patternType name file line redacted evidence { source path line symbol artifactKey description } }
        sensitiveConfiguration { category title description severity file line evidence { source path line symbol artifactKey description } }
        authenticationIndicators { type name file line evidence { source path line symbol artifactKey description } }
        securityToolingDetected { name file evidence { source path line symbol artifactKey description } }
      }
      changesHistory {
        status
        previousSnapshot { generatedAt gitHead identityName schemaVersion }
        currentSnapshot { generatedAt gitHead identityName schemaVersion }
        summary
        warnings
        sections {
          key
          label
          available
          reason
          added { key title evidence { source path line symbol artifactKey description } }
          removed { key title evidence { source path line symbol artifactKey description } }
          changed {
            key
            title
            fields { field before after }
            evidence { source path line symbol artifactKey description }
          }
        }
      }
    }
  }
`;

export const REPOSITORY_DIGEST_STATUS_QUERY = gql`
  query RepositoryDigestStatus {
    repositoryDigestStatus {
      state
      startedAt
      completedAt
      lastError
      hasReadableDigest
      hasProjectMap
      indexedGitHead
      currentGitHead
      staleReasons
    }
  }
`;

export const REFRESH_REPOSITORY_DIGEST_MUTATION = gql`
  mutation RefreshRepositoryDigest($rebuildDiscovery: Boolean!, $narrative: Boolean!) {
    refreshRepositoryDigest(rebuildDiscovery: $rebuildDiscovery, narrative: $narrative) {
      accepted
      state
      message
      hasReadableDigest
    }
  }
`;

export const REPOSITORY_DIGEST_UPDATED_SUBSCRIPTION = gql`
  subscription RepositoryDigestUpdated {
    repositoryDigestUpdated {
      state
      startedAt
      completedAt
      lastError
      hasReadableDigest
      hasProjectMap
      indexedGitHead
      currentGitHead
      staleReasons
    }
  }
`;

// ── TypeScript types (mirroring the GraphQL shapes above) ────────

export type DigestConfidence = "CONFIRMED" | "DERIVED" | "INFERRED" | "UNKNOWN";
export type DigestEffectiveState = "MISSING" | "GENERATING" | "CURRENT" | "STALE" | "ERROR";
export type DigestCapabilityStatus = "AVAILABLE" | "PARTIAL" | "UNAVAILABLE" | "INVALID" | "STALE";

export interface DigestEvidence {
  source: string;
  path: string | null;
  line: number | null;
  symbol: string | null;
  artifactKey: string | null;
  description: string;
}

export type DigestLane = "frontend" | "api" | "services" | "data" | "other";

export interface DigestDomain {
  id: string;
  label: string;
  summary: string;
  confidence: DigestConfidence;
  fileCount: number;
  symbolCount: number;
  representativeFiles: string[];
  representativeSymbols: string[];
  dependsOn: string[];
  usedBy: string[];
  evidence: DigestEvidence[];
  lane: DigestLane;
}

export interface DigestSymbolReference {
  sourceSymbol: string;
  targetSymbol: string;
}

export interface DigestRelationship {
  source: string;
  target: string;
  weight: number;
  evidenceType: string;
  sampleReferences: DigestSymbolReference[];
}

export interface DigestCommand {
  purpose: string;
  command: string;
  workingDirectory: string;
  confidence: DigestConfidence;
  evidence: DigestEvidence[];
}

export interface DigestHotspot {
  symbolId: string;
  name: string;
  file: string;
  line: number;
  domainId: string;
  reason: string;
  blastRadius: number;
  dependents: number;
}

export interface DigestConvention {
  text: string;
  scope: string[];
  confidence: DigestConfidence;
  evidence: DigestEvidence[];
}

export interface DigestRisk {
  type: string;
  description: string;
  severity: string;
  domainId: string;
  evidence: DigestEvidence[];
}

export interface DigestGap {
  type: string;
  description: string;
  evidence: DigestEvidence[];
}

export interface DigestReadiness {
  capability: string;
  status: DigestCapabilityStatus;
  reason: string | null;
  remediation: string | null;
}

export interface DigestEntrypoint {
  name: string;
  file: string;
  kind: string;
}

export interface DigestCoverageStats {
  sourceFilesTotal: number;
  sourceFilesParsed: number;
  parseCoveragePct: number | null;
  symbolsExtracted: number | null;
  referencesExtracted: number | null;
}

export interface DigestAnnotatedDirectory {
  path: string;
  fileCount: number;
  totalLines: number;
  dominantDomainLabel: string | null;
}

export interface DigestReadingPathItem {
  file: string;
  reason: string;
  kind: string;
}

export interface DigestKnowledgeEntry {
  id: string;
  knowledge: string;
  whyItMatters: string;
  appliesTo: string[];
  lastVerified: string | null;
  stalenessFlag: string;
}

export interface DigestKnowledgeDraft {
  id: string;
  knowledge: string;
  whyItMatters: string;
  appliesTo: string[];
  source: string;
  draftReason: string;
}

export interface DigestRoute {
  method: string;
  path: string;
  file: string;
  line: number;
  handler: string;
  framework: string;
  evidence: DigestEvidence[];
}

export interface DigestEntityColumn {
  name: string;
  type: string;
  primaryKey: boolean;
}

export interface DigestEntityRelationship {
  field: string;
  targetEntity: string | null;
  cardinality: string;
}

export interface DigestEntity {
  name: string;
  file: string | null;
  line: number | null;
  tableName: string | null;
  language: string | null;
  columns: DigestEntityColumn[];
  columnsInferred: boolean;
  relationships: DigestEntityRelationship[];
  evidence: DigestEvidence[];
}

export interface DigestPersistenceSummary {
  mode: string;
  entityCount: number;
  byLanguage: Record<string, number>;
}

export interface DigestApiData {
  routes: DigestRoute[];
  entities: DigestEntity[];
  persistenceSummary: DigestPersistenceSummary | null;
}

export interface DigestCiJob {
  name: string;
  runsOn: string | null;
  needs: string[];
  commands: string[];
}

export interface DigestCiWorkflow {
  name: string;
  provider: string;
  configFile: string;
  triggers: string[];
  jobs: DigestCiJob[];
  evidence: DigestEvidence[];
}

export interface DigestOtherCiProvider {
  provider: string;
  configFile: string;
  evidence: DigestEvidence[];
}

export interface DigestCicd {
  workflows: DigestCiWorkflow[];
  otherProvidersDetected: DigestOtherCiProvider[];
}

export interface DigestRuntime {
  language: string;
  version: string | null;
  sourceFile: string;
  evidence: DigestEvidence[];
}

export interface DigestFramework {
  name: string;
  version: string | null;
  sourceFile: string;
  evidence: DigestEvidence[];
}

export interface DigestConfigSource {
  file: string;
  evidence: DigestEvidence[];
}

export interface DigestEnvironmentVariable {
  name: string;
  sourceFile: string;
  looksSensitive: boolean;
  evidence: DigestEvidence[];
}

export interface DigestRuntimeConfig {
  runtimes: DigestRuntime[];
  frameworks: DigestFramework[];
  configSources: DigestConfigSource[];
  environmentVariables: DigestEnvironmentVariable[];
}

export interface DigestSecretIndicator {
  category: string;
  patternType: string | null;
  name: string;
  file: string;
  line: number | null;
  redacted: boolean;
  evidence: DigestEvidence[];
}

export interface DigestSensitiveConfigFinding {
  category: string;
  title: string;
  description: string;
  severity: string | null;
  file: string;
  line: number | null;
  evidence: DigestEvidence[];
}

export interface DigestAuthIndicator {
  type: string;
  name: string;
  file: string;
  line: number | null;
  evidence: DigestEvidence[];
}

export interface DigestSecurityTool {
  name: string;
  file: string;
  evidence: DigestEvidence[];
}

export interface DigestSecurity {
  secretIndicators: DigestSecretIndicator[];
  sensitiveConfiguration: DigestSensitiveConfigFinding[];
  authenticationIndicators: DigestAuthIndicator[];
  securityToolingDetected: DigestSecurityTool[];
}

export type DigestChangesStatus = "FIRST_RUN" | "COMPARED";

export interface DigestSnapshotMeta {
  generatedAt: string | null;
  gitHead: string | null;
  identityName: string | null;
  schemaVersion: number | null;
}

export interface DigestChangeItem {
  key: string;
  title: string;
  evidence: DigestEvidence[];
}

export interface DigestChangeFieldDiff {
  field: string;
  before: unknown;
  after: unknown;
}

export interface DigestChangedItem {
  key: string;
  title: string;
  fields: DigestChangeFieldDiff[];
  evidence: DigestEvidence[];
}

export interface DigestChangeSection {
  key: string;
  label: string;
  available: boolean;
  reason: string | null;
  added: DigestChangeItem[];
  removed: DigestChangeItem[];
  changed: DigestChangedItem[];
}

export interface DigestChangesHistory {
  status: DigestChangesStatus;
  previousSnapshot: DigestSnapshotMeta | null;
  currentSnapshot: DigestSnapshotMeta | null;
  summary: string[];
  warnings: string[];
  sections: DigestChangeSection[];
}

export interface RepositoryDigestData {
  schemaVersion: number;
  status: "COMPLETE" | "PARTIAL" | "FAILED";
  effectiveState: DigestEffectiveState;
  generatedAt: string;
  freshness: {
    state: string;
    indexedGitHead: string | null;
    currentGitHead: string | null;
    generatedAt: string | null;
    staleReasons: string[];
  };
  identity: { name: string; summary: string; confidence: DigestConfidence; evidence: DigestEvidence[] };
  footprint: {
    fileCount: number;
    lineCount: number;
    symbolCount: number | null;
    domainCount: number | null;
    languages: { name: string; files: number; lines: number; percent: number }[];
  };
  domains: DigestDomain[];
  relationships: DigestRelationship[];
  commands: DigestCommand[];
  hotspots: DigestHotspot[];
  conventions: DigestConvention[];
  risks: DigestRisk[];
  gaps: DigestGap[];
  readiness: DigestReadiness[];
  warnings: string[];
  coverageStats: DigestCoverageStats | null;
  entrypoints: DigestEntrypoint[];
  annotatedTree: DigestAnnotatedDirectory[];
  readingPath: DigestReadingPathItem[];
  approvedKnowledge: DigestKnowledgeEntry[];
  pendingKnowledge: DigestKnowledgeDraft[];
  apiData: DigestApiData | null;
  cicd: DigestCicd | null;
  runtimeConfig: DigestRuntimeConfig | null;
  security: DigestSecurity | null;
  changesHistory: DigestChangesHistory | null;
}

export interface RepositoryDigestBuildStatus {
  state: DigestEffectiveState;
  startedAt: string | null;
  completedAt: string | null;
  lastError: string | null;
  hasReadableDigest: boolean;
  hasProjectMap: boolean;
  indexedGitHead: string | null;
  currentGitHead: string | null;
  staleReasons: string[];
}
