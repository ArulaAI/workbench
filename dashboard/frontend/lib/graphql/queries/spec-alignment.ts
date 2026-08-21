import { gql } from "urql";

export interface ClaimSource {
  specFile: string;
  section: string;
  line: number;
}

export interface SpecAlignmentClaim {
  source: ClaimSource;
  claimType: string;
  claimText: string;
  entity: string;
  status: string;
  evidence: string | null;
  divergence: string | null;
}

export interface SpecAlignmentSection {
  section: string;
  claimCount: number;
  confirmed: number;
  missing: number;
  unverifiable: number;
  coveragePct: number;
  claims: SpecAlignmentClaim[];
}

export interface SpecAlignmentSpec {
  specFile: string;
  totalClaims: number;
  confirmed: number;
  coveragePct: number;
  sections: SpecAlignmentSection[];
}

export interface SpecAlignmentView {
  totalClaims: number;
  totalConfirmed: number;
  totalMissing: number;
  totalUnverifiable: number;
  overallCoveragePct: number;
  specs: SpecAlignmentSpec[];
}

export const SPEC_ALIGNMENT_QUERY = gql`
  query SpecAlignment($specFile: String) {
    specAlignment(specFile: $specFile) {
      totalClaims
      totalConfirmed
      totalMissing
      totalUnverifiable
      overallCoveragePct
      specs {
        specFile
        totalClaims
        confirmed
        coveragePct
        sections {
          section
          claimCount
          confirmed
          missing
          unverifiable
          coveragePct
          claims {
            source {
              specFile
              section
              line
            }
            claimType
            claimText
            entity
            status
            evidence
            divergence
          }
        }
      }
    }
  }
`;
