"""Check whether another model verifies like the one that verified a past run.

Manual check, not collected by the test runner. It CALLS THE PROVIDER and
spends tokens. It takes verification requests saved in a project's cache,
together with the verdicts the original model gave, sends a sample of them to
`--model` through the real discovery code, and compares:

  - verdict: pass versus fail or uncertain;
  - blocking findings: how many of the subjects the original model blocked
    on the new model also blocks on (recall), and what it blocks on that the
    original didn't.

The calls run in a scratch copy of the repository, so the project's cache is
only read.

    python tests/business_domains/verify_agreement.py --repo ~/petclinic-test --model sonnet --limit 10

The sample takes turns across slice and reconciliation scopes and passing and
failing verdicts, smallest request first in each, to keep the cost down.
"""
import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.context.business_domain_schema import DomainError, limits, settings
from lib.context.business_domain_synthesis import Synthesis
from lib.context.business_domains import load_speed_toml


def saved_verifications(cache):
    requests, answers = {}, {}
    for path in cache.glob('*.json'):
        saved = json.loads(path.read_text())
        if saved.get('kind') == 'request' and saved['request']['operation'] == 'verify':
            requests[saved['key']] = saved['request']
        elif (saved.get('kind') == 'response'
              and saved['response']['operation'] == 'verify'):
            answers[saved['request_key']] = saved['response']['verification_report']
    return [(key, requests[key], answers[key]) for key in sorted(requests) if key in answers]


def blocking_subjects(report):
    return {subject for finding in report['findings'] if finding['severity'] == 'blocking'
            for subject in finding['subject_ids']}


def sample(items, limit):
    """Take turns across scope kinds and verdicts, smallest request first in each."""
    groups = {}
    for item in sorted(items, key=lambda item: len(json.dumps(item[1]['graph']))):
        kind = (item[1]['graph']['scope_kind'], item[2]['verdict'] == 'pass')
        groups.setdefault(kind, []).append(item)
    chosen = []
    while len(chosen) < limit and any(groups.values()):
        for kind in sorted(groups):
            if groups[kind] and len(chosen) < limit:
                chosen.append(groups[kind].pop(0))
    return chosen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--json', type=Path, help='Write per-request results here')
    args = parser.parse_args()

    source = args.repo.expanduser().resolve()
    items = sample(saved_verifications(source / '.speed/context/business-domain-cache'), args.limit)
    work = Path(tempfile.mkdtemp(prefix='speed-verify-agreement-'))
    root = work / source.name
    shutil.copytree(source, root, ignore=shutil.ignore_patterns('.speed'))
    os.environ['SPEED_DISCOVER_VERIFICATION_MODEL'] = args.model
    config = settings(load_speed_toml(str(root)))
    counters = limits(config)
    runner = Synthesis(root, config, None, counters)

    results = []
    try:
        for key, saved, original in items:
            request = copy.deepcopy(saved)
            request.update(model=args.model, request_id=str(uuid.uuid4()),
                           deadline_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
            before = counters.get('input_tokens_reported') or 0
            try:
                report, _ = runner._run_once(request)
            except DomainError as exc:
                results.append({'key': key, 'error': f'{exc.code}: {exc}'})
                print(f'{key[:12]}  ERROR {exc.code}')
                continue
            expected, got = blocking_subjects(original), blocking_subjects(report)
            row = {'key': key, 'scope_kind': saved['graph']['scope_kind'],
                   'original_verdict': original['verdict'], 'verdict': report['verdict'],
                   'original_blocking': sorted(expected), 'blocking': sorted(got),
                   'recall': (len(expected & got) / len(expected)) if expected else None,
                   'extra': sorted(got - expected),
                   'input_tokens': (counters.get('input_tokens_reported') or 0) - before}
            results.append(row)
            recall = '-' if row['recall'] is None else f"{row['recall']:.0%}"
            print(f"{key[:12]}  {row['scope_kind']:<14} original {original['verdict']:<9} "
                  f"{args.model} {report['verdict']:<9} blocking recall {recall:>4}  "
                  f"extra {len(row['extra'])}")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    done = [row for row in results if 'verdict' in row]
    same = sum((row['verdict'] == 'pass') == (row['original_verdict'] == 'pass') for row in done)
    recalls = [row['recall'] for row in done if row['recall'] is not None]
    missed = sum(row['original_verdict'] != 'pass' and row['verdict'] == 'pass' for row in done)
    print(f'\n{len(done)} compared, {len(results) - len(done)} errors')
    if done:
        print(f'verdict agreement {same}/{len(done)}; failing candidates {args.model} passed: {missed}')
    if recalls:
        print(f'mean blocking recall {sum(recalls) / len(recalls):.0%}')
    print(f"input tokens {counters.get('input_tokens_reported') or 0:,}, "
          f"output tokens {counters.get('output_tokens_reported') or 0:,}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
