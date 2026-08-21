import { gql } from "urql";

export const TOKEN_BURN_QUERY = gql`
  query TokenBurn($feature: String, $agentType: String, $model: String, $limit: Int) {
    tokenBurn(feature: $feature, agentType: $agentType, model: $model, limit: $limit) {
      id
      feature
      agentType
      subtype
      isError
      durationMs
      numTurns
      totalCostUsd
      inputTokens
      outputTokens
      cacheCreationTokens
      cacheReadTokens
      sourceFile
      createdAt
      models
    }
  }
`;

export const TOKEN_BURN_AGGREGATE_QUERY = gql`
  query TokenBurnAggregate($groupBy: GroupBy!, $feature: String) {
    tokenBurnAggregate(groupBy: $groupBy, feature: $feature) {
      groupKey
      runCount
      totalCostUsd
      totalInputTokens
      totalOutputTokens
      totalCacheReadTokens
      totalCacheCreationTokens
    }
  }
`;

export const TOKEN_BURN_TIME_SERIES_QUERY = gql`
  query TokenBurnTimeSeries($feature: String, $bucketMinutes: Int) {
    tokenBurnTimeSeries(feature: $feature, bucketMinutes: $bucketMinutes) {
      bucket
      costUsd
      cumulativeCostUsd
      runCount
      totalTokens
    }
  }
`;

export const AGENT_RUN_SUBSCRIPTION = gql`
  subscription AgentRunCompleted($feature: String) {
    agentRunCompleted(feature: $feature) {
      feature
      runId
      cost
    }
  }
`;
