"""Facts are the same whichever process extracts them.

Every scope, and every cache key derived from a scope, is built from the
facts. A fact whose content depends on the process, such as the order a set
happens to iterate in, gives an unchanged repository new scopes on every run
and discards its validated work.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_business_domain_typescript_memory_stores import SERVICE

ROOT = Path(__file__).resolve().parents[1]
SINKS = '''export type LogRecord = { level: 'debug' | 'info' | 'error'; message: string };

export const sinks = {
  logs: [] as LogRecord[],
  spans: [] as string[],
};

export const log = {
  debug: (message: string) => sinks.logs.push({ level: 'debug', message }),
  info: (message: string) => sinks.logs.push({ level: 'info', message }),
  error: (message: string) => sinks.logs.push({ level: 'error', message }),
};

export const span = (name: string): void => {
  sinks.spans.push(name);
};

export const resetSinks = (): void => {
  sinks.logs.length = 0;
  sinks.spans.length = 0;
};
'''
EXTRACT = '''
import json, sys
from pathlib import Path
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import settings
facts, _ = Extractor(Path(sys.argv[1]), settings({})).extract()
# When the extraction ran, not what it found.
for key in ('generated_at', 'build_id', 'fingerprint'):
    facts.pop(key, None)
for snapshot in facts['source_snapshots'].values():
    snapshot.pop('retrieved_at', None)
print(json.dumps(facts, sort_keys=True))
'''


def _extract(root, seed):
    environment = {**os.environ, 'PYTHONHASHSEED': str(seed),
                   'PYTHONPATH': os.pathsep.join(filter(None, [str(ROOT), os.environ.get('PYTHONPATH')]))}
    result = subprocess.run([sys.executable, '-c', EXTRACT, str(root)], cwd=ROOT,
                            env=environment, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_extraction_does_not_depend_on_the_process_hash_seed(tmp_path):
    source = tmp_path / 'src/payments.ts'
    source.parent.mkdir(parents=True)
    source.write_text(SERVICE)
    # One store several functions of a module write: the evidence it gathers
    # comes from each, in whatever order the functions are visited.
    (tmp_path / 'src/obs.ts').write_text(SINKS)

    runs = [_extract(tmp_path, seed) for seed in (1, 2, 3, 4, 5, 6)]

    assert all(run == runs[0] for run in runs[1:])
    assert any(resource['kind'] == 'memory_store'
               for resource in runs[0]['resources'].values())
