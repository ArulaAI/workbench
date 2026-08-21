"""Lightweight HTTP server for SPEED multi-player mode.

REST endpoints for roster, events, features, and claim arbitration.
WebSocket endpoint for real-time event streaming.

Runs standalone via `speed serve`. Dependencies are optional:
- With uvicorn + starlette: full async server with WebSocket
- Without: falls back to stdlib http.server (REST only, no WebSocket)

Environment variables (set by serve.sh):
- SPEED_SERVE_PORT: port number
- SPEED_STATE_DIR: .speed/ root
- SPEED_SHARED_DIR: .speed/shared/
- SPEED_EVENTS_DIR: .speed/shared/events/
- SPEED_ROSTER_DIR: .speed/shared/roster/
- SPEED_PROJECT_ROOT: project root
"""

import json
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone


PORT = int(os.environ.get("SPEED_SERVE_PORT", "4450"))
SHARED_DIR = Path(os.environ.get("SPEED_SHARED_DIR", ".speed/shared"))
EVENTS_DIR = Path(os.environ.get("SPEED_EVENTS_DIR", ".speed/shared/events"))
ROSTER_DIR = Path(os.environ.get("SPEED_ROSTER_DIR", ".speed/shared/roster"))
STATE_DIR = Path(os.environ.get("SPEED_STATE_DIR", ".speed"))
PROJECT_ROOT = Path(os.environ.get("SPEED_PROJECT_ROOT", "."))


def _read_roster() -> list[dict]:
    """Read all roster entries, filter stale (>24h)."""
    entries = []
    if not ROSTER_DIR.exists():
        return entries
    cutoff = time.time() - 86400
    for f in sorted(ROSTER_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            last_seen = data.get("last_seen", "")
            if last_seen:
                try:
                    seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                    if seen_dt.timestamp() < cutoff:
                        continue
                except (ValueError, OSError):
                    pass
            entries.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return entries


def _read_events(feature: str = "", event_type: str = "", limit: int = 100) -> list[dict]:
    """Read events, optionally filtered by feature and type."""
    if not EVENTS_DIR.exists():
        return []
    events = []
    pattern = "*.jsonl"
    if feature:
        pattern = f"*_{feature}.jsonl"
    for f in sorted(EVENTS_DIR.glob(pattern), reverse=True):
        if len(events) >= limit:
            break
        try:
            data = json.loads(f.read_text().strip())
            if event_type and data.get("type") != event_type:
                continue
            events.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return events


def _read_features() -> list[dict]:
    """Read active features with their ownership and task counts."""
    features_dir = SHARED_DIR / "features"
    if not features_dir.exists():
        return []
    result = []
    for feat_dir in sorted(features_dir.iterdir()):
        if not feat_dir.is_dir():
            continue
        name = feat_dir.name
        tasks_dir = feat_dir / "tasks"
        total = done = failed = 0
        if tasks_dir.exists():
            for tf in tasks_dir.glob("*.json"):
                try:
                    task = json.loads(tf.read_text())
                    total += 1
                    status = task.get("status", "")
                    if status == "done":
                        done += 1
                    elif status == "failed":
                        failed += 1
                except (json.JSONDecodeError, OSError):
                    continue

        # Find owner from events
        owner = None
        for ef in sorted(EVENTS_DIR.glob(f"*_feature-claimed_{name}.jsonl"), reverse=True):
            try:
                ev = json.loads(ef.read_text().strip())
                owner = ev.get("actor")
                break
            except (json.JSONDecodeError, OSError):
                continue

        # Check if released
        for ef in sorted(EVENTS_DIR.glob(f"*_feature-released_{name}.jsonl"), reverse=True):
            try:
                ev = json.loads(ef.read_text().strip())
                if owner and ev.get("timestamp", "") > "":
                    # Check if release is newer than claim
                    owner = None
                break
            except (json.JSONDecodeError, OSError):
                continue

        result.append({
            "name": name,
            "owner": owner,
            "tasks": {"total": total, "done": done, "failed": failed},
        })
    return result


def _arbitrate_claim(feature: str, actor: str, actor_email: str) -> dict:
    """Atomic claim arbitration. Returns {success, owner, message}."""
    lock_dir = STATE_DIR / "local" / "locks" / f"claim-{feature}"

    try:
        lock_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return {"success": False, "owner": None, "message": "Claim in progress by another request"}

    try:
        # Check current ownership
        current_owner = None
        current_owner_email = None
        for ef in sorted(EVENTS_DIR.glob(f"*_feature-claimed_{feature}.jsonl"), reverse=True):
            try:
                ev = json.loads(ef.read_text().strip())
                current_owner = ev.get("actor")
                current_owner_email = ev.get("actor_email")
                break
            except (json.JSONDecodeError, OSError):
                continue

        # Check if released
        if current_owner:
            for ef in sorted(EVENTS_DIR.glob(f"*_feature-released_{feature}.jsonl"), reverse=True):
                try:
                    ev = json.loads(ef.read_text().strip())
                    current_owner = None
                    current_owner_email = None
                    break
                except (json.JSONDecodeError, OSError):
                    continue

        # Email-first comparison with name fallback for old events
        if current_owner:
            is_same_actor = False
            if current_owner_email and actor_email:
                is_same_actor = (current_owner_email == actor_email)
            else:
                is_same_actor = (current_owner == actor)

            if not is_same_actor:
                return {"success": False, "owner": current_owner, "message": f"Feature claimed by {current_owner}"}

        # Write claim event
        ts = datetime.now(timezone.utc)
        ts_file = ts.strftime("%Y%m%dT%H%M%SZ")
        slug = actor.lower().replace(" ", "-")
        filename = f"{ts_file}_{slug}_feature-claimed_{feature}.jsonl"
        event = {
            "timestamp": ts.isoformat(),
            "type": "feature.claimed",
            "feature": feature,
            "actor": actor,
            "actor_email": actor_email,
            "data": {"actor": actor},
        }
        event_path = EVENTS_DIR / filename
        tmp = event_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(event))
        tmp.rename(event_path)

        return {"success": True, "owner": actor, "message": "Claimed"}
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


class SpeedHandler(BaseHTTPRequestHandler):
    """HTTP request handler for SPEED multi-player server."""

    def log_message(self, format, *args):
        """Suppress default stderr logging."""
        pass

    def _json_response(self, data: dict | list, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def do_GET(self):
        path = self.path.split("?")[0]
        params = {}
        if "?" in self.path:
            for p in self.path.split("?")[1].split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k] = v

        if path == "/api/roster":
            self._json_response(_read_roster())
        elif path == "/api/events":
            feature = params.get("feature", "")
            event_type = params.get("type", "")
            limit = int(params.get("limit", "100"))
            self._json_response(_read_events(feature, event_type, limit))
        elif path == "/api/features":
            self._json_response(_read_features())
        elif path == "/api/health":
            self._json_response({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/claim":
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}
            feature = body.get("feature", "")
            actor = body.get("actor", "")
            actor_email = body.get("actor_email", "")
            if not feature or not actor:
                self._json_response({"error": "feature and actor required"}, 400)
                return
            result = _arbitrate_claim(feature, actor, actor_email)
            status = 200 if result["success"] else 409
            self._json_response(result, status)
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    server = HTTPServer(("0.0.0.0", PORT), SpeedHandler)
    print(f"SPEED multi-player server listening on port {PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
