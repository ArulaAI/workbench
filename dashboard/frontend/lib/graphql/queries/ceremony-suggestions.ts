import { gql } from "urql";

// ── Types ────────────────────────────────────────────────────────

export interface SuggestionResolution {
  action: string;
  resolvedBy: string;
  resolvedByEmail: string;
  resolvedAt: string;
  reason: string | null;
}

export interface SuggestionReply {
  id: string;
  author: string;
  authorEmail: string;
  text: string;
  createdAt: string;
}

export interface Suggestion {
  id: string;
  author: string;
  authorEmail: string;
  revisionId: string;
  sectionId: string;
  sectionTitle: string;
  sectionContentHash: string;
  text: string;
  status: string;
  outdated: boolean;
  createdAt: string;
  updatedAt: string | null;
  resolution: SuggestionResolution | null;
  thread: SuggestionReply[];
  specType: string;
}

export interface DismissedSummary {
  count: number;
  reasons: string[];
}

export interface SuggestionHistory {
  received: number;
  accepted: number;
  dismissed: DismissedSummary;
}

// ── Query/Mutation response types ────────────────────────────────

export interface SuggestionsData {
  suggestions: Suggestion[];
}

export interface SuggestionsVars {
  featureName: string;
}

export interface SuggestionHistoryData {
  suggestionHistory: SuggestionHistory;
}

export interface CreateSuggestionData {
  createSuggestion: Suggestion;
}

export interface CreateSuggestionVars {
  featureName: string;
  specType: string;
  sectionId: string;
  sectionTitle: string;
  text: string;
}

export interface ResolveSuggestionData {
  resolveSuggestion: Suggestion;
}

export interface ResolveSuggestionVars {
  featureName: string;
  suggestionId: string;
  action: string;
  reason?: string;
}

export interface ReplySuggestionData {
  replySuggestion: SuggestionReply;
}

export interface ReplySuggestionVars {
  featureName: string;
  suggestionId: string;
  text: string;
}

// ── Fragments ────────────────────────────────────────────────────

const SUGGESTION_FIELDS = `
  fragment SuggestionFields on Suggestion {
    id
    author
    authorEmail
    revisionId
    sectionId
    sectionTitle
    sectionContentHash
    text
    status
    outdated
    createdAt
    updatedAt
    specType
    resolution {
      action
      resolvedBy
      resolvedByEmail
      resolvedAt
      reason
    }
    thread {
      id
      author
      authorEmail
      text
      createdAt
    }
  }
`;

// ── Queries ──────────────────────────────────────────────────────

export const SUGGESTIONS_QUERY = gql`
  ${SUGGESTION_FIELDS}
  query Suggestions($featureName: String!) {
    suggestions(featureName: $featureName) {
      ...SuggestionFields
    }
  }
`;

export const SUGGESTION_HISTORY_QUERY = gql`
  query SuggestionHistory($featureName: String!) {
    suggestionHistory(featureName: $featureName) {
      received
      accepted
      dismissed {
        count
        reasons
      }
    }
  }
`;

// ── Mutations ────────────────────────────────────────────────────

export const CREATE_SUGGESTION_MUTATION = gql`
  ${SUGGESTION_FIELDS}
  mutation CreateSuggestion(
    $featureName: String!,
    $specType: String!,
    $sectionId: String!,
    $sectionTitle: String!,
    $text: String!
  ) {
    createSuggestion(
      featureName: $featureName,
      specType: $specType,
      sectionId: $sectionId,
      sectionTitle: $sectionTitle,
      text: $text
    ) {
      ...SuggestionFields
    }
  }
`;

export const RESOLVE_SUGGESTION_MUTATION = gql`
  ${SUGGESTION_FIELDS}
  mutation ResolveSuggestion($featureName: String!, $suggestionId: String!, $action: String!, $reason: String) {
    resolveSuggestion(featureName: $featureName, suggestionId: $suggestionId, action: $action, reason: $reason) {
      ...SuggestionFields
    }
  }
`;

export const REPLY_SUGGESTION_MUTATION = gql`
  mutation ReplySuggestion($featureName: String!, $suggestionId: String!, $text: String!) {
    replySuggestion(featureName: $featureName, suggestionId: $suggestionId, text: $text) {
      id
      author
      authorEmail
      text
      createdAt
    }
  }
`;

export const DELETE_SUGGESTION_MUTATION = gql`
  mutation DeleteSuggestion($featureName: String!, $suggestionId: String!) {
    deleteSuggestion(featureName: $featureName, suggestionId: $suggestionId)
  }
`;
