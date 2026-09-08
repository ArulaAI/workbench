#!/usr/bin/env python3
"""Start, inspect or stop this worktree's isolated authoring studio preview."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".speed/studio"
STATE = RUNTIME / "preview.json"


def start_time(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True)
    return result.stdout.strip()


def occupied(port):
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def health(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.load(response)
    except Exception:
        return None


def stop():
    if not STATE.exists():
        print("No preview processes recorded for this worktree.")
        return
    state = json.loads(STATE.read_text())
    for process in state["processes"]:
        if process["started"] and start_time(process["pid"]) == process["started"]:
            try:
                os.killpg(process["pid"], signal.SIGTERM)
                print(f"Stopped {process['name']} (PID {process['pid']}).")
            except ProcessLookupError:
                pass
    STATE.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"], nargs="?", default="start")
    parser.add_argument("--frontend-port", type=int, default=3011)
    parser.add_argument("--backend-port", type=int, default=4451)
    args = parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if args.action == "stop":
        stop(); return
    if args.action == "status":
        if not STATE.exists():
            print("Preview is not running through this launcher."); return
        state = json.loads(STATE.read_text())
        for process in state["processes"]:
            running = bool(process["started"] and start_time(process["pid"]) == process["started"])
            print(f"{process['name']}: {'running' if running else 'stopped'} (PID {process['pid']})")
        print(state["url"]); return
    if STATE.exists():
        old = json.loads(STATE.read_text())
        if any(p["started"] and start_time(p["pid"]) == p["started"] for p in old["processes"]):
            print(f"This worktree's preview is already running: {old['url']}"); return
    for port in (args.frontend_port, args.backend_port):
        if occupied(port):
            sys.exit(f"Port {port} is in use. Choose another port; the existing process was left running.")
    python = ROOT / ".venv/bin/python"
    npm = shutil.which("npm")
    if not python.exists() or not npm or not (ROOT / "dashboard/frontend/node_modules").exists():
        sys.exit("Install the backend .venv and frontend npm dependencies first; see docs/authoring-studio-preview.md.")
    env = dict(os.environ)
    env.update({
        "DASHBOARD_ALLOWED_ORIGINS": f"http://localhost:{args.frontend_port},http://127.0.0.1:{args.frontend_port}",
        "NEXT_PUBLIC_GRAPHQL_URL": f"http://127.0.0.1:{args.backend_port}/graphql",
        "NEXT_PUBLIC_STUDIO_URL": f"http://127.0.0.1:{args.backend_port}/studio",
        "SPEED_NEXT_DIST_DIR": f".next-studio-{args.backend_port}",
        "SPEED_TYPESCRIPT_CONFIG": "tsconfig.app.json",
    })
    # A standalone process group keeps the preview available when the launching shell exits.
    commands = [
        ("backend", [str(python), "-m", "dashboard.backend", "--port", str(args.backend_port), "--project-root", str(ROOT)], ROOT),
        ("frontend", [npm, "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(args.frontend_port)], ROOT / "dashboard/frontend"),
    ]
    state = {"url": f"http://localhost:{args.frontend_port}/define/studio", "processes": []}
    try:
        for name, command, cwd in commands:
            with (RUNTIME / f"{name}.log").open("a") as log:
                process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            state["processes"].append({"name": name, "pid": process.pid, "started": start_time(process.pid)})
            STATE.write_text(json.dumps(state, indent=2))
        for _ in range(40):
            result = health(f"http://127.0.0.1:{args.backend_port}/studio/health")
            if result and result.get("project_root") == str(ROOT) and occupied(args.frontend_port):
                print(f"Authoring studio: {state['url']}")
                print(f"Logs and saved work: {RUNTIME}")
                return
            time.sleep(.5)
        sys.exit(f"Preview did not become ready. Inspect {RUNTIME}/backend.log and frontend.log. Saved work is retained.")
    except (KeyboardInterrupt, OSError):
        stop(); raise


if __name__ == "__main__":
    main()
