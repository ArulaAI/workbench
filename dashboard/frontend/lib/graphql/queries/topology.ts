import { gql } from "urql";

export const TOPOLOGY_QUERY = gql`
  query CodebaseTopology {
    codebaseTopology {
      generatedAt
      gitHead
      nodeCount
      edgeCount
      clusterCount
      clusters {
        id
        symbolCount
        files
        kinds
        avgBlastRadius
      }
      clusterEdges {
        source
        target
        type
      }
    }
  }
`;

export const TOPOLOGY_FULL_QUERY = gql`
  query CodebaseTopologyFull {
    codebaseTopology {
      generatedAt
      gitHead
      nodeCount
      edgeCount
      clusterCount
      nodes {
        id
        name
        kind
        file
        line
        cluster
        impact {
          blastRadius
          centrality
          dependents
          stability
        }
      }
      edges {
        source
        target
        type
      }
      clusters {
        id
        symbolCount
        files
        kinds
        avgBlastRadius
      }
      clusterEdges {
        source
        target
        type
      }
    }
  }
`;

export const CLUSTER_DETAIL_QUERY = gql`
  query ClusterDetail($clusterId: String!) {
    clusterDetail(clusterId: $clusterId) {
      clusterId
      nodes {
        id
        name
        kind
        file
        line
        cluster
        impact {
          blastRadius
          centrality
          dependents
          stability
        }
      }
      internalEdges {
        source
        target
        type
      }
      externalEdges {
        source
        target
        type
      }
    }
  }
`;
