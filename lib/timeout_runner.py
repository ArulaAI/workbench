#!/usr/bin/env python3
"""POSIX fallback for Workbench's GNU timeout usage (duration + --kill-after).

Standard-library only. Child stdio is inherited so agent streaming is unchanged.
"""
import argparse
import math
import os
import re
import signal
import subprocess
import sys
import time


class Interrupted(Exception):
    def __init__(self, signum):
        self.signum = signum


def duration(value):
    match = re.fullmatch(r'(\d+(?:\.\d*)?|\.\d+)([smhd]?)', value)
    if not match:
        raise argparse.ArgumentTypeError('duration must be a nonnegative number, optionally suffixed s/m/h/d')
    seconds = float(match[1]) * {'': 1, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[match[2]]
    if not math.isfinite(seconds):
        raise argparse.ArgumentTypeError('duration must be finite')
    return seconds


class Parser(argparse.ArgumentParser):
    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, sys.stderr)
        raise SystemExit(125 if status else 0)


def send_group(process, signum):
    try:
        os.killpg(process.pid, signum)
        return True
    except ProcessLookupError:
        return False


def stop_group(process, signum, grace):
    end = time.monotonic() + grace
    def shorten_cleanup(_signum, _frame):
        nonlocal end
        # Workbench kills its wrapper after 3 seconds on cancellation.
        end = min(end, time.monotonic() + 1.0)

    # Finish cleanup even if interrupted again, within Workbench's budget.
    signal.signal(signal.SIGINT, shorten_cleanup)
    signal.signal(signal.SIGTERM, shorten_cleanup)
    send_group(process, signum)
    while time.monotonic() < end:
        process.poll()  # Reap the leader; descendants may still be running.
        try:
            alive = send_group(process, 0)
        except PermissionError:
            # macOS can report EPERM while the leader exits, before reaping.
            # Retry rather than assuming its descendants have disappeared.
            alive = True
        if not alive:
            process.wait()
            return False
        time.sleep(min(0.02, max(0, end - time.monotonic())))
    process.poll()
    forced = send_group(process, signal.SIGKILL)
    process.wait()
    return forced


def main():
    parser = Parser(description=__doc__)
    parser.add_argument('--kill-after', type=duration, default=10.0)
    parser.add_argument('duration', type=duration)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error('a command is required')
    if os.name != 'posix':
        parser.error('the Python fallback requires POSIX process groups; use GNU timeout on Windows')

    def interrupted(signum, _frame):
        raise Interrupted(signum)

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    process = None
    try:
        process = subprocess.Popen(args.command, start_new_session=True)
        try:
            code = process.wait(timeout=args.duration or None)
            return code if code >= 0 else 128 - code
        except subprocess.TimeoutExpired:
            return 137 if stop_group(process, signal.SIGTERM, args.kill_after) else 124
    except Interrupted as error:
        if process is not None:
            # cleanup_all force-kills registered wrappers after 3 seconds.
            # Finish descendant cleanup first; deadline grace is unchanged.
            stop_group(process, error.signum, min(args.kill_after, 1.0))
        return 128 + error.signum
    except OSError as error:
        print(f'timeout: {error}', file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126


if __name__ == '__main__':
    sys.exit(main())
