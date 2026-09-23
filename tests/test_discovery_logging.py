import json
import hashlib

from lib.context.discovery_logging import DiscoveryRecorder


def test_recorder_pairs_boundaries_without_persisting_payloads(tmp_path):
    progress = []
    recorder = DiscoveryRecorder(tmp_path, progress=progress.append)

    with recorder.boundary("provider.generate", {"prompt": "private input"}) as boundary:
        boundary.success({"response": "private output"})
    try:
        with recorder.boundary("semantic.normalize", {"response": "rejected output"}):
            raise ValueError("invalid response")
    except ValueError:
        pass
    recorder.progress("refresh", "Safe status")
    recorder.finish("failed", {"error": "private output"})

    text = recorder.events_path.read_text()
    events = [json.loads(line) for line in text.splitlines()]
    assert [event["direction"] for event in events[:4]] == [
        "input", "output", "input", "error"]
    assert "private input" not in text
    assert "private output" not in text
    assert "rejected output" not in text
    assert progress == [{"stage": "refresh", "message": "Safe status",
                         "level": "step", "details": {}}]
    manifest = json.loads((recorder.directory/"manifest.json").read_text())
    assert manifest["event_count"] == len(events)
    assert manifest["segments"][0]["sha256"] == hashlib.sha256(
        recorder.events_path.read_bytes()).hexdigest()
    boundary_events = [event for event in events if event["boundary_id"]]
    by_boundary = {}
    for event in boundary_events:
        by_boundary.setdefault(event["boundary_id"], []).append(event)
        descriptor = event["descriptor"]
        if descriptor is not None:
            assert descriptor["schema"]
            assert len(descriptor["sha256"]) == 64
            assert isinstance(descriptor["bytes"], int)
            assert isinstance(descriptor["counts"], dict)
    assert all([event["direction"] for event in pair] in
               (["input", "output"], ["input", "error"])
               for pair in by_boundary.values())


def test_recorder_closes_abandoned_boundary_and_redacts_sensitive_metadata(tmp_path):
    recorder = DiscoveryRecorder(tmp_path)
    recorder.boundary("artifact.read", {"path": "private.py"},
                      schema="ArtifactReference", artifact="safe.json",
                      metadata={"api_key": "short-secret", "prompt": "raw prompt"})
    recorder.emit("provider", "error", error={
        "message": "token=short-secret authorization=Bearer-secret",
        "rejected_response": {"value": "provider output"}})
    recorder.finish("failed")

    events = [json.loads(line) for line in recorder.events_path.read_text().splitlines()]
    text = recorder.events_path.read_text()
    assert "short-secret" not in text and "raw prompt" not in text
    assert "provider output" not in text
    pair = [event for event in events if event["boundary_id"]]
    assert [event["direction"] for event in pair] == ["input", "error"]
    assert pair[0]["descriptor"]["artifact"] == "safe.json"


def test_progress_callback_cannot_fail_discovery(tmp_path):
    def broken_callback(_event):
        raise RuntimeError("closed stream")

    recorder = DiscoveryRecorder(tmp_path, progress=broken_callback)
    recorder.progress("refresh", "Still recorded")
    recorder.finish("complete")
    assert "Still recorded" in recorder.events_path.read_text()
