"""Process-level tests for the bundled POSIX timeout runner."""
import os
import shutil
import importlib.util
from unittest import mock
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'lib/timeout_runner.py'

@unittest.skipUnless(os.name == 'posix', 'POSIX process groups')
class TimeoutRunner(unittest.TestCase):
    def run_command(self, body, duration='2', grace='0.2', input=None):
        return subprocess.run([sys.executable, str(RUNNER), '--kill-after='+grace, duration,
                               sys.executable, '-c', body], input=input, text=True,
                              capture_output=True, timeout=5)

    def test_backend_selection_always_uses_python_on_posix(self):
        root = RUNNER.parent.parent
        deps = (root / 'lib/deps.sh').read_text()
        available = deps[deps.index('_python_timeout_available() {'):deps.index('\n_check_timeout() {')]
        provider = (root / 'lib/provider.sh').read_text().split('# ── JSON extraction')[0]
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env.update(PATH=tmp, SPEED_PYTHON=sys.executable)
            script = ('set -euo pipefail\nLIB_DIR=' + repr(str(root / 'lib')) +
                      '\nEXIT_CONFIG_ERROR=3\n_deps_python=""\n'
                      '_resolve_python() { _deps_python="$SPEED_PYTHON"; }\n'
                      'log_error_block() { echo "$*" >&2; }\n' + available + '\n' + provider +
                      '\nprintf "%s\\n" "$_TIMEOUT_CMD"\n')
            r = subprocess.run(['/bin/bash','-c',script],env=env,text=True,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(r.stdout.strip(),str(root / 'lib/timeout'))
            # Installed GNU commands must not change the POSIX backend.
            native = Path(tmp)/'timeout'
            native.write_text('#!/bin/sh\nexit 0\n'); native.chmod(0o755)
            r = subprocess.run(['/bin/bash','-c',script],env=env,text=True,capture_output=True)
            self.assertEqual(r.stdout.strip(),str(root / 'lib/timeout'))
            native.rename(Path(tmp)/'gtimeout')
            r = subprocess.run(['/bin/bash','-c',script],env=env,text=True,capture_output=True)
            self.assertEqual(r.stdout.strip(),str(root / 'lib/timeout'))
            for platform in ('msys', 'cygwin'):
                r = subprocess.run(['/bin/bash','-c','OSTYPE='+platform+'\n'+script],env=env,text=True,capture_output=True)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertEqual(r.stdout.strip(),'gtimeout')
            env['SPEED_PYTHON']='/nonexistent/python-timeout-test'
            r = subprocess.run(['/bin/bash','-c',script],env=env,text=True,capture_output=True)
            self.assertEqual(r.returncode,3,r.stderr)

    def test_learning_bridge_with_timeout_path_containing_spaces(self):
        root = RUNNER.parent.parent
        with tempfile.TemporaryDirectory(prefix='workbench space ') as tmp:
            install = Path(tmp)
            (install/'lib').mkdir()
            for name in ('timeout', 'timeout_runner.py'):
                shutil.copy2(root/'lib'/name,install/'lib'/name)
            env=os.environ.copy()
            env.update(SPEED_PYTHON=sys.executable, SCRIPT_DIR=str(root),
                       SPEED_DIR=str(root), PROJECT_ROOT=tmp, STATE_DIR=str(install/'.speed'),
                       TIMEOUT_PATH=str(install/'lib/timeout'), PYTHONDONTWRITEBYTECODE='1')
            code='source "$SCRIPT_DIR/lib/learn_bridge.sh"\n_TIMEOUT_CMD="$TIMEOUT_PATH"\nlearn_conventions'
            r=subprocess.run(['/bin/bash','-c',code],env=env,text=True,capture_output=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)

    def test_streams_and_preserves_exit_code(self):
        r = self.run_command('import sys; print(sys.stdin.read()); print("stderr",file=sys.stderr); sys.exit(7)', input='hello')
        self.assertEqual(r.returncode, 7, r.stderr)
        self.assertEqual(r.stdout.strip(), 'hello')
        self.assertEqual(r.stderr.strip(), 'stderr')

    def test_timeout_returns_124(self):
        r = self.run_command('import time; time.sleep(10)', duration='0.1')
        self.assertEqual(r.returncode, 124, r.stderr)

    def test_ignored_term_is_force_killed(self):
        r = self.run_command('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(10)', duration='0.2')
        self.assertEqual(r.returncode, 137, r.stderr)

    def test_zero_duration_disables_deadline(self):
        r = self.run_command('import time; time.sleep(0.1); print("done")', duration='0')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'done')

    def test_invalid_duration_and_missing_command(self):
        for args, expected in [(['-1', 'echo'],125), (['nan', 'echo'],125), (['1', '/nonexistent/timeout-test'],127)]:
            r = subprocess.run([sys.executable, str(RUNNER), *args], text=True, capture_output=True)
            self.assertEqual(r.returncode, expected, r.stderr)

    def test_kills_descendant_even_when_parent_exits_on_term(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'child.pid'
            child = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'
            body = ('import subprocess,sys,signal,time; from pathlib import Path; '
                    f'p=subprocess.Popen([sys.executable,"-c",{child!r}]); '
                    f'Path({str(pidfile)!r}).write_text(str(p.pid)); '
                    'signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); time.sleep(30)')
            try:
                r = self.run_command(body, duration='0.4')
                self.assertEqual(r.returncode,137,r.stderr)
                self.assert_dead(int(pidfile.read_text()))
            finally:
                if pidfile.exists():
                    try: os.kill(int(pidfile.read_text()),signal.SIGKILL)
                    except ProcessLookupError: pass

    def assert_dead(self, pid):
        for _ in range(40):
            try: os.kill(pid,0)
            except ProcessLookupError: return
            time.sleep(0.05)
        self.fail(f'child {pid} still exists')

    def test_group_probe_retries_macos_exit_window(self):
        spec=importlib.util.spec_from_file_location('timeout_under_test',RUNNER)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'],start_new_session=True)
        real_send=module.send_group
        probes=[]
        def send(proc, signum):
            if signum == 0 and not probes:
                probes.append(signum)
                raise PermissionError('macOS group is exiting but not yet reaped')
            return real_send(proc,signum)
        handlers={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
        try:
            with mock.patch.object(module,'send_group',side_effect=send):
                self.assertFalse(module.stop_group(process,signal.SIGTERM,0.2))
            self.assertTrue(probes)
        finally:
            try:
                try: process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait()
            finally:
                for sig,handler in handlers.items(): signal.signal(sig,handler)

    def test_workbench_cleanup_does_not_strand_term_resistant_child(self):
        self.check_workbench_cleanup('600', '')

    def test_workbench_cleanup_during_deadline_grace(self):
        self.check_workbench_cleanup('0.2', 'sleep 0.4')

    def check_workbench_cleanup(self, deadline, delay):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile=Path(tmp)/'pid'
            body=f'import signal,os,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(30)'
            env=os.environ.copy()
            env.update(SPEED_PYTHON=sys.executable, ROOT=str(RUNNER.parent.parent),
                       BODY=body, PIDFILE=str(pidfile))
            code = '\n'.join([
                'set -euo pipefail', 'source "$ROOT/lib/cleanup.sh"',
                f'"$ROOT/lib/timeout" --kill-after=10 {deadline} "$SPEED_PYTHON" -c "$BODY" >/dev/null 2>&1 &',
                'cleanup_register_pid "$!"',
                'for ((i=0; i<100; i++)); do [[ -f "$PIDFILE" ]] && break; sleep 0.01; done',
                '[[ -f "$PIDFILE" ]]', delay, 'cleanup_all',
            ])
            try:
                r=subprocess.run(['/bin/bash','-c',code],env=env,text=True,capture_output=True,timeout=8)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assert_dead(int(pidfile.read_text()))
            finally:
                if pidfile.exists():
                    try: os.kill(int(pidfile.read_text()),signal.SIGKILL)
                    except ProcessLookupError: pass

    def test_interrupt_is_forwarded_and_child_is_reaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp)/'pid'
            body=f'import os,time; from pathlib import Path; Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(30)'
            p=subprocess.Popen([sys.executable,str(RUNNER),'--kill-after=0.2','10',sys.executable,'-c',body],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                for _ in range(100):
                    if pidfile.exists(): break
                    time.sleep(0.01)
                self.assertTrue(pidfile.exists(),'child did not start')
                p.send_signal(signal.SIGINT)
                out,err=p.communicate(timeout=3)
                self.assertEqual(p.returncode,130,err)
                self.assert_dead(int(pidfile.read_text()))
            finally:
                if p.poll() is None: p.kill(); p.wait()

if __name__ == '__main__': unittest.main()
