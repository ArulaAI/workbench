import { describe,it,expect,vi } from 'vitest';
import { render,screen,fireEvent } from '@testing-library/react';
import { DomainList } from '@/components/digest/DomainList';

const mocks = vi.hoisted(()=>({query:vi.fn()}));
vi.mock('urql',()=>({useQuery:mocks.query,useMutation:()=>[{fetching:false},vi.fn()],
  gql:(strings:TemplateStringsArray)=>strings.raw.join('')}));
vi.mock('@/components/digest/DomainDetail',()=>({DomainDetail:()=>null}));

describe('DomainList discovery coverage',()=>{
  it('shows grouping limitations even when no entrypoints are pending',()=>{
    render(<DomainList domains={[]} status={{phase:'partial',attemptBuildId:'attempt',
      publishedBuildId:'build',freshness:'current',
      executionMode:'hierarchical',currentScopeId:null,rootReconciled:true,
      coverage:{anchorsTotal:29,anchorsProcessed:24,anchorsPending:0,anchorsExcluded:5,edgesUnresolved:0},
      limits:{requests:41,elapsedMs:1000},error:null,
      warnings:[{code:'PARTIAL_GROUPING',message:'5 interpreted activities remain pending domain grouping.',subjectIds:['activity:pending']}]}} />);
    expect(screen.getByText(/0 pending · 5 excluded/)).toBeInTheDocument();
    expect(screen.getByText('Discovery limitations (1)')).toBeInTheDocument();
    expect(screen.getByText('5 interpreted activities remain pending domain grouping.')).toBeInTheDocument();
    expect(screen.getByText('Hierarchical reconciliation: complete')).toBeInTheDocument();
  });

  it('shows the normalized provider cause while retaining the previous publication',()=>{
    render(<DomainList domains={[]} status={{phase:'unavailable',attemptBuildId:'attempt',
      publishedBuildId:'build',freshness:'stale',
      executionMode:'whole_graph',currentScopeId:null,rootReconciled:false,
      coverage:{anchorsTotal:20,anchorsProcessed:0,anchorsPending:20,anchorsExcluded:0,edgesUnresolved:0},
      limits:{requests:1,elapsedMs:50},warnings:[],error:{
        code:'PROVIDER_UNAVAILABLE',message:'Provider rejected authorization',retryable:false,
        providerFailure:{category:'authorization_denied',scope:'provider',retryable:false,
          nativeStatus:'403',diagnosticLog:'.speed/logs/provider.json'}}}} />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Provider authorization denied (403): Provider rejected authorization');
    expect(screen.getByText(/previous published result is shown/)).toBeInTheDocument();
  });
});

it('loads exclusion reasons only when requested and keeps paging scoped to the build',()=>{
  mocks.query.mockReturnValue([{data:{domainUnassigned:{edges:[{cursor:'one',node:{
    subjectId:'activity:one',status:'excluded',reason:'Generic navigation has no business-purpose evidence.'}}],
    pageInfo:{endCursor:'one',hasNextPage:true},error:null}},fetching:false}]);
  render(<DomainList domains={[]} buildId="published" />);
  expect(mocks.query).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Inspect pending and excluded work'}));
  expect(screen.getByText('Excluded: Generic navigation has no business-purpose evidence.')).toBeInTheDocument();
  expect(mocks.query).toHaveBeenLastCalledWith(expect.objectContaining({variables:{build:'published',after:null}}));
  fireEvent.click(screen.getByRole('button',{name:'Next page'}));
  expect(mocks.query).toHaveBeenLastCalledWith(expect.objectContaining({variables:{build:'published',after:'one'}}));
});
