import { gql } from 'urql';

export const DOMAIN_DETAIL_QUERY = gql`
  query DomainDetail($id: ID!, $build: ID!, $activityAfter: String, $ruleAfter: String, $evidenceAfter: String,
    $conceptAfter: String, $ownershipAfter: String, $claimAfter: String) {
    domain(id: $id, expectedBuildId: $build) {
      error { code message }
      domain {
        id name boundaryRationale unresolvedQuestions support reviewState
        exclusions {explanation} alternatives {explanation}
        concepts(first:20,after:$conceptAfter) {
          edges {cursor node {id name qualifiedTypeNames}}
          pageInfo {endCursor hasNextPage} error {code message}
        }
        ownerships(first:20,after:$ownershipAfter) {
          edges {cursor node {id kind rationale support unresolvedQuestions concept {id name}}}
          pageInfo {endCursor hasNextPage} error {code message}
        }
        claims(first:20,after:$claimAfter) {
          edges {cursor node {id text kind semanticReview evidenceIds}}
          pageInfo {endCursor hasNextPage} error {code message}
        }
        activities(first:20, after:$activityAfter) {
          edges { cursor node { id name description implementationStatus support unresolvedQuestions inputBindingIds outputBindingIds
            inputs {id name valueType expression resolution reason}
            outputs {id name valueType expression resolution reason}
            traces {id resolution reason stopReasons uiInteraction {
              elements {id kind label routePatterns {pattern} routingResolution reason}
              events {id trigger resolution reason}
              validations {id enforcement resolution reason}
              calls {id resolution reason}
              outputs {id kind resolution reason}
            }}
          } }
          pageInfo {endCursor hasNextPage} error {code message}
        }
        rules(first:20, after:$ruleAfter) {
          edges { cursor node { id name description predicateOrFormula outcome enforcementStatus support unresolvedQuestions
            observations {id sourceLocationKind nativeExpression resolution reason}
            relationships {id kind verification explanation fromObservationId toObservationId}
          } }
          pageInfo {endCursor hasNextPage} error {code message}
        }
        implementationEvidence(first:20, after:$evidenceAfter) {
          edges { cursor node { id sourceKind claimKind excerpt contentHash locator {
            ... on BusinessLocator0 {path startLine endLine snapshotId}
            ... on BusinessLocator1 {snapshotId pointer}
            ... on BusinessLocator2 {snapshotId eventId}
          } } }
          pageInfo {endCursor hasNextPage} error {code message}
        }
      }
    }
  }
`;

export const REVIEW_DOMAIN_MUTATION = gql`
  mutation ReviewDomain($input: DomainReviewInput!) {
    reviewDomain(input:$input) {accepted buildId domainIds error {code message}}
  }
`;

export const DOMAIN_REVIEW_ACTIVITIES_QUERY = gql`
  query DomainReviewActivities($id: ID!, $build: ID!, $after: String) {
    domain(id:$id, expectedBuildId:$build) {
      error {code message}
      domain {primaryActivityIds activities(first:100, after:$after) {
        edges {node {id name}}
        pageInfo {endCursor hasNextPage} error {code message}
      }}
    }
  }
`;

export const CANCEL_DOMAIN_BUILD_MUTATION = gql`
  mutation CancelDomainBuild($buildId: ID!) {
    cancelDomainBuild(buildId:$buildId) {accepted error {code message}}
  }
`;

export interface DomainProblem {code:string; message:string}
export interface DomainConnection<T> {
  edges: {cursor:string; node:T}[];
  pageInfo: {endCursor:string|null; hasNextPage:boolean};
  error: DomainProblem|null;
}
export interface DomainActivity {
  id:string; name:string; description:string; implementationStatus:string; support:string;
  unresolvedQuestions:string[]; inputBindingIds:string[]; outputBindingIds:string[];
  inputs:DomainBinding[]; outputs:DomainBinding[];
  traces:{id:string; resolution:string; reason:string|null; stopReasons:string[]; uiInteraction?:{
    elements:{id:string;kind:string;label:string|null;routePatterns:{pattern:string}[]|null;routingResolution:string;reason:string|null}[];
    events:{id:string;trigger:string;resolution:string;reason:string|null}[];
    validations:{id:string;enforcement:string;resolution:string;reason:string|null}[];
    calls:{id:string;resolution:string;reason:string|null}[];
    outputs:{id:string;kind:string;resolution:string;reason:string|null}[];
  }|null}[];
}
export interface DomainBinding {id:string; name:string; valueType:string; expression:string|null; resolution:string; reason:string|null}
export interface DomainRule {
  id:string; name:string; description:string; predicateOrFormula:string|null; outcome:string;
  enforcementStatus:string; support:string; unresolvedQuestions:string[];
  observations?:{id:string;sourceLocationKind:string;nativeExpression:string|null;resolution:string;reason:string|null}[];
  relationships?:{id:string;kind:string;verification:string;explanation:string;fromObservationId:string;toObservationId:string}[];
}
export interface DomainEvidence {
  id:string; sourceKind:string; claimKind:string; excerpt:string; contentHash:string;
  locator:{path?:string; startLine?:number; endLine?:number; snapshotId:string; pointer?:string; eventId?:string};
}
export interface DomainDetailData {
  domain: {error:DomainProblem|null; domain: null|{
    id:string; name:string; boundaryRationale:string; unresolvedQuestions:string[];
    support:string; reviewState:string; activities:DomainConnection<DomainActivity>;
    rules:DomainConnection<DomainRule>; implementationEvidence:DomainConnection<DomainEvidence>;
    exclusions?:{explanation:string}[]; alternatives?:{explanation:string}[];
    concepts?:DomainConnection<{id:string;name:string;qualifiedTypeNames:string[]}>;
    ownerships?:DomainConnection<{id:string;kind:string;rationale:string;support:string;unresolvedQuestions:string[];concept:{id:string;name:string}|null}>;
    claims?:DomainConnection<{id:string;text:string;kind:string;semanticReview:string;evidenceIds:string[]}>;
  }};
}

export const DOMAIN_UNASSIGNED_QUERY = gql`
  query DomainUnassigned($build: ID!, $after: String) {
    domainUnassigned(expectedBuildId: $build, first: 20, after: $after) {
      edges {cursor node {subjectId status reason}}
      pageInfo {endCursor hasNextPage}
      error {code message}
    }
  }
`;
