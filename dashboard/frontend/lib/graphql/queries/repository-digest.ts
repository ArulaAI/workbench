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
      domains(limit: 10) {
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
      }
      commands {
        purpose
        command
        workingDirectory
        confidence
        evidence { source path line symbol artifactKey description }
      }
      hotspots(limit: 10) {
        symbolId
        name
        file
        line
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
  commands: DigestCommand[];
  hotspots: DigestHotspot[];
  conventions: DigestConvention[];
  risks: DigestRisk[];
  gaps: DigestGap[];
  readiness: DigestReadiness[];
  warnings: string[];
}

export interface RepositoryDigestBuildStatus {
  state: DigestEffectiveState;
  startedAt: string | null;
  completedAt: string | null;
  lastError: string | null;
  hasReadableDigest: boolean;
  indexedGitHead: string | null;
  currentGitHead: string | null;
  staleReasons: string[];
}
