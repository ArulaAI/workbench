import { test,expect } from '@playwright/test';
import { baseDigest,baseStatus } from '../__tests__/digest/fixtures';
test.use({launchOptions:{executablePath:process.env.SPEED_DOMAIN_BROWSER}});

const baseURL=process.env.SPEED_DOMAIN_E2E_URL || 'http://127.0.0.1:3317';
const pageInfo={endCursor:null,hasNextPage:false};
const connection=(nodes:unknown[])=>({edges:nodes.map(node=>({cursor:'fixture',node})),pageInfo,error:null});

for (const width of [390,1440]) {
  test(`domain evidence and review stay readable at ${width}px`,async({page})=>{
    await page.setViewportSize({width,height:1000});
    const mutations:unknown[]=[];
    const domain={...baseDigest.domains[0],id:'domain:refund',name:'Refund eligibility',label:'Refund eligibility',
      support:'partial',reviewState:'proposed',activityCount:1,boundaryRationale:'Checks refund requests against the supplied policy.',unresolvedQuestions:[]};
    const detail={...domain,activities:connection([{
      id:'activity:refund',name:'Request a refund',description:'Submit the purchase and reason for eligibility review.',
      implementationStatus:'partial',support:'partial',unresolvedQuestions:[],inputBindingIds:[],outputBindingIds:[],
      inputs:[{id:'binding:purchase',name:'purchaseId',valueType:'string',expression:null,resolution:'resolved',reason:null}],
      outputs:[{id:'binding:receipt',name:'requestReceipt',valueType:'Receipt',expression:null,resolution:'resolved',reason:null}],
      traces:[{id:'trace:refund',resolution:'unresolved',reason:'Remote outcome is not established.',stopReasons:['unresolved'],uiInteraction:null}],
    }]),rules:connection([{id:'rule:window',name:'Refund request eligibility',description:'The supplied policy limits the purchase age.',
      predicateOrFormula:'purchaseAgeDays <= refundWindowDays',outcome:'Request may proceed to server validation',
      enforcementStatus:'declared_only',support:'partial',unresolvedQuestions:[]}]),
      implementationEvidence:connection([{id:'ev:refund',sourceKind:'source',claimKind:'source_observation',
        excerpt:'<script>untrusted source</script>\nif (purchaseAgeDays > refundWindowDays) return reject();',contentHash:'fixture',
        locator:{path:'src/purchases/refund-requests/forms/CustomerRefundRequestFormWithLongSourceName.tsx',startLine:12,endLine:14,snapshotId:'snapshot:fixture'}}])};
    await page.route('**/graphql',async route=>{
      const body=route.request().postDataJSON();const query=body?.query || '';let data={};
      if (query.includes('mutation ReviewDomain')) {
        mutations.push(body.variables);data={reviewDomain:{accepted:true,buildId:'fixture-build',domainIds:[domain.id],error:null}};
      } else if (query.includes('query DomainDetail')) data={domain:{domain:detail,error:null}};
      else if (query.includes('query RepositoryDigestStatus')) data={repositoryDigestStatus:baseStatus,
        domainDiscoveryStatus:{phase:'partial',attemptBuildId:'fixture-build',publishedBuildId:'fixture-build',freshness:'current',executionMode:'whole_graph',currentScopeId:null,rootReconciled:true,error:null,
          coverage:{anchorsProcessed:1,anchorsTotal:2,anchorsPending:1,edgesUnresolved:1},limits:{requests:3,activitiesUsed:1,truncated:false}}};
      else if (query.includes('query RepositoryDigest')) data={repositoryDigest:{...baseDigest,schemaVersion:2,domainBuildId:'fixture-build',domains:[domain]}};
      await route.fulfill({json:{data}});
    });
    await page.goto(baseURL+'/digest');
    if (width<600) {
      await page.getByRole('button',{name:'Sections'}).click();
      await page.getByRole('navigation',{name:'Repository Digest'}).getByRole('link',{name:'Overview',exact:true}).click();
      await expect(page.getByRole('button',{name:'Sections'})).toHaveAttribute('aria-expanded','false');
    }
    await page.getByRole('button',{name:'Activities, rules and evidence'}).click();
    await expect(page.getByText('purchaseId',{exact:true})).toBeVisible();
    await expect(page.getByText('requestReceipt',{exact:true})).toBeVisible();
    await page.getByText(/source: src\/purchases\/refund-requests/).click();
    await expect(page.getByText(/<script>untrusted source<\/script>/)).toBeVisible();
    expect(mutations).toEqual([]);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
    const contentWidth=await page.locator('main').evaluate(element=>element.getBoundingClientRect().width);
    expect(contentWidth).toBeGreaterThanOrEqual(width<600 ? width-32 : width-300);
    await page.screenshot({path:`/private/tmp/speed-domain-ui-${width}.png`,fullPage:true});
    await page.getByLabel('Reason',{exact:true}).fill('Reviewed the stored activity and evidence');
    await page.getByRole('button',{name:'Save review'}).click();
    await expect(page.getByText('Review saved.')).toBeVisible();
    expect(mutations).toEqual([{input:{expectedBuildId:'fixture-build',operation:'ACCEPT',domainIds:[domain.id],explanation:'Reviewed the stored activity and evidence'}}]);
  });
}
