"""Compare two published business-domain models, or describe one.

Manual check, not collected by the test runner, and it makes no provider calls.
Use it to see whether a change to discovery, such as a different verification
model, changed the published result:

  - shape: how many domains, activities, rules, uses and claims, and how
    certain they are;
  - coverage: which entry points ended up in an activity;
  - grouping: whether pairs of entry points share a domain in both models
    (agreement over all pairs, so renamed domains don't count as changes);
  - corpus cases: whether the critical sources in corpus.json are covered by
    an activity, and whether any claim states a forbidden conclusion.

    python tests/business_domains/scorecard.py --model new/.speed/context/business-domains.json \\
        --baseline old/.speed/context/business-domains.json --repo-id petclinic
"""
import argparse
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

CORPUS = Path(__file__).with_name('corpus.json')


def shape(model):
    return {
        'domains': len(model['domains']),
        'activities': len(model['activities']),
        'rules': len(model['rules']),
        'information uses': len(model['information_uses']),
        'claims': len(model['claims']),
        'activity support': dict(Counter(a['support'] for a in model['activities'].values())),
        'implementation': dict(Counter(a['implementation_status']
                                       for a in model['activities'].values())),
        'domain support': dict(Counter(d['support'] for d in model['domains'].values())),
    }


def covered_anchors(model):
    return {anchor_id for activity in model['activities'].values()
            for anchor_id in activity['anchor_ids']}


def anchor_domains(model):
    """Map each covered anchor to the domain holding its activity as primary."""
    primary = {membership['activity_id']: domain_id
               for domain_id, domain in model['domains'].items()
               for membership in domain['activity_memberships']
               if membership['role'] == 'primary'}
    result = {}
    for activity_id, activity in model['activities'].items():
        for anchor_id in activity['anchor_ids']:
            result.setdefault(anchor_id, primary.get(activity_id))
    return result


def grouping_agreement(model, baseline):
    """Share of anchor pairs that are together, or apart, in both models."""
    ours, theirs = anchor_domains(model), anchor_domains(baseline)
    shared = sorted(set(ours) & set(theirs))
    pairs = agree = 0
    for left, right in combinations(shared, 2):
        pairs += 1
        agree += (ours[left] == ours[right]) == (theirs[left] == theirs[right])
    return agree / pairs if pairs else None, len(shared)


def corpus_cases(model, repo_id):
    corpus = json.loads(CORPUS.read_text())
    repository = next((item for item in corpus['repositories'] if item['id'] == repo_id), None)
    if repository is None:
        return []
    texts = [claim['text'].lower() for claim in model['claims'].values()]
    texts += [activity['description'].lower() for activity in model['activities'].values()]
    results = []
    for case in repository['critical_cases']:
        covering = []
        for activity_id, activity in model['activities'].items():
            evidence = set(activity['evidence_ids'])
            for claim_id in activity['claim_ids']:
                evidence |= set(model['claims'].get(claim_id, {}).get('evidence_ids', ()))
            if any(model['evidence'].get(evidence_id, {}).get('locator', {}).get('path', '')
                   .endswith(case['source']) for evidence_id in evidence):
                covering.append(activity['name'])
        stated = [phrase for phrase in case['must_not_claim']
                  if any(phrase.lower() in text for text in texts)]
        results.append({'symbol': case['symbol'], 'covered_by': sorted(covering),
                        'forbidden_claims': stated})
    return results


def describe(label, model, repo_id):
    print(f'== {label}')
    for key, value in shape(model).items():
        print(f'  {key:<18} {value}')
    anchors = set(model.get('anchors', {}))
    covered = covered_anchors(model)
    print(f'  {"entry points":<18} {len(covered & anchors) if anchors else len(covered)}'
          f' covered of {len(anchors) or len(covered)}')
    print(f'  {"domain names":<18} {sorted(d["name"] for d in model["domains"].values())}')
    for case in corpus_cases(model, repo_id):
        status = 'covered' if case['covered_by'] else 'NOT COVERED'
        forbidden = f"  FORBIDDEN: {case['forbidden_claims']}" if case['forbidden_claims'] else ''
        print(f'  case {case["symbol"]:<24} {status}{forbidden}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--repo-id', default='petclinic')
    args = parser.parse_args()
    model = json.loads(args.model.read_text())
    describe('model', model, args.repo_id)
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        describe('baseline', baseline, args.repo_id)
        agreement, anchors = grouping_agreement(model, baseline)
        ours, theirs = covered_anchors(model), covered_anchors(baseline)
        print('== comparison')
        print(f'  entry points only in model: {len(ours - theirs)}, only in baseline: {len(theirs - ours)}')
        if agreement is not None:
            print(f'  grouping agreement over {anchors} shared entry points: {agreement:.0%}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
