import { gql } from "urql";

// ── Types ────────────────────────────────────────────────────────

export interface DismissedSummary {
  count: number;
  reasons: string[];
}

export interface SuggestionHistory {
  received: number;
  accepted: number;
  dismissed: DismissedSummary;
}

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

export interface SpecClaimInfo {
  specType: string;
  claimant: string;
  claimantEmail: string;
  claimedAt: string;
  lastActivityAt: string;
  releasedAt: string | null;
}

export interface SpecProgressInfo {
  specType: string;
  claim: SpecClaimInfo | null;
  hasCommit: boolean;
  committer: string | null;
  committerEmail: string | null;
  hasRatification: boolean;
  ratified: boolean;
  hasRejection: boolean;
  approvalCount: number;
  hasVoted: boolean;
  ratificationThreshold: number;
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

// ── Query/Mutation response types ────────────────────────────────

export interface CommitRecordData {
  commitRecord: CommitRecord | null;
}

export interface CommitRecordVars {
  featureName: string;
  specType: string;
}

export interface RatificationStateData {
  ratificationState: RatificationState | null;
}

export interface RatificationStateVars {
  featureName: string;
  specType: string;
}

export interface CommitSpecData {
  commitSpec: CommitRecord;
}

export interface CommitSpecVars {
  featureName: string;
  specType: string;
}

export interface SubmitRatificationData {
  submitRatification: RatificationState;
}

export interface SubmitRatificationVars {
  featureName: string;
  specType: string;
  verdict: string;
  comment?: string;
}

export interface CeremonyClaimsData {
  ceremonyClaims: SpecClaimInfo[];
}

export interface CeremonyClaimsVars {
  featureName: string;
}

export interface ClaimSpecData {
  claimSpec: SpecClaimInfo;
}

export interface ClaimSpecVars {
  featureName: string;
  specType: string;
}

export interface ReleaseSpecData {
  releaseSpec: SpecClaimInfo;
}

export interface ReleaseSpecVars {
  featureName: string;
  specType: string;
}

export interface CeremonyProgressData {
  ceremonyProgress: SpecProgressInfo[];
}

export interface CeremonyProgressVars {
  featureName: string;
}

// ── Queries ──────────────────────────────────────────────────────

export const COMMIT_RECORD_QUERY = gql`
  query CommitRecord($featureName: String!, $specType: String!) {
    commitRecord(featureName: $featureName, specType: $specType) {
      featureName
      specType
      revisionId
      claimant
      claimantEmail
      committedAt
      validationStateRef
      contextPackageRef
      suggestionHistory {
        received
        accepted
        dismissed { count reasons }
      }
      specPath
      decompositionRef
      isMultiplayer
      ratificationThreshold
      ratificationStatus
    }
  }
`;

export const RATIFICATION_STATE_QUERY = gql`
  query RatificationState($featureName: String!, $specType: String!) {
    ratificationState(featureName: $featureName, specType: $specType) {
      featureName
      revisionId
      status
      ratificationCount
      threshold
      verdicts {
        id
        revisionId
        actor
        actorEmail
        verdict
        comment
        timestamp
      }
      isAuthor
      hasVoted
    }
  }
`;

export const CEREMONY_CLAIMS_QUERY = gql`
  query CeremonyClaims($featureName: String!) {
    ceremonyClaims(featureName: $featureName) {
      specType
      claimant
      claimantEmail
      claimedAt
      lastActivityAt
      releasedAt
    }
  }
`;

export const CEREMONY_PROGRESS_QUERY = gql`
  query CeremonyProgress($featureName: String!) {
    ceremonyProgress(featureName: $featureName) {
      specType
      claim {
        specType
        claimant
        claimantEmail
        claimedAt
        lastActivityAt
        releasedAt
      }
      hasCommit
      committer
      committerEmail
      hasRatification
      ratified
      hasRejection
      approvalCount
      hasVoted
      ratificationThreshold
    }
  }
`;

// ── Mutations ────────────────────────────────────────────────────

export const COMMIT_SPEC_MUTATION = gql`
  mutation CommitSpec($featureName: String!, $specType: String!) {
    commitSpec(featureName: $featureName, specType: $specType) {
      featureName
      specType
      revisionId
      claimant
      claimantEmail
      committedAt
      ratificationStatus
    }
  }
`;

export const SUBMIT_RATIFICATION_MUTATION = gql`
  mutation SubmitRatification(
    $featureName: String!,
    $specType: String!,
    $verdict: String!,
    $comment: String
  ) {
    submitRatification(
      featureName: $featureName,
      specType: $specType,
      verdict: $verdict,
      comment: $comment
    ) {
      featureName
      status
      ratificationCount
      threshold
      verdicts {
        id
        actor
        verdict
        comment
        timestamp
      }
      isAuthor
      hasVoted
    }
  }
`;

export const CLAIM_SPEC_MUTATION = gql`
  mutation ClaimSpec($featureName: String!, $specType: String!) {
    claimSpec(featureName: $featureName, specType: $specType) {
      specType
      claimant
      claimantEmail
      claimedAt
      lastActivityAt
      releasedAt
    }
  }
`;

export const RELEASE_SPEC_MUTATION = gql`
  mutation ReleaseSpec($featureName: String!, $specType: String!) {
    releaseSpec(featureName: $featureName, specType: $specType) {
      specType
      claimant
      claimantEmail
      claimedAt
      lastActivityAt
      releasedAt
    }
  }
`;
