"""Replay saved repair and verify requests through the provider projection.

Manual check, not collected by the test runner, and it makes no provider calls.
For each request saved in a project's business-domain cache it measures the
input the provider would receive, and for repair requests it checks that the
focused packet is safe to send:

  - the projection round-trips to the exact canonical graph,
  - aliases and the provider schema are the same as for the whole scope,
  - every graph record the candidate or findings mention is sent or listed in
    record_refs.

    python tests/business_domains/replay_focus.py --cache <project>/.speed/context/business-domain-cache
    python tests/business_domains/replay_focus.py --cache ... --json out.json --since 2026-10-19T06:55
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.context import business_domain_synthesis as synthesis
from lib.context.business_domain_synthesis import (
    OPERATIONS, AliasRegistry, ProviderProjection, Synthesis, projected_input_token_estimate,
    wire_schema)

FOCUSED = hasattr(synthesis, 'repair_focus')


class _Aliases:
    """Stands in for Synthesis where project_exchange only needs alias registries."""

    def __init__(self):
        self.registries = {}

    def alias_registry(self, graph):
        return self.registries.setdefault(graph['scope_id'], AliasRegistry())


def _input_tokens(request):
    output_type, _ = OPERATIONS[request['operation']]
    schema = wire_schema(output_type, request['graph'])
    projected, provider_schema, projection = Synthesis.project_exchange(
        _Aliases(), request, schema)
    return projected_input_token_estimate(projected, provider_schema), projection, provider_schema


def _focus(request):
    return synthesis.repair_focus(request['graph'], request['candidate'],
                                  request['deterministic_findings'],
                                  request['verification_report'])


def _check(request, full, focused):
    problems = []
    (_, whole, whole_schema), (_, narrow, narrow_schema) = full, focused
    if whole.aliases != narrow.aliases:
        problems.append('aliases differ from the whole-scope projection')
    offered = set(narrow_schema.get('$defs', {}).get('AllowedEvidenceId', {}).get('enum', ()))
    if _without_evidence_enum(whole_schema) != _without_evidence_enum(narrow_schema):
        problems.append('provider schema differs from the whole-scope schema')
    context = request['graph']['context']
    graph_ids = {record_id for collection, records in context.items()
                 if isinstance(records, dict) for record_id in records}
    wire = narrow.decode_packet(narrow.wire_packet)
    if wire != narrow.packet:
        problems.append('round trip does not restore the canonical graph')
    on_wire = {narrow.canonical_ids.get(value, value)
               for value in ProviderProjection._strings(narrow._unpack(narrow.wire_packet))}
    mentioned = set(ProviderProjection._strings([
        request['candidate'], request['deterministic_findings'],
        request['verification_report']])) & graph_ids
    missing = sorted(mentioned - on_wire)
    if missing:
        problems.append(f'{len(missing)} mentioned records neither sent nor referenced, '
                        f'e.g. {missing[0]}')
    unseen = sorted(narrow.canonical_ids.get(alias, alias) for alias in offered
                    if narrow.canonical_ids.get(alias, alias) not in on_wire)
    if unseen:
        problems.append(f'{len(unseen)} offered evidence IDs not on the wire, e.g. {unseen[0]}')
    cited = set(ProviderProjection._strings(request['candidate'])) & set(
        request['allowed_evidence_ids'])
    uncitable = sorted(cited - {narrow.canonical_ids.get(alias, alias) for alias in offered})
    if uncitable:
        problems.append(f'{len(uncitable)} candidate citations no longer offered, '
                        f'e.g. {uncitable[0]}')
    return problems


def _without_evidence_enum(schema):
    schema = json.loads(json.dumps(schema))
    schema.get('$defs', {}).get('AllowedEvidenceId', {}).pop('enum', None)
    return schema


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--since', default='', help='Only requests created at or after this ISO time')
    parser.add_argument('--until', default='9999', help='Only requests created before this ISO time')
    parser.add_argument('--json', type=Path, help='Write per-request numbers here')
    args = parser.parse_args()

    rows, failures = [], 0
    for path in sorted(args.cache.glob('*.json')):
        saved = json.loads(path.read_text())
        if saved.get('kind') != 'request' or not (args.since <= saved['created_at'] < args.until):
            continue
        request = saved['request']
        operation = request['operation']
        row = {'key': path.stem, 'created_at': saved['created_at'], 'operation': operation,
               'scope_kind': request['graph']['scope_kind']}
        full = _input_tokens(request)
        row['tokens'] = full[0]
        if FOCUSED and operation == 'repair':
            focus = _focus(request)
            row['focused'] = focus is not None
            if focus is not None:
                focused_request = {**request,
                                   'provider_focus': {'version': 1, 'record_ids': focus}}
                narrow = _input_tokens(focused_request)
                row['focused_tokens'] = narrow[0]
                row['omitted_records'] = narrow[1].omitted_records
                row['problems'] = _check(request, full, narrow)
                failures += bool(row['problems'])
        rows.append(row)

    rows.sort(key=lambda row: row['created_at'])
    for row in rows:
        line = f"{row['created_at'][:16]}  {row['operation']:<10} {row['scope_kind']:<15} {row['tokens']:>9,}"
        if 'focused_tokens' in row:
            share = row['focused_tokens'] / row['tokens']
            line += (f"  focused {row['focused_tokens']:>9,} ({share:.0%}, "
                     f"{row['omitted_records']} records left out)")
            if row['problems']:
                line += '  PROBLEMS: ' + '; '.join(row['problems'])
        elif row.get('focused') is False:
            line += '  whole scope (focus not worth it or not safe)'
        print(line)
    total = sum(row['tokens'] for row in rows)
    after = sum(row.get('focused_tokens', row['tokens']) for row in rows)
    print(f'\nrequests {len(rows)}  input {total:,}  with focused repairs {after:,}'
          f'  checks failed {failures}')
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
