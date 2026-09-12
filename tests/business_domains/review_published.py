"""Opt-in semantic review diagnostic; never changes the published model."""
import argparse
import copy
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from lib.context.business_domain_schema import settings,limits
from lib.context.business_domain_synthesis import Synthesis,packet_for
from lib.context.business_domains import _allowed_evidence,apply_verdicts

p=argparse.ArgumentParser()
p.add_argument('--repo',type=Path,required=True)
p.add_argument('--config',type=Path,required=True)
p.add_argument('--model',required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
import os
os.environ["SPEED_SUPPORT_MODEL"] = a.model
model=json.loads((a.repo/'.speed/context/business-domains.json').read_text())
config=settings(json.loads(a.config.read_text()))
counters=limits(config)
synthesis=Synthesis(a.repo,config,None,counters)
claim_ids=[cid for cid,c in model['claims'].items() if c['subject_id'] in model['domains']]
verdicts=[]
for cid in claim_ids:
 packet=packet_for(model,'evidence_review',[cid])
 def check(payload):
  _allowed_evidence(payload,packet)
  apply_verdicts(copy.deepcopy(model),[cid],payload)
 result=synthesis.run(packet,check)
 verdicts.extend(result['verdicts'])
a.output.write_text(json.dumps({'build_id':model['build_id'],'verdicts':verdicts,'limits':counters},indent=2))
print(json.dumps({'claims':len(verdicts),'verdicts':{v:sum(r['verdict']==v for r in verdicts) for v in ['supported','uncertain','unsupported']}}))
