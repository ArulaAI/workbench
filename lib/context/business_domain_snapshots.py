"""Import explicitly supplied, versioned snapshots without remote retrieval.

A supplied document establishes captured contents, never deployment activation.
Format-specific interpretation remains the responsibility of source adapters.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .business_domain_schema import DomainError, digest, identifier, read_json, record, validate
from .repository_digest_schema import is_credential_path


def contained_file(root, path, limit):
    path = Path(path)
    if not path.resolve().is_relative_to(root) or path.is_symlink() or any(
            parent.is_symlink() for parent in path.parents) or is_credential_path(path):
        raise DomainError('UNSAFE_SNAPSHOT','Snapshot path fails containment or credential filtering')
    try:
        with path.open('rb') as stream:
            data = stream.read(limit+1)
    except OSError as exc:
        raise DomainError('SNAPSHOT_UNAVAILABLE','Supplied snapshot cannot be read') from exc
    if len(data)>limit:
        raise DomainError('SNAPSHOT_LIMIT','Supplied snapshot exceeds its byte limit')
    return data


def sanitized_identity(value):
    if not isinstance(value,str) or not value.strip():
        raise DomainError('INVALID_SNAPSHOT','Snapshot identity must be a nonempty string')
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        # Authentication, query parameters and fragments are not resource identity.
        host = parsed.hostname or ''
        if ':' in host:
            host = '['+host+']'
        return urlunsplit((parsed.scheme,host+(':'+str(parsed.port) if parsed.port else ''),parsed.path,'',''))
    return value


def capture_supplied(extractor):
    location = extractor.config.get('snapshot_manifest')
    if not location:
        return 'not_applicable',{}
    root = extractor.root
    manifest_path = root/location
    inputs = {}
    def diagnostic(code,message,subject_ids=None):
        extractor.diagnostics.append(record('Diagnostic',code=code,message=message,subject_ids=subject_ids or []))
    try:
        import json
        raw = contained_file(root,manifest_path,extractor.config['max_source_bytes'])
        inputs[manifest_path.relative_to(root).as_posix()] = digest(raw)
        manifest = json.loads(raw)
        if not isinstance(manifest,dict) or set(manifest)!={'schema_version','sources'} or manifest['schema_version']!=1 or not isinstance(manifest['sources'],list):
            raise DomainError('INVALID_SNAPSHOT_MANIFEST','Invalid supplied snapshot manifest')
    except (DomainError,ValueError,UnicodeError) as exc:
        diagnostic(getattr(exc,'code','INVALID_SNAPSHOT_MANIFEST'),'Supplied snapshot manifest could not be validated')
        return 'unknown',inputs
    freshness = 'snapshot_only'
    seen = set()
    required = {'id','resource_kind','resource_identity','local_path','content_sha256','provider_revision','retrieved_at','expires_at','scope','format'}
    for entry in manifest['sources']:
        try:
            if not isinstance(entry,dict) or set(entry)!=required or not isinstance(entry['id'],str) or not entry['id'] or entry['id'] in seen:
                raise DomainError('INVALID_SNAPSHOT','Invalid or duplicate supplied snapshot record')
            seen.add(entry['id'])
            if entry['resource_kind'] not in ('configuration','external_policy','workflow','execution') or not isinstance(entry['format'],str):
                raise DomainError('INVALID_SNAPSHOT','Invalid supplied snapshot kind or format')
            validate(entry['scope'],'Scope')
            path = manifest_path.parent/entry['local_path']
            raw = contained_file(root,path,extractor.config['max_source_bytes'])
            inputs[path.relative_to(root).as_posix()] = digest(raw)
            if digest(raw)!=entry['content_sha256']:
                raise DomainError('SNAPSHOT_HASH_MISMATCH','Supplied snapshot hash does not match its manifest')
            text = raw.decode('utf-8')
            from .business_domain_extract import redacted
            identity = redacted(sanitized_identity(entry['resource_identity']))
            sid = identifier('snapshot',entry['id'],entry['content_sha256'],entry['provider_revision'],entry['scope'])
            eid = identifier('ev',sid)
            excerpt = redacted(text)
            blob = record('SnapshotArtifact',snapshot_id=sid,source_hash=entry['content_sha256'],fragments=[{
                'id':identifier('fragment',eid),'original_locator':identity,'text':excerpt,'excerpt_hash':digest(excerpt.encode())}])
            blob_hash = digest(blob)
            snapshot = record('Snapshot',id=sid,resource_kind=entry['resource_kind'],resource_identity=identity,
                content_hash=entry['content_sha256'],local_blob_path=f'.speed/context/business-domain-snapshots/{blob_hash}.json',
                provider_revision=entry['provider_revision'],retrieved_at=entry['retrieved_at'],expires_at=entry['expires_at'],scope=entry['scope'])
            validate(snapshot,'Snapshot')
            if entry['expires_at'] and datetime.fromisoformat(entry['expires_at'].replace('Z','+00:00'))<=datetime.now(timezone.utc):
                freshness='stale'
                diagnostic('SNAPSHOT_EXPIRED','Supplied snapshot has expired',[sid])
            extractor.snapshot_objects[blob_hash]=blob
            extractor.facts['source_snapshots'][sid]=snapshot
            extractor.facts['evidence'][eid]=record('Evidence',id=eid,source_kind=entry['resource_kind'],
                locator={'kind':'snapshot_pointer','snapshot_id':sid,'pointer':'/fragments/0/text'},
                content_hash=digest(excerpt.encode()),excerpt=excerpt,claim_kind='source_observation',
                extractor='supplied-snapshot',extractor_version='1')
            rid=identifier('resource','supplied',entry['id'])
            extractor.facts['resources'][rid]=record('Resource',id=rid,
                kind=entry['resource_kind'] if entry['resource_kind']!='execution' else 'workflow',
                name=identity,version=entry['provider_revision'],evidence_ids=[eid],resolution='unresolved',
                reason='Snapshot contents are captured; activation and consumers have not been verified.')
            extractor.facts['coverage']['unsupported_source_ids'].append(rid)
            diagnostic('SNAPSHOT_REFERENCE_ONLY',
                'Captured supplied contents; this format has no verified semantic adapter or activation binding.',[rid])
        except (DomainError,ValueError,TypeError,KeyError,UnicodeError) as exc:
            if freshness!='stale':freshness='unknown'
            diagnostic(getattr(exc,'code','INVALID_SNAPSHOT'),'Supplied snapshot could not be validated')
    return freshness,inputs


def unchanged(root,inputs,limit):
    try:
        return all(digest(contained_file(root,root/path,limit))==value for path,value in inputs.items())
    except DomainError:
        return False
