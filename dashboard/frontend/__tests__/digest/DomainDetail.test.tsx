import { describe,it,expect,vi,beforeEach } from 'vitest';
import { render,screen,fireEvent,waitFor } from '@testing-library/react';
import { DomainDetail } from '@/components/digest/DomainDetail';
import { baseDigest } from './fixtures';
import type { DomainDetailData } from '@/lib/graphql/queries/business-domains';

const mocks = vi.hoisted(()=>({query:vi.fn(),mutation:vi.fn(),save:vi.fn(),reload:vi.fn()}));
vi.mock('urql',()=>({useQuery:mocks.query,useMutation:mocks.mutation,
  gql:(strings:TemplateStringsArray)=>strings.raw.join('')}));

const page = {endCursor:null,hasNextPage:false};
const data:DomainDetailData = {domain:{error:null,domain:{id:'domain:one',name:'Purchasing',
  boundaryRationale:'Creates and maintains purchase requests',unresolvedQuestions:[],support:'partial',reviewState:'proposed',
  activities:{error:null,pageInfo:page,edges:[{cursor:'activity-page',node:{
    id:'activity:one',name:'Submit purchase',description:'Creates a request for a purchase',implementationStatus:'partial',
    support:'partial',unresolvedQuestions:[],inputBindingIds:['binding:input'],outputBindingIds:['binding:output'],
    inputs:[{id:'binding:input',name:'purchaseId',valueType:'string',expression:null,resolution:'resolved',reason:null}],
    outputs:[{id:'binding:output',name:'receipt',valueType:'Receipt',expression:'response.body',resolution:'resolved',reason:null}],
    traces:[{id:'trace:one',resolution:'unresolved',reason:'Remote service implementation is unavailable',stopReasons:['unresolved']}],
  }}]},rules:{error:null,pageInfo:page,edges:[]},implementationEvidence:{error:null,pageInfo:page,edges:[{
    cursor:'evidence-page',node:{id:'ev:one',sourceKind:'source',claimKind:'source_observation',
      excerpt:'<script>untrusted source text</script>',contentHash:'hash',locator:{path:'purchase.ts',startLine:1,endLine:3,snapshotId:'snapshot:one'}}
  }]}}}};

describe('DomainDetail',()=>{
  beforeEach(()=>{
    vi.clearAllMocks();
    mocks.query.mockReturnValue([{data,fetching:false},mocks.reload]);
    mocks.save.mockResolvedValue({data:{reviewDomain:{accepted:true,error:null}}});
    mocks.mutation.mockReturnValue([{fetching:false},mocks.save]);
  });
  it('shows captured inputs, outputs and trace gaps without mutating on read',()=>{
    const {container} = render(<DomainDetail domain={baseDigest.domains[0]} buildId="build-one" />);
    expect(screen.getByText('purchaseId')).toBeInTheDocument();
    expect(screen.getByText('receipt')).toBeInTheDocument();
    expect(screen.getByText('Receipt · response.body')).toBeInTheDocument();
    expect(screen.getByText('Remote service implementation is unavailable')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    expect(mocks.save).not.toHaveBeenCalled();
  });
  it('submits a review only with the displayed build and a reason',async()=>{
    const reviewed = vi.fn();
    render(<DomainDetail domain={baseDigest.domains[0]} buildId="build-one" onReviewed={reviewed} />);
    expect(screen.getByRole('button',{name:'Save review'})).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Reason'),{target:{value:'I checked the responsibility and source evidence'}});
    fireEvent.click(screen.getByRole('button',{name:'Save review'}));
    await waitFor(()=>expect(reviewed).toHaveBeenCalledOnce());
    expect(mocks.save).toHaveBeenCalledWith({input:{expectedBuildId:'build-one',operation:'ACCEPT',
      domainIds:[baseDigest.domains[0].id],explanation:'I checked the responsibility and source evidence'}});
  });
  it('shows rule observations and preserves uncertainty about conflicts',()=>{
    const result = structuredClone(data);
    result.domain.domain!.rules.edges = [{cursor:'rule-page',node:{
      id:'rule:one',name:'Purchase limit',description:'Checks the requested amount',
      predicateOrFormula:'amount <= limit',outcome:'Request is permitted',
      enforcementStatus:'conditional',support:'partial',unresolvedQuestions:['Effective profile is unknown'],
      observations:[{id:'observation:one',sourceLocationKind:'configuration',nativeExpression:'limit: 100',
        resolution:'unresolved',reason:'Active configuration has not been established'}],
      relationships:[{id:'rule_relationship:one',kind:'conflicts_with',verification:'unresolved',
        explanation:'The two limits may apply in different environments',fromObservationId:'observation:one',toObservationId:'observation:two'}],
    }}];
    mocks.query.mockReturnValue([{data:result,fetching:false},mocks.reload]);
    render(<DomainDetail domain={baseDigest.domains[0]} buildId="build-one" />);
    expect(screen.getByText('Observed in configuration: unresolved')).toBeInTheDocument();
    expect(screen.getByText(/conflicts with \(unresolved\): The two limits/)).toBeInTheDocument();
    expect(screen.getByText('Effective profile is unknown')).toBeInTheDocument();
  });
  it('shows alternative boundaries and unknown ownership without implying authority',()=>{
    const result = structuredClone(data);
    Object.assign(result.domain.domain!,{
      alternatives:[{explanation:'Receiving may be a separate responsibility'}],
      exclusions:[{explanation:'Generic navigation does not maintain purchase information'}],
      concepts:{error:null,pageInfo:page,edges:[{cursor:'concept-page',node:{id:'concept:purchase',name:'Purchase request',qualifiedTypeNames:[]}}]},
      ownerships:{error:null,pageInfo:page,edges:[{cursor:'ownership-page',node:{id:'ownership:purchase',kind:'unknown',support:'partial',
        rationale:'Reading a request does not establish authority',unresolvedQuestions:[],concept:{id:'concept:purchase',name:'Purchase request'}}}]},
      claims:{error:null,pageInfo:{endCursor:'claim-page',hasNextPage:true},edges:[{cursor:'claim-page',node:{id:'claim:purchase',
        text:'The handler records the request',kind:'behavior',semanticReview:'uncertain',evidenceIds:['ev:one']}}]},
    });
    mocks.query.mockReturnValue([{data:result,fetching:false},mocks.reload]);
    render(<DomainDetail domain={baseDigest.domains[0]} buildId="build-one" />);
    expect(screen.getByText('Receiving may be a separate responsibility')).toBeInTheDocument();
    expect(screen.getByText('Reading a request does not establish authority')).toBeInTheDocument();
    expect(screen.getByText('unknown · Evidence: partial')).toBeInTheDocument();
    expect(screen.getByText('Evidence review: uncertain · 1 cited excerpts')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Next claims'));
    expect(mocks.query.mock.calls.some(([options])=>options.variables.claimAfter==='claim-page')).toBe(true);
  });
  it('disables review when the build is stale',()=>{
    mocks.query.mockReturnValue([{data:{domain:{domain:null,error:{code:'STALE_BUILD',message:'Reload this build'}}},fetching:false},mocks.reload]);
    render(<DomainDetail domain={baseDigest.domains[0]} buildId="build-one" />);
    expect(screen.getByRole('alert')).toHaveTextContent('Reload this build');
    expect(screen.queryByRole('button',{name:'Save review'})).not.toBeInTheDocument();
  });
  it('partitions all primary activities when splitting a domain',async()=>{
    const reviewData={domain:{error:null,domain:{primaryActivityIds:['activity:one','activity:two'],activities:{error:null,pageInfo:page,
      edges:[{node:{id:'activity:one',name:'Submit purchase'}},{node:{id:'activity:two',name:'Receive delivery'}}]}}}};
    mocks.query.mockImplementation(({query}:{query:string})=>[{data:query.includes('DomainReviewActivities') ? reviewData : data,fetching:false},mocks.reload]);
    render(<DomainDetail domain={baseDigest.domains[0]} buildId="build-one" />);
    fireEvent.change(screen.getByLabelText('Decision'),{target:{value:'SPLIT'}});
    await waitFor(()=>expect(screen.getByLabelText('Receive delivery')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('First domain name'),{target:{value:'Purchasing'}});
    fireEvent.change(screen.getByLabelText(/Second domain name/),{target:{value:'Receiving'}});
    fireEvent.click(screen.getByLabelText('Submit purchase'));
    fireEvent.change(screen.getByLabelText('Reason'),{target:{value:'These activities serve different responsibilities'}});
    fireEvent.click(screen.getByRole('button',{name:'Save review'}));
    await waitFor(()=>expect(mocks.save).toHaveBeenCalledOnce());
    expect(mocks.save.mock.calls[0][0].input.groups).toEqual([
      {name:'Purchasing',activityIds:['activity:one']},{name:'Receiving',activityIds:['activity:two']},
    ]);
  });
  it('requires an explicit second domain for a merge',async()=>{
    render(<DomainDetail domain={baseDigest.domains[0]} domains={baseDigest.domains} buildId="build-one" />);
    fireEvent.change(screen.getByLabelText('Decision'),{target:{value:'MERGE'}});
    fireEvent.change(screen.getByLabelText('Reason'),{target:{value:'Shared responsibility'}});
    expect(screen.getByRole('button',{name:'Save review'})).toBeDisabled();
    fireEvent.click(screen.getByLabelText(baseDigest.domains[1].name || baseDigest.domains[1].label));
    fireEvent.click(screen.getByRole('button',{name:'Save review'}));
    await waitFor(()=>expect(mocks.save).toHaveBeenCalledOnce());
    expect(mocks.save.mock.calls[0][0].input.domainIds).toEqual(baseDigest.domains.map(d=>d.id));
  });
});
