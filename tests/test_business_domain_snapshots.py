import json
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, digest, record, validate_evidence
from lib.context.business_domain_snapshots import unchanged


def setup(root,**changes):
    raw=b'{"refundWindowDays":30,"secret":"hidden-value"}'
    (root/'policy.export').write_bytes(raw)
    entry=dict(id='policy',resource_kind='external_policy',
        resource_identity='https://user:pass@policy.example/refunds?token=hidden#private',
        local_path='policy.export',content_sha256=digest(raw),provider_revision='rev-2',
        retrieved_at='2026-09-06T10:00:00Z',expires_at=None,scope=record('Scope'),format='unknown-format')
    entry.update(changes)
    (root/'snapshots.json').write_text(json.dumps({'schema_version':1,'sources':[entry]}))
    return Extractor(root,{**DEFAULTS,'snapshot_manifest':'snapshots.json'})


def test_supplied_snapshot_preserves_version_but_does_not_claim_activation(tmp_path):
    extractor=setup(tmp_path)
    facts,_=extractor.extract()
    snapshot=next(s for s in facts['source_snapshots'].values() if s['resource_kind']=='external_policy')
    assert snapshot['provider_revision']=='rev-2'
    assert snapshot['resource_identity']=='https://policy.example/refunds'
    assert snapshot['activation_evidence_id'] is None
    assert extractor.external_freshness=='snapshot_only'
    assert facts['coverage']['unsupported_source_ids']
    assert not facts['anchors']
    assert 'hidden-value' not in json.dumps(facts)
    validate_evidence(tmp_path,facts)
    assert unchanged(tmp_path,extractor.snapshot_inputs,DEFAULTS['max_source_bytes'])
    (tmp_path/'policy.export').write_text('changed')
    assert not unchanged(tmp_path,extractor.snapshot_inputs,DEFAULTS['max_source_bytes'])


def test_supplied_hash_mismatch_is_rejected(tmp_path):
    extractor=setup(tmp_path,content_sha256='0'*64)
    facts,_=extractor.extract()
    assert extractor.external_freshness=='unknown'
    assert any(d['code']=='SNAPSHOT_HASH_MISMATCH' for d in facts['warnings'])
    assert not any(s['resource_kind']=='external_policy' for s in facts['source_snapshots'].values())


def test_expired_snapshot_remains_inspectable_and_stale(tmp_path):
    extractor=setup(tmp_path,expires_at='2000-01-01T00:00:00Z')
    facts,_=extractor.extract()
    assert extractor.external_freshness=='stale'
    assert any(d['code']=='SNAPSHOT_EXPIRED' for d in facts['warnings'])


def test_symlink_snapshot_is_not_read(tmp_path):
    extractor=setup(tmp_path,local_path='linked.export')
    (tmp_path/'linked.export').symlink_to(tmp_path/'policy.export')
    facts,_=extractor.extract()
    assert any(d['code']=='UNSAFE_SNAPSHOT' for d in facts['warnings'])


def test_cleanup_preserves_all_retained_snapshot_references(tmp_path):
    import os
    from lib.context.business_domain_retention import cleanup
    from lib.context.business_domain_schema import atomic_write
    directory = tmp_path/'.speed/context'
    retained = ['business-domains.json','business-domain-facts.json','business-domain-overrides.json',
                'business-domain-history/previous.json','business-domain-baselines/base.json',
                'business-domain-cache/recent.json']
    snapshots = []
    for index,artifact in enumerate(retained):
        relative = f'.speed/context/business-domain-snapshots/retained-{index}.json'
        snapshot = tmp_path/relative
        atomic_write(snapshot,{'source':'retained'})
        os.utime(snapshot,(1,1))
        atomic_write(directory/artifact,{'nested':[{'local_blob_path':relative}]})
        snapshots.append(snapshot)
    orphan = directory/'business-domain-snapshots/orphan.json'
    expired = directory/'business-domain-cache/expired.json'
    for path in (orphan,expired):
        atomic_write(path,{'source':'unreferenced'})
        os.utime(path,(1,1))
    assert cleanup(tmp_path,DEFAULTS) == 2
    assert all(path.exists() for path in snapshots)
    assert all((directory/path).exists() for path in retained)
    assert not orphan.exists() and not expired.exists()
