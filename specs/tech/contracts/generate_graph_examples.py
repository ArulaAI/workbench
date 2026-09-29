"""Regenerate the four compact graph contract specimens deterministically."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from lib.context.business_domain_schema import (
    DEFAULTS, account_artifact_bytes, canonical, copy_facts, digest, limits,
    record, validate, validate_references,
)


ROOT = Path(__file__).parent / "examples"


def graph(name: str, published: bool) -> dict:
    snapshot = json.loads((ROOT / f"{name}.snapshot.json").read_text())
    excerpt = snapshot["fragments"][0]["text"]
    evidence_id = f"ev:{name}"
    resource_id = f"resource:{name}"
    anchor_id = f"anchor:{name}"
    symbol_id = f"symbol:{name}"
    representation_id = f"anchor_representation:{name}"
    correspondence_id = f"anchor_correspondence:{name}"
    trace_id = f"trace:{name}"
    protocol = {"api": "http", "dag": "workflow"}.get(name, name)
    operation = record(
        "Operation", protocol=protocol, service_resource_id=resource_id,
        name=f"{name.title()} example", method="POST" if name == "api" else None,
        path="/examples" if name == "api" else None,
    )
    representation = record(
        "AnchorRepresentation", id=representation_id, role="registration",
        identity_key=f"{name}:fixture", source_id=resource_id, symbol_id=symbol_id,
        operation=operation, registration=None, eligibility="eligible",
        visibility="external", evidence_ids=[evidence_id], resolution="resolved",
        reason=None,
    )
    correspondence = record(
        "AnchorCorrespondence", id=correspondence_id,
        from_representation=representation_id,
        to_representations=[representation_id], relationship_edges=[],
        state="resolved", evidence_ids=[evidence_id],
        reason="The authored fixture is its canonical source representation.",
    )
    anchor = record(
        "Anchor", id=anchor_id, kind="http" if name == "api" else name,
        source_id=resource_id, symbol_id=symbol_id, operation=operation,
        status="processed" if published else "candidate",
        evidence_ids=[evidence_id], resolution="resolved", reason=None,
        canonical_anchor_id=anchor_id, eligibility="eligible",
        representations=[representation], correspondences=[correspondence],
    )
    configured_limits = limits(DEFAULTS)
    configured_limits.update(
        semantic_units_total=1, semantic_units_validated=1 if published else 0,
        semantic_units_pending=0 if published else 1,
    )
    facts = record(
        "FactsArtifact", schema_version=1,
        generated_at="2026-01-01T00:00:00+00:00",
        build_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"speed:{name}:facts")),
        limits=configured_limits,
    )
    facts["resources"][resource_id] = record(
        "Resource", id=resource_id, kind="repository_file",
        name=f"{name}.fixture", language=name,
        evidence_ids=[evidence_id], resolution="resolved", reason=None,
    )
    facts["symbols"][symbol_id] = record(
        "Symbol", id=symbol_id, qualified_name=f"{name}.fixture::behavior",
        signature="behavior()", kind="function", file=f"{name}.fixture",
        evidence_ids=[evidence_id], resolution="resolved", reason=None,
    )
    facts["evidence"][evidence_id] = record(
        "Evidence", id=evidence_id, source_kind="source",
        locator={"kind": "repository_span", "path": f"{name}.fixture",
                 "start_line": 1, "end_line": excerpt.count("\n") + 1,
                 "source_hash": snapshot["source_hash"],
                 "snapshot_id": snapshot["snapshot_id"],
                 "pointer": "/fragments/0/text"},
        content_hash=digest(excerpt.encode()), excerpt=excerpt,
        claim_kind="source_observation", extractor="authored-fixture",
        extractor_version="1",
    )
    facts["source_snapshots"][snapshot["snapshot_id"]] = record(
        "Snapshot", id=snapshot["snapshot_id"], resource_kind=name,
        resource_identity=f"{name}.fixture", content_hash=snapshot["source_hash"],
        local_blob_path=f"{name}.snapshot.json",
        retrieved_at="2026-01-01T00:00:00+00:00",
    )
    facts["anchors"][anchor_id] = anchor
    obligation_id = f"trace_obligation:{name}"
    facts["trace_obligations"][obligation_id] = record(
        "TraceObligation", id=obligation_id, trace_id=trace_id,
        kind="implementation_selection", origin_ref={"kind": "symbol", "id": symbol_id},
        edge_id=None, candidate_target_ids=[symbol_id], status="satisfied",
        reason_code="IMPLEMENTATION_REACHED",
        reason="The authored fixture identifies its implementation.",
        evidence_ids=[evidence_id],
    )
    facts["traces"][trace_id] = record(
        "Trace", id=trace_id, anchor_id=anchor_id, symbol_ids=[symbol_id], edge_ids=[],
        obligation_ids=[obligation_id],
        frontier_ids=[], stop_reasons=[], ui_interaction=None,
        evidence_ids=[evidence_id], traversal_complete=True,
        resolution="resolved", reason=None,
    )
    facts["coverage"].update(
        anchors_total=1, representations_total=1,
        representations_canonicalized=1, anchors_processed=1 if published else 0,
        anchors_pending=0 if published else 1, evidence_valid=1,
    )
    facts["fingerprint"] = record(
        "Fingerprint", sources=digest({name: snapshot["source_hash"]}),
        configuration=digest({}), extractors=digest({"fixture": 1}),
        prompts=digest({}), provider=digest({}), overrides=digest({}),
        snapshots=digest(snapshot),
    )
    facts["fingerprint"]["value"] = digest(
        {key: value for key, value in facts["fingerprint"].items() if key != "value"})
    if not published:
        account_artifact_bytes(facts)
        validate(facts, "FactsArtifact")
        validate_references(facts)
        return facts

    model = copy_facts(
        facts, str(uuid.uuid5(uuid.NAMESPACE_URL, f"speed:{name}:domain")))
    claim_id = f"claim:{name}"
    activity_id = f"activity:{name}"
    model["claims"][claim_id] = record(
        "Claim", id=claim_id, subject_id=activity_id,
        text="The authored fixture evidences this behavior.",
        kind="behavior", evidence_ids=[evidence_id], trace_ids=[trace_id],
        semantic_review="supported",
    )
    model["activities"][activity_id] = record(
        "Activity", id=activity_id, name=f"{name.title()} behavior",
        description="Authored contract behavior example.", anchor_ids=[anchor_id],
        trace_ids=[trace_id], claim_ids=[claim_id], evidence_ids=[evidence_id],
        implementation_status="implemented", support="supported",
        review_state="proposed",
    )
    model["status"] = "complete"
    account_artifact_bytes(model)
    validate(model, "DomainArtifact")
    validate_references(model)
    return model


def main() -> None:
    for name in ("api", "sql", "ui", "dag"):
        for suffix, published in (("facts", False), ("domain", True)):
            destination = ROOT / f"{name}.{suffix}.json"
            destination.write_bytes(canonical(graph(name, published)) + b"\n")


if __name__ == "__main__":
    main()
