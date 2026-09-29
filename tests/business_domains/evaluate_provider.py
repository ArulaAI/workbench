"""Opt-in real-provider contract check; never imported by the test runner."""
import argparse
import copy
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, DomainError, copy_facts, limits, read_json)
from lib.context.business_domain_synthesis import Synthesis
from lib.context.business_domains import accept_candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--full', action='store_true',help='Run the complete discovery pipeline, including grouping and evidence review')
    parser.add_argument('--cli',action='store_true',help='Exercise the actual speed digest --refresh --json entry point; repository speed.toml supplies configuration')
    parser.add_argument('--config', type=Path,help='Explicit JSON evaluation configuration')
    args = parser.parse_args()
    import os
    os.environ["SPEED_SUPPORT_MODEL"] = args.model
    if args.cli:
        import os,shutil,subprocess
        from lib.context.business_domains import load
        env={**os.environ,'SPEED_PROVIDER':'codex-cli','SPEED_PROJECT_ROOT':str(args.repo),
            'SPEED_PYTHON':sys.executable}
        bash=shutil.which('bash')
        completed=subprocess.run([bash,str(Path(__file__).resolve().parents[2]/'speed'),'digest','--refresh','--json'],
            cwd=args.repo,env=env,capture_output=True,text=True)
        artifact_error = None
        try:
            model,status=load(args.repo)
        except DomainError as exc:
            model = None
            status = read_json(args.repo/'.speed/context/business-domain-status.json')
            artifact_error = exc.record()
        try:artifact=json.loads(completed.stdout)
        except ValueError:artifact=None
        args.output.write_text(json.dumps({'status':status,'model':model,'digest':artifact,
            'cli_exit_code':completed.returncode,'stderr':completed.stderr,'artifact_error':artifact_error},indent=2))
        print(json.dumps({'cli_exit_code':completed.returncode,'phase':status['phase'] if status else None,
            'visible_domains':len(artifact.get('domains',[])) if artifact else 0,
            'coverage':status['coverage'] if status else None}))
        return 0 if completed.returncode==0 and model and not artifact_error and artifact and artifact.get('domains') else 1
    if args.full:
        from lib.context.business_domains import discover
        config = json.loads(args.config.read_text()) if args.config else None
        model,status = discover(args.repo,config=config,provider=None)
        args.output.write_text(json.dumps({'status':status,'model':model},indent=2))
        print(json.dumps({'phase':status['phase'],'domains':len(model['domains']) if model else 0,
            'coverage':status['coverage'],'error':status['error']}))
        return 0 if model and status['phase'] in ('complete','partial') else 1
    facts, _ = Extractor(args.repo, DEFAULTS).extract()
    counters = limits(DEFAULTS)
    interpreter = Synthesis(args.repo, DEFAULTS, None, counters)
    model = copy_facts(facts, str(uuid.uuid4()))
    graph = interpreter.graph_scope(model)
    try:
        candidate = interpreter.run(
            graph,
            lambda value: accept_candidate(
                copy.deepcopy(model), graph, value, verified=False))
    except Exception as error:
        print(type(error).__name__, str(error), getattr(error, 'provider_error', {}), file=sys.stderr)
        raise
    args.output.write_text(json.dumps(
        {'graph':graph,'candidate':candidate,'limits':counters}, indent=2))
    print(json.dumps({'activities':len(candidate['activities']),'rules':len(candidate['rules']),
                      'limits':counters}))


if __name__ == '__main__':
    sys.exit(main())
