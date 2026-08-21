import { gql } from "urql";

// ── Types ───────────────────────────────────────────────────────

export interface AgentProcess {
  taskId: string;
  pid: number;
  alive: boolean;
  agentType: string | null;
}

export interface StaleProcess {
  taskId: string;
  pid: number;
  pidFile: string;
  agentType: string | null;
}

export interface FeatureProcessState {
  name: string;
  orchestratorRunning: boolean;
  startedAt: string | null;
  agents: AgentProcess[];
  supportAgents: AgentProcess[];
  staleProcesses: StaleProcess[];
}

export interface ProcessStatusData {
  processStatus: {
    activeFeature: string | null;
    features: FeatureProcessState[];
  };
}

// ── Queries ─────────────────────────────────────────────────────

export const PROCESS_STATUS_QUERY = gql`
  query ProcessStatus {
    processStatus {
      activeFeature
      features {
        name
        orchestratorRunning
        startedAt
        agents {
          taskId
          pid
          alive
          agentType
        }
        supportAgents {
          taskId
          pid
          alive
          agentType
        }
        staleProcesses {
          taskId
          pid
          pidFile
          agentType
        }
      }
    }
  }
`;

// ── Subscriptions ───────────────────────────────────────────────

export const PROCESS_STATUS_SUBSCRIPTION = gql`
  subscription ProcessStatusChanged($feature: String) {
    processStatusChanged(feature: $feature) {
      feature
    }
  }
`;
