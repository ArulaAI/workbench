import { gql } from "urql";

export interface SpecDoc {
  exists: boolean;
  path: string | null;
  auditStatus: string;
  warningCount: number;
  warnings: string[];
}

export interface AdditionalSpec {
  path: string;
  specType: string;
  auditStatus: string;
  warningCount: number;
}

export interface SpecifiedData {
  productSpec: SpecDoc;
  technicalSpec: SpecDoc;
  designSpec: SpecDoc;
  additionalSpecs: AdditionalSpec[];
  openQuestions: number;
  sizingEstimate: number | null;
}

export interface BuiltData {
  coveragePct: number | null;
  criteriaPassed: number | null;
  criteriaTotal: number | null;
  guardianVerdict: string | null;
  taskProgress: number | null;
  tasksDone: number | null;
  tasksTotal: number | null;
  blockedCount: number;
  completedAt: string | null;
}

export interface Escalation {
  description: string;
  linkedWarningId: string | null;
}

export interface GapData {
  escalationCount: number;
  escalations: Escalation[];
  unverifiableCount: number;
  reworkCount: number;
}

export interface DefineFeature {
  name: string;
  state: string;
  specified: SpecifiedData;
  built: BuiltData;
  gap: GapData;
}

export interface DefectData {
  name: string;
  severity: string;
  status: string;
  description: string;
  impact: string | null;
  filedAt: string | null;
}

export interface DefineAggregates {
  designSpecCount: number;
  featureCount: number;
  auditWarningCount: number;
  openQuestionCount: number;
  escalationCount: number;
  completedCount: number;
  executingCount: number;
  unplannedCount: number;
}

export interface DefineViewData {
  defineView: {
    visionStatus: string;
    visionPath: string | null;
    features: DefineFeature[];
    defects: DefectData[];
    aggregates: DefineAggregates;
  };
}

export const DEFINE_VIEW_QUERY = gql`
  query DefineView($feature: String) {
    defineView(feature: $feature) {
      visionStatus
      visionPath
      features {
        name
        state
        specified {
          productSpec {
            exists
            path
            auditStatus
            warningCount
            warnings
          }
          technicalSpec {
            exists
            path
            auditStatus
            warningCount
            warnings
          }
          designSpec {
            exists
            path
            auditStatus
            warningCount
            warnings
          }
          additionalSpecs {
            path
            specType
            auditStatus
            warningCount
          }
          openQuestions
          sizingEstimate
        }
        built {
          coveragePct
          criteriaPassed
          criteriaTotal
          guardianVerdict
          taskProgress
          tasksDone
          tasksTotal
          blockedCount
          completedAt
        }
        gap {
          escalationCount
          escalations {
            description
            linkedWarningId
          }
          unverifiableCount
          reworkCount
        }
      }
      defects {
        name
        severity
        status
        description
        impact
        filedAt
      }
      aggregates {
        designSpecCount
        featureCount
        auditWarningCount
        openQuestionCount
        escalationCount
        completedCount
        executingCount
        unplannedCount
      }
    }
  }
`;
