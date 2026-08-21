"""Tests for email-based actor identity in lib/serve/server.py.

All 8 server-side cases from the spec (speed-define-ceremony-identity.md):
  _arbitrate_claim (6): new claim with email, same-actor reclaim,
      different-email same-name, old-event fallback match,
      old-event fallback different-name, event includes email
  do_POST handler (2): reads actor_email, missing actor_email defaults

The remaining 40 cases (bash) are in test_actor_identity.sh.

Run: python3 tests/test_server_identity.py
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

# Set up environment before importing server module
_tmpdir = tempfile.mkdtemp(prefix="speed-server-identity-test-")
_events_dir = Path(_tmpdir) / "shared" / "events"
_events_dir.mkdir(parents=True)
(Path(_tmpdir) / "local" / "locks").mkdir(parents=True)
(Path(_tmpdir) / "shared" / "roster").mkdir(parents=True)
(Path(_tmpdir) / "shared" / "features").mkdir(parents=True)

os.environ["SPEED_STATE_DIR"] = _tmpdir
os.environ["SPEED_SHARED_DIR"] = str(Path(_tmpdir) / "shared")
os.environ["SPEED_EVENTS_DIR"] = str(_events_dir)
os.environ["SPEED_ROSTER_DIR"] = str(Path(_tmpdir) / "shared" / "roster")
os.environ["SPEED_PROJECT_ROOT"] = _tmpdir

sys.path.insert(0, str(Path(__file__).parent.parent))

import lib.serve.server as srv
from lib.serve.server import _arbitrate_claim, SpeedHandler

PASS = 0
FAIL = 0


def assert_eq(label, expected, actual):
    global PASS, FAIL
    if expected == actual:
        print(f"  PASS: {label}")
        PASS += 1
    else:
        print(f"  FAIL: {label} (expected '{expected}', got '{actual}')")
        FAIL += 1


def assert_true(label, value, detail=""):
    global PASS, FAIL
    if value:
        print(f"  PASS: {label}")
        PASS += 1
    else:
        print(f"  FAIL: {label} ({detail})")
        FAIL += 1


def clear_events():
    """Remove all event files and stale locks between tests."""
    for f in _events_dir.glob("*.jsonl"):
        f.unlink()
    locks = Path(_tmpdir) / "local" / "locks"
    if locks.exists():
        for d in locks.iterdir():
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass


def write_claim_event(feature, actor, actor_email=None):
    """Write a claim event directly (bypasses _arbitrate_claim for test setup)."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc)
    slug = actor.lower().replace(" ", "-")
    filename = f"{ts.strftime('%Y%m%dT%H%M%SZ')}_{slug}_feature-claimed_{feature}.jsonl"
    event = {
        "timestamp": ts.isoformat(),
        "type": "feature.claimed",
        "feature": feature,
        "actor": actor,
        "data": {"actor": actor},
    }
    if actor_email is not None:
        event["actor_email"] = actor_email
    (_events_dir / filename).write_text(json.dumps(event))


# ═══════════════════════════════════════════════════════════════
# Unit tests — _arbitrate_claim (6 tests)
# ═══════════════════════════════════════════════════════════════
print("")
print("=== _arbitrate_claim ===")

# 1. test_arbitrate_new_claim_with_email
clear_events()
result = _arbitrate_claim("feat-1", "Alice", "alice@co.com")
assert_eq("test_arbitrate_new_claim_with_email (success)", True, result["success"])
event_files = list(_events_dir.glob("*_feature-claimed_feat-1.jsonl"))
assert_eq("test_arbitrate_new_claim_with_email (event written)", 1, len(event_files))
if event_files:
    ev = json.loads(event_files[0].read_text())
    assert_eq(
        "test_arbitrate_new_claim_with_email (actor_email)",
        "alice@co.com",
        ev.get("actor_email"),
    )

# 2. test_arbitrate_same_actor_reclaim (self-contained, no dependency on test #1)
clear_events()
_arbitrate_claim("feat-2", "Alice", "alice@co.com")  # initial claim
result = _arbitrate_claim("feat-2", "Alice", "alice@co.com")  # re-claim
assert_eq("test_arbitrate_same_actor_reclaim", True, result["success"])

# 3. test_arbitrate_different_email_same_name
clear_events()
write_claim_event("feat-3", "John Smith", "john@A.com")
result = _arbitrate_claim("feat-3", "John Smith", "john@B.com")
assert_eq("test_arbitrate_different_email_same_name (rejected)", False, result["success"])
assert_eq("test_arbitrate_different_email_same_name (owner)", "John Smith", result["owner"])

# 4. test_arbitrate_fallback_old_claim
clear_events()
write_claim_event("feat-4", "John Smith")  # no actor_email
result = _arbitrate_claim("feat-4", "John Smith", "john@B.com")
assert_eq("test_arbitrate_fallback_old_claim (name match)", True, result["success"])

# 5. test_arbitrate_fallback_old_claim_different_name
clear_events()
write_claim_event("feat-5", "Alice")  # no actor_email
result = _arbitrate_claim("feat-5", "Bob", "bob@co.com")
assert_eq("test_arbitrate_fallback_old_claim_different_name", False, result["success"])

# 6. test_arbitrate_event_includes_email
clear_events()
_arbitrate_claim("feat-6", "Dave", "dave@co.com")
event_files = list(_events_dir.glob("*_feature-claimed_feat-6.jsonl"))
assert_eq("test_arbitrate_event_includes_email (file exists)", 1, len(event_files))
if event_files:
    ev = json.loads(event_files[0].read_text())
    assert_true(
        "test_arbitrate_event_includes_email (has key)",
        "actor_email" in ev,
        f"keys: {list(ev.keys())}",
    )
    assert_eq("test_arbitrate_event_includes_email (value)", "dave@co.com", ev.get("actor_email"))


# ═══════════════════════════════════════════════════════════════
# Unit tests — do_POST handler (2 tests)
# ═══════════════════════════════════════════════════════════════
print("")
print("=== do_POST handler ===")


def _make_handler(body_dict, path="/api/claim"):
    """Build a SpeedHandler wired to mock I/O for testing do_POST."""
    body_bytes = json.dumps(body_dict).encode()

    handler = SpeedHandler.__new__(SpeedHandler)

    class _FakeServer:
        server_name = "localhost"
        server_port = 4450

    handler.server = _FakeServer()
    handler.client_address = ("127.0.0.1", 9999)
    handler.rfile = io.BytesIO(body_bytes)
    handler.wfile = io.BytesIO()
    handler.headers = {
        "Content-Length": str(len(body_bytes)),
        "Content-Type": "application/json",
    }
    handler.path = path
    handler._response_code = None

    def send_response(code, message=None):
        handler._response_code = code

    def send_header(k, v):
        pass

    def end_headers():
        pass

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers

    return handler


# 7. test_handler_reads_actor_email
clear_events()
captured = {}
original_arbitrate = srv._arbitrate_claim


def _fake_arbitrate(feature, actor, actor_email):
    captured["feature"] = feature
    captured["actor"] = actor
    captured["actor_email"] = actor_email
    return {"success": True, "owner": actor, "message": "Claimed"}


srv._arbitrate_claim = _fake_arbitrate
try:
    handler = _make_handler({"feature": "f", "actor": "A", "actor_email": "a@b.com"})
    handler.do_POST()
    assert_eq("test_handler_reads_actor_email", "a@b.com", captured.get("actor_email"))
finally:
    srv._arbitrate_claim = original_arbitrate

# 8. test_handler_missing_actor_email
clear_events()
captured = {}
srv._arbitrate_claim = _fake_arbitrate
try:
    handler = _make_handler({"feature": "f", "actor": "A"})  # no actor_email field
    handler.do_POST()
    assert_eq(
        "test_handler_missing_actor_email (defaults to empty string)",
        "",
        captured.get("actor_email"),
    )
finally:
    srv._arbitrate_claim = original_arbitrate


# ── Summary ──────────────────────────────────────────────────
print("")
print("=" * 40)
print(f"Results: {PASS} passed, {FAIL} failed")
print("=" * 40)

import shutil

shutil.rmtree(_tmpdir, ignore_errors=True)

sys.exit(0 if FAIL == 0 else 1)
