"""Conservative cleanup of disposable discovery objects after publication."""
from pathlib import Path
import time

from .business_domain_schema import DomainError, read_json


def cleanup(root, config, timestamp=None):
    root = Path(root).resolve()
    directory = root/'.speed/context'
    cutoff = (time.time() if timestamp is None else timestamp)-config['cache_retention_days']*86400
    retained = set()
    def files(folder):
        if folder.is_symlink() or any(parent.is_symlink() for parent in folder.parents):
            raise DomainError('CLEANUP_UNSAFE','Cleanup directory is not contained safely')
        return sorted(folder.glob('*.json')) if folder.is_dir() else []
    def collect(value):
        if isinstance(value,dict):
            path = value.get('local_blob_path')
            if isinstance(path,str):
                target = root/path
                if not target.resolve().is_relative_to(directory):
                    raise DomainError('CLEANUP_UNSAFE','Snapshot reference is outside artifact storage')
                retained.add(target)
            for child in value.values():
                collect(child)
        elif isinstance(value,list):
            for child in value:
                collect(child)
    # A malformed retained artifact prevents cleanup; absence of a readable
    # reference is not evidence that its snapshot can be discarded.
    references = [directory/'business-domains.json',directory/'business-domain-facts.json',
                  directory/'business-domain-overrides.json']
    for name in ('business-domain-history','business-domain-baselines'):
        references.extend(files(directory/name))
    candidates = []
    for path in files(directory/'business-domain-cache'):
        if path.is_symlink():
            raise DomainError('CLEANUP_UNSAFE','Disposable object is a symbolic link')
        if path.stat().st_mtime < cutoff:
            candidates.append(path)
        else:
            references.append(path)
    for path in references:
        value = read_json(path,config['max_artifact_bytes'])
        if value:
            collect(value)
    for path in files(directory/'business-domain-snapshots'):
        if path.is_symlink():
            raise DomainError('CLEANUP_UNSAFE','Snapshot object is a symbolic link')
        if path not in retained and path.stat().st_mtime < cutoff:
            candidates.append(path)
    # Complete reference discovery before making any deletion.
    for path in candidates:
        path.unlink()
    return len(candidates)
