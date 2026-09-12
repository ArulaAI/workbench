"use client";
import { useState, useEffect } from 'react';
import { useMutation, useQuery } from 'urql';
import type { DigestDomain } from '@/lib/graphql/queries/repository-digest';
import { DOMAIN_DETAIL_QUERY, REVIEW_DOMAIN_MUTATION, DOMAIN_REVIEW_ACTIVITIES_QUERY, type DomainDetailData, type DomainProblem, type DomainConnection } from '@/lib/graphql/queries/business-domains';

export function DomainDetail({domain,domains=[domain],buildId,onReviewed}:{domain:DigestDomain;domains?:DigestDomain[];buildId:string;onReviewed?:()=>void}) {
  const [activityAfter,setActivityAfter] = useState<string|null>(null);
  const [ruleAfter,setRuleAfter] = useState<string|null>(null);
  const [evidenceAfter,setEvidenceAfter] = useState<string|null>(null);
  const [conceptAfter,setConceptAfter] = useState<string|null>(null);
  const [ownershipAfter,setOwnershipAfter] = useState<string|null>(null);
  const [claimAfter,setClaimAfter] = useState<string|null>(null);
  const [{data,error,fetching},reload] = useQuery<DomainDetailData>({query:DOMAIN_DETAIL_QUERY,
    variables:{id:domain.id,build:buildId,activityAfter,ruleAfter,evidenceAfter,conceptAfter,ownershipAfter,claimAfter}});
  const [{fetching:saving},submitReview] = useMutation<{reviewDomain:{accepted:boolean;error:DomainProblem|null}}>(REVIEW_DOMAIN_MUTATION);
  const [operation,setOperation] = useState('ACCEPT');
  const [name,setName] = useState(domain.name || domain.label);
  const [explanation,setExplanation] = useState('');
  const [message,setMessage] = useState('');
  const [mergeIds,setMergeIds] = useState<string[]>([]);
  const [selectedActivities,setSelectedActivities] = useState<string[]>([]);
  const [secondName,setSecondName] = useState('');
  const detail = data?.domain.domain;
  const problem = error?.message || data?.domain.error?.message;
  const membershipOperation = operation === 'SPLIT' || operation === 'SET_MEMBERSHIP';
  const [reviewAfter,setReviewAfter] = useState<string|null>(null);
  const [allActivities,setAllActivities] = useState<{id:string;name:string}[]>([]);
  const [completeActivityList,setCompleteActivityList] = useState(false);
  const [{data:reviewData,error:reviewError}] = useQuery<{domain:{error:DomainProblem|null;domain:null|{
    primaryActivityIds:string[]; activities:DomainConnection<{id:string;name:string}>
  }}}>({query:DOMAIN_REVIEW_ACTIVITIES_QUERY,variables:{id:domain.id,build:buildId,after:reviewAfter},pause:!membershipOperation});
  const reviewProblem = reviewError?.message || reviewData?.domain.error?.message || reviewData?.domain.domain?.activities.error?.message;
  useEffect(()=>{
    const page=reviewData?.domain.domain?.activities;
    if (!page || reviewProblem) return;
    const primary=new Set(reviewData?.domain.domain?.primaryActivityIds ?? []);
    setAllActivities(previous=>Array.from(new Map([...previous,...page.edges.map(e=>e.node).filter(a=>primary.has(a.id))].map(a=>[a.id,a])).values()));
    if (page.pageInfo.hasNextPage) setReviewAfter(page.pageInfo.endCursor);
    else setCompleteActivityList(true);
  },[reviewData,reviewProblem]);
  const validSelection = !membershipOperation || (completeActivityList && selectedActivities.length>0 &&
    !reviewProblem && (operation !== 'SPLIT' || selectedActivities.length<allActivities.length));
  async function save(event:React.FormEvent) {
    event.preventDefault(); setMessage('');
    if (!validSelection) return;
    const response = await submitReview({input:{expectedBuildId:buildId,operation,
      domainIds:operation === 'MERGE' ? [domain.id,...mergeIds] : [domain.id],
      explanation,...(['RENAME','MERGE'].includes(operation) ? {name} : {}),
      ...(operation === 'SET_MEMBERSHIP' ? {activityIds:selectedActivities} : {}),
      ...(operation === 'SPLIT' ? {groups:[{name,activityIds:selectedActivities},
        {name:secondName,activityIds:allActivities.filter(a=>!selectedActivities.includes(a.id)).map(a=>a.id)}]} : {})}});
    if (response.error || !response.data?.reviewDomain.accepted) {
      setMessage(response.error?.message || response.data?.reviewDomain.error?.message || 'Review could not be saved');
    } else {setMessage('Review saved.'); onReviewed?.();}
  }
  return <div className="domain-details" style={{marginTop:16}}>
    {fetching && <p role="status">Loading domain details…</p>}
    {problem && <p role="alert">{problem} <button onClick={() => {onReviewed?.();reload({requestPolicy:'network-only'});}}>Reload stored result</button></p>}
    {detail && <>
      <h4>Why these activities belong together</h4><p>{detail.boundaryRationale}</p>
      {!!detail.exclusions?.length && <><h4>What stays outside this domain</h4><ul>{detail.exclusions.map((item,index)=><li key={index}>{item.explanation}</li>)}</ul></>}
      {!!detail.alternatives?.length && <><h4>Alternative boundaries</h4><ul>{detail.alternatives.map((item,index)=><li key={index}>{item.explanation}</li>)}</ul></>}
      {detail.concepts && <><h4>Business concepts</h4>
        {detail.concepts.error && <p role="alert">{detail.concepts.error.message}</p>}
        {!detail.concepts.edges.length && <p>No business concepts have been established for this domain.</p>}
        {detail.concepts.edges.map(({node:concept})=><p key={concept.id}><strong>{concept.name}</strong>
          {!!concept.qualifiedTypeNames.length && <span className="type-caption"> · {concept.qualifiedTypeNames.join(', ')}</span>}</p>)}
        {detail.concepts.pageInfo.hasNextPage && <button onClick={()=>setConceptAfter(detail.concepts!.pageInfo.endCursor)}>Next concepts</button>}
        {conceptAfter && <button onClick={()=>setConceptAfter(null)}>First concepts</button>}
      </>}
      {detail.ownerships && <><h4>Information ownership</h4>
        {detail.ownerships.error && <p role="alert">{detail.ownerships.error.message}</p>}
        {!detail.ownerships.edges.length && <p>Information ownership has not been established.</p>}
        {detail.ownerships.edges.map(({node:ownership})=><div key={ownership.id}>
          <strong>{ownership.concept?.name || 'Unresolved concept'}</strong>
          <p>{ownership.kind.replaceAll('_',' ')} · Evidence: {ownership.support}</p><p>{ownership.rationale}</p>
          {ownership.unresolvedQuestions.map((question,index)=><p key={index}>{question}</p>)}
        </div>)}
        {detail.ownerships.pageInfo.hasNextPage && <button onClick={()=>setOwnershipAfter(detail.ownerships!.pageInfo.endCursor)}>Next ownership records</button>}
        {ownershipAfter && <button onClick={()=>setOwnershipAfter(null)}>First ownership records</button>}
      </>}
      {detail.claims && <details><summary>Claims supporting this proposal</summary>
        {detail.claims.error && <p role="alert">{detail.claims.error.message}</p>}
        {detail.claims.edges.map(({node:claim})=><div key={claim.id}><p>{claim.text}</p>
          <p className="type-caption">Evidence review: {claim.semanticReview} · {claim.evidenceIds.length} cited excerpts</p></div>)}
        {detail.claims.pageInfo.hasNextPage && <button onClick={()=>setClaimAfter(detail.claims!.pageInfo.endCursor)}>Next claims</button>}
        {claimAfter && <button onClick={()=>setClaimAfter(null)}>First claims</button>}
      </details>}
      {detail.unresolvedQuestions.length > 0 && <><h4>Unresolved questions</h4><ul>{detail.unresolvedQuestions.map((q,i)=><li key={i}>{q}</li>)}</ul></>}
      <h4>Activities</h4>
      {detail.activities.error && <p role="alert">{detail.activities.error.message}</p>}
      {detail.activities.edges.map(({node:a})=><div key={a.id} style={{marginBottom:12}}>
        <strong>{a.name}</strong><p>{a.description}</p><p className="type-caption">Implementation: {a.implementationStatus.replaceAll('_',' ')} · Evidence: {a.support}</p>
        <table style={{width:'100%',tableLayout:'fixed'}}><thead><tr><th>Direction</th><th>Value</th><th>Type / mapping</th></tr></thead><tbody>
          {(['inputs','outputs'] as const).flatMap(direction=>a[direction].map(binding=><tr key={direction+binding.id}>
            <td>{direction === 'inputs' ? 'Input' : 'Output'}</td><td style={{overflowWrap:'anywhere'}}>{binding.name}</td>
            <td style={{overflowWrap:'anywhere'}}>{binding.valueType}{binding.expression ? ` · ${binding.expression}` : ''}{binding.resolution !== 'resolved' ? ` · ${binding.reason || binding.resolution}` : ''}</td>
          </tr>))}
        </tbody></table>
        {!a.inputs.length && <p className="type-caption">Inputs have not been established by discovery.</p>}
        {!a.outputs.length && <p className="type-caption">Outputs have not been established by discovery.</p>}
        {a.traces.filter(trace=>trace.resolution!=='resolved').map(trace=><p className="type-caption" key={trace.id}>{trace.reason || `Trace: ${trace.resolution}`}</p>)}
        {a.traces.filter(trace=>trace.uiInteraction).map(trace=><div key={trace.id}>
          <h5>Views and addresses</h5>
          <table style={{width:'100%',tableLayout:'fixed'}}><thead><tr><th>View</th><th>URL pattern</th><th>Link status</th></tr></thead><tbody>
            {trace.uiInteraction!.elements.filter(e=>e.kind==='view').map(view=><tr key={view.id}>
              <td style={{overflowWrap:'anywhere'}}>{view.label || 'Unnamed view'}<details><summary>View ID</summary><code>{view.id}</code></details></td>
              <td style={{overflowWrap:'anywhere'}}>{view.routePatterns?.map(r=>r.pattern).join(', ') || 'Not established'}</td>
              <td>{view.reason || view.routingResolution}</td>
            </tr>)}
          </tbody></table>
          <h5>Events and validations</h5>
          {trace.uiInteraction!.events.map(event=><p key={event.id}>{event.trigger} · {event.reason || event.resolution}</p>)}
          {trace.uiInteraction!.validations.map(validation=><p key={validation.id}>{validation.enforcement} validation · {validation.reason || validation.resolution}</p>)}
          {!trace.uiInteraction!.calls.length && <p className="type-caption">Event-to-service call mappings have not been established.</p>}
          {trace.uiInteraction!.calls.map(call=><p key={call.id}>Service call: {call.reason || call.resolution}</p>)}
        </div>)}
        {a.unresolvedQuestions.map((q,i)=><p key={i}>{q}</p>)}
      </div>)}
      {detail.activities.pageInfo.hasNextPage && <button onClick={()=>setActivityAfter(detail.activities.pageInfo.endCursor)}>Next activities</button>}
      {activityAfter && <button onClick={()=>setActivityAfter(null)}>First activities</button>}
      <h4>Business rules</h4>
      {detail.rules.error && <p role="alert">{detail.rules.error.message}</p>}
      {detail.rules.edges.length === 0 && <p>No business rules have been supported by the captured evidence.</p>}
      {detail.rules.edges.map(({node:r})=><div key={r.id} style={{marginBottom:12}}>
        <strong>{r.name}</strong><p>{r.description}</p>{r.predicateOrFormula && <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{r.predicateOrFormula}</pre>}
        <p>Outcome: {r.outcome}</p><p className="type-caption">Enforcement: {r.enforcementStatus.replaceAll('_',' ')} · Evidence: {r.support}</p>
        {r.observations?.map(observation=><details key={observation.id}>
          <summary>Observed in {observation.sourceLocationKind}: {observation.resolution}</summary>
          {observation.nativeExpression && <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{observation.nativeExpression}</pre>}
          {observation.reason && <p>{observation.reason}</p>}
        </details>)}
        {r.relationships?.map(relation=><p key={relation.id}>
          {relation.kind.replaceAll('_',' ')} ({relation.verification}): {relation.explanation}
        </p>)}
        {r.unresolvedQuestions.map((question,index)=><p key={index}>{question}</p>)}
      </div>)}
      {detail.rules.pageInfo.hasNextPage && <button onClick={()=>setRuleAfter(detail.rules.pageInfo.endCursor)}>Next rules</button>}
      {ruleAfter && <button onClick={()=>setRuleAfter(null)}>First rules</button>}
      <h4>Captured evidence</h4>
      <p className="type-caption">These excerpts are the stored sources used for this proposal. Several excerpts from one file are not independent confirmations.</p>
      {detail.implementationEvidence.error && <p role="alert">{detail.implementationEvidence.error.message}</p>}
      {detail.implementationEvidence.edges.map(({node:e})=><details key={e.id} style={{marginBottom:12}}>
        <summary style={{overflowWrap:'anywhere'}}>{e.sourceKind.replaceAll('_',' ')}: {e.locator.path ? `${e.locator.path}:${e.locator.startLine}–${e.locator.endLine}` : 'Captured external or review record'}</summary>
        <p className="type-caption">{e.claimKind.replaceAll('_',' ')}</p><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{e.excerpt}</pre>
      </details>)}
      {detail.implementationEvidence.pageInfo.hasNextPage && <button onClick={()=>setEvidenceAfter(detail.implementationEvidence.pageInfo.endCursor)}>Next evidence</button>}
      {evidenceAfter && <button onClick={()=>setEvidenceAfter(null)}>First evidence</button>}
      <form onSubmit={save} style={{display:'grid',gap:8,marginTop:16}}>
        <h4>Review this proposal</h4>
        <label>Decision <select value={operation} onChange={e=>{setOperation(e.target.value);setSelectedActivities([]);}}><option value="ACCEPT">Accept</option><option value="REJECT">Reject</option><option value="RENAME">Rename</option><option value="MERGE">Merge domains</option><option value="SPLIT">Split domain</option><option value="SET_MEMBERSHIP">Change activities</option></select></label>
        {['RENAME','MERGE','SPLIT'].includes(operation) && <label>{operation==='SPLIT' ? 'First domain name' : 'Domain name'} <input required maxLength={120} value={name} onChange={e=>setName(e.target.value)} /></label>}
        {operation === 'MERGE' && <fieldset><legend>Merge with</legend>{domains.filter(d=>d.id!==domain.id).map(d=><label key={d.id} style={{display:'block'}}><input type="checkbox" checked={mergeIds.includes(d.id)} onChange={e=>setMergeIds(e.target.checked ? [...mergeIds,d.id] : mergeIds.filter(id=>id!==d.id))} />{d.name || d.label}</label>)}</fieldset>}
        {membershipOperation && <fieldset><legend>{operation==='SPLIT' ? 'Activities in the first domain' : 'Activities to keep'}</legend>
          {!completeActivityList && !reviewProblem && <p role="status">Loading all activities for review…</p>}
          {reviewProblem && <p role="alert">{reviewProblem}</p>}
          {allActivities.map(a=><label key={a.id} style={{display:'block'}}><input type="checkbox" checked={selectedActivities.includes(a.id)} onChange={e=>setSelectedActivities(e.target.checked ? [...selectedActivities,a.id] : selectedActivities.filter(id=>id!==a.id))} />{a.name}</label>)}
        </fieldset>}
        {operation === 'SPLIT' && <label>Second domain name <input required maxLength={120} value={secondName} onChange={e=>setSecondName(e.target.value)} /><span className="type-caption">Unchecked activities move to this domain.</span></label>}
        <label>Reason <textarea required maxLength={2000} value={explanation} onChange={e=>setExplanation(e.target.value)} /></label>
        <button disabled={saving || !explanation.trim() || !!problem || !validSelection || (operation==='MERGE' && !mergeIds.length)} type="submit">{saving ? 'Saving…' : 'Save review'}</button>
        {message && <p role="status">{message}</p>}
      </form>
    </>}
  </div>;
}
