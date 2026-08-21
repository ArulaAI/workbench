import { gql } from "urql";

export { TASK_STATUS_SUBSCRIPTION } from "./mission-control";

// TypeScript types matching the GraphQL schema (Strawberry snake_case → camelCase)

export interface DraftSpec {
  name: string;
  specTypes: string[];
  status: string;
}

export interface Defect {
  severity: string;
  name: string;
}

export interface DefinePanel {
  visionStatus: string;
  draftSpecs: DraftSpec[];
  defects: Defect[];
  defectCount: number;
}

export interface DecisionItem {
  title: string;
  description: string;
}

export interface CompletedFeature {
  feature: string;
  completedAt: string | null;
  coveragePct: number;
  criteriaPassed: number;
  criteriaTotal: number;
  guardianVerdict: string;
  decisionsNeeded: number;
  decisionItems: DecisionItem[];
  reviewStatus: string;
  summary: string | null;
}

export interface QualityGate {
  name: string;
  status: string;
  detail: string | null;
}

export interface JudgePanel {
  completedFeatures: CompletedFeature[];
  qualityGates: QualityGate[];
  totalFeatures: number;
  awaitingReview: number;
}

export interface RunningFeature {
  name: string;
  progressPct: number;
  tasksCompleted: number;
  tasksTotal: number;
  blockedCount: number;
}

export interface Escalation {
  feature: string;
  taskId: string;
  taskTitle: string;
  question: string;
}

export interface RecentFeature {
  name: string;
  completedAt: string | null;
  coveragePct: number;
  tasksCompleted: number;
  tasksTotal: number;
}

export interface ExecutePanel {
  runningFeatures: RunningFeature[];
  recentFeatures: RecentFeature[];
  escalations: Escalation[];
}

export interface CoverageTrend {
  feature: string;
  coveragePct: number;
}

export interface Insight {
  type: string;
  text: string;
}

export interface EscalationTrend {
  feature: string;
  count: number;
}

export interface LearnPanel {
  coverageTrend: CoverageTrend[];
  insights: Insight[];
  escalationTrend: EscalationTrend[];
}

export interface LandingViewData {
  landingView: {
    greeting: string;
    projectName: string;
    branch: string | null;
    narrative: string | null;
    define: DefinePanel;
    judge: JudgePanel;
    execute: ExecutePanel;
    learn: LearnPanel;
  };
}

export interface EscalationResponseData {
  respondToEscalation: {
    success: boolean;
    error: string | null;
  };
}

export const LANDING_VIEW_QUERY = gql`
  query LandingView {
    landingView {
      greeting
      projectName
      branch
      narrative
      define {
        visionStatus
        draftSpecs {
          name
          specTypes
          status
        }
        defects {
          severity
          name
        }
        defectCount
      }
      judge {
        completedFeatures {
          feature
          completedAt
          coveragePct
          criteriaPassed
          criteriaTotal
          guardianVerdict
          decisionsNeeded
          decisionItems {
            title
            description
          }
          reviewStatus
          summary
        }
        qualityGates {
          name
          status
          detail
        }
        totalFeatures
        awaitingReview
      }
      execute {
        runningFeatures {
          name
          progressPct
          tasksCompleted
          tasksTotal
          blockedCount
        }
        recentFeatures {
          name
          completedAt
          coveragePct
          tasksCompleted
          tasksTotal
        }
        escalations {
          feature
          taskId
          taskTitle
          question
        }
      }
      learn {
        coverageTrend {
          feature
          coveragePct
        }
        insights {
          type
          text
        }
        escalationTrend {
          feature
          count
        }
      }
    }
  }
`;

export const RESPOND_TO_ESCALATION_MUTATION = gql`
  mutation RespondToEscalation(
    $feature: String!
    $taskId: String!
    $response: String!
  ) {
    respondToEscalation(feature: $feature, taskId: $taskId, response: $response) {
      success
      error
    }
  }
`;
