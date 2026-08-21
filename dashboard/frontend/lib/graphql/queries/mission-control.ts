import { gql } from "urql";

export const MISSION_CONTROL_QUERY = gql`
  query MissionControl($feature: String!) {
    missionControl(feature: $feature) {
      feature
      status
      taskCount
      statusCounts {
        pending
        running
        done
        failed
        reviewing
      }
      tasks {
        id
        title
        status
        agentModel
        dependsOn
        branch
        acceptanceCriteria
        filesTouched
        error
        reviewFeedback
        retryCount
        createdAt
        startedAt
        completedAt
      }
      crossTaskAnalysis
    }
  }
`;

export const TASK_STATUS_SUBSCRIPTION = gql`
  subscription TaskStatusChanged($feature: String!) {
    taskStatusChanged(feature: $feature) {
      feature
      taskId
      status
    }
  }
`;
