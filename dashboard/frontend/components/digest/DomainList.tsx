"use client";
import { useState } from 'react';
import { useMutation, useQuery } from 'urql';
import { CANCEL_DOMAIN_BUILD_MUTATION, DOMAIN_UNASSIGNED_QUERY } from '@/lib/graphql/queries/business-domains';
import type { DigestDomain, DomainDiscoveryStatus } from "@/lib/graphql/queries/repository-digest";
import { DomainDetail } from './DomainDetail';

export function DomainList({ domains, buildId, status, onReviewed }: { domains: DigestDomain[]; buildId?: string|null; status?:DomainDiscoveryStatus; onReviewed?:()=>void }) {
  const [selected,setSelected] = useState<string|null>(null);
  const [cancelMessage,setCancelMessage] = useState('');
  const [showUnassigned,setShowUnassigned] = useState(false);
  const [{fetching:cancelling},cancel] = useMutation<{cancelDomainBuild:{accepted:boolean;error:{message:string}|null}}>(CANCEL_DOMAIN_BUILD_MUTATION);
  async function stopBuild() {
    if (!status?.attemptBuildId) return;
    const result=await cancel({buildId:status.attemptBuildId});
    setCancelMessage(result.error?.message || result.data?.cancelDomainBuild.error?.message ||
      (result.data?.cancelDomainBuild.accepted ? 'Cancellation requested.' : 'Cancellation could not be requested.'));
    onReviewed?.();
  }
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="digest-section-title" style={{ marginBottom: 12 }}>
        Business domains
      </div>
      {status && <div role="status" style={{marginBottom:12}}>
        <p>Discovery: {status.phase} · {status.coverage.anchorsProcessed} of {status.coverage.anchorsTotal} entry points interpreted · {status.coverage.anchorsPending} pending · {status.coverage.anchorsExcluded} excluded</p>
        {status.executionMode === 'hierarchical' && <p className="type-caption">Hierarchical reconciliation: {status.rootReconciled ? 'complete' : 'incomplete'}{status.currentScopeId ? ` · active scope ${status.currentScopeId}` : ''}</p>}
        {status.coverage.edgesUnresolved > 0 && <p className="type-caption">{status.coverage.edgesUnresolved} unresolved code connections remain visible in activity traces.</p>}
        {status.freshness === 'stale' && <p>The previous published result is shown while the latest attempt is incomplete.</p>}
        {status.error && <p role="alert">
          {status.error.providerFailure && <strong>
            Provider {status.error.providerFailure.category.replaceAll('_',' ')}{status.error.providerFailure.nativeStatus ? ` (${status.error.providerFailure.nativeStatus})` : ''}: {' '}
          </strong>}
          {status.error.message}
        </p>}
        {!!status.warnings?.length && <details>
          <summary>Discovery limitations ({status.warnings.length})</summary>
          <ul>{status.warnings.map((warning,index)=><li key={`${warning.code}-${index}`}>{warning.message}</li>)}</ul>
        </details>}
        {['extracting','synthesizing','validating'].includes(status.phase) && status.attemptBuildId &&
          <button type="button" disabled={cancelling} onClick={stopBuild}>{cancelling ? 'Requesting cancellation…' : 'Cancel discovery'}</button>}
        {cancelMessage && <p>{cancelMessage}</p>}
      </div>}
      {buildId && <>
        <button type="button" aria-expanded={showUnassigned} onClick={()=>setShowUnassigned(!showUnassigned)}>
          {showUnassigned ? 'Hide pending and excluded work' : 'Inspect pending and excluded work'}
        </button>
        {showUnassigned && <UnassignedWork key={buildId} buildId={buildId} />}
      </>}
      {domains.length === 0 ? (
        <p className="type-body">No supported domain proposals are available. Discovery status explains missing coverage.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {domains.map((d) => (
            <div key={d.id} style={{ borderTop: "1px solid var(--color-border-light)", paddingTop: 12 }}>
              <div style={{ display: "flex", flexWrap:"wrap",gap:8,justifyContent: "space-between", alignItems: "baseline" }}>
                <span className="type-column-name">{d.name || d.label}</span>
                <span className="type-column-aggregate">
                  {d.activityCount ?? 0} activities · {d.fileCount} files · {d.symbolCount} symbols
                </span>
              </div>
              {d.summary && <p className="type-column-intent">{d.summary}</p>}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                <span className="type-caption">Evidence: {d.support ?? 'insufficient'} · Review: {(d.reviewState ?? 'proposed').replaceAll('_',' ')}{d.hasSharedCode ? ' · Shared implementation' : ''}</span>
              </div>
              {buildId && <button type="button" aria-expanded={selected === d.id} onClick={()=>setSelected(selected===d.id ? null : d.id)}>{selected===d.id ? 'Close details' : 'Activities, rules and evidence'}</button>}
              {selected===d.id && buildId && <DomainDetail key={buildId+d.id} domain={d} domains={domains} buildId={buildId} onReviewed={onReviewed} />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function UnassignedWork({buildId}:{buildId:string}) {
  const [after,setAfter] = useState<string|null>(null);
  const [{data,fetching,error}] = useQuery<{domainUnassigned:{
    edges:{cursor:string;node:{subjectId:string;status:string;reason:string}}[];
    pageInfo:{endCursor:string|null;hasNextPage:boolean};error:{code:string;message:string}|null;
  }}>({query:DOMAIN_UNASSIGNED_QUERY,variables:{build:buildId,after}});
  const page = data?.domainUnassigned;
  if (error || page?.error) return <p role="alert">{error?.message || page?.error?.message}</p>;
  if (fetching) return <p role="status">Loading pending and excluded work…</p>;
  if (!page) return <p>Pending and excluded work is unavailable.</p>;
  return <div>
    <p>Pending and excluded work in this published build</p>
    {page.edges.length === 0 ? <p>No pending or excluded work in this published build.</p> :
      <ul>{page.edges.map(({cursor,node})=><li key={cursor}>
        <p>{node.status === 'pending' ? 'Pending' : 'Excluded'}: {node.reason}</p>
        <span className="type-caption">Reference: {node.subjectId}</span>
      </li>)}</ul>}
    {after && <button type="button" onClick={()=>setAfter(null)}>First page</button>}
    {page.pageInfo.hasNextPage && <button type="button" onClick={()=>setAfter(page.pageInfo.endCursor)}>Next page</button>}
  </div>;
}
