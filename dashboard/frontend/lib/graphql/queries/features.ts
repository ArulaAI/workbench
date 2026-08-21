import { gql } from "urql";

export const FEATURES_QUERY = gql`
  query Features {
    features {
      name
      status
      startedAt
      taskCount
    }
  }
`;

export const PROJECT_QUERY = gql`
  query Project {
    project {
      id
      name
      rootPath
      gitRemote
      gitHead
    }
  }
`;
