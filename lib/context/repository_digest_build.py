"""Shared synchronous refresh owner for CLI and dashboard."""
from __future__ import annotations
import uuid
from pathlib import Path
from .business_domain_schema import DomainError, settings
from .business_domains import build_lock, discover
from .discovery_logging import DiscoveryRecorder
from .repository_digest import build_repository_digest, DigestInputError, load_repository_digest
from .utils import load_speed_toml


class BuildLease:
    """Core-owned lock reservation transferable to a background worker."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.context = build_lock(self.root)
        self.handle = self.context.__enter__()
    def __enter__(self):
        if self.handle is None:
            raise DomainError('INVALID_LEASE','Build reservation is already released')
        return self
    def __exit__(self,*args):
        self.close()
    def close(self):
        if self.handle is not None:
            self.context.__exit__(None,None,None)
            self.handle = None


def reserve_digest_build(project_root):
    return BuildLease(project_root)


def refresh_digest(project_root: str, *, rebuild_discovery=False, narrative=False,
                   config=None, provider=None, _lease=None, progress=None):
    root = Path(project_root).resolve()
    run_id = str(uuid.uuid4())
    result = {'ok':False,'outcome':'failed','build_id':None,'domain_build_id':None,
              'has_readable_digest':False,'warnings':[],'error':None,
              'run_id':run_id,'log_path':None}
    recorder = None
    refresh_boundary = None
    try:
        if not root.is_dir():
            raise DomainError('INVALID_ROOT','Repository root does not exist')
        recorder = DiscoveryRecorder(root,run_id,progress)
        result['log_path'] = recorder.relative_path
        recorder.progress('refresh',f'Discovery run {run_id[:8]} started')
        refresh_boundary = recorder.boundary('refresh',{
            'rebuild_discovery':rebuild_discovery,'narrative':narrative})
        recorder.progress('configuration','Loading and validating SPEED configuration')
        with recorder.boundary('configuration.load',{
                'source':'caller' if config is not None else '.speed/config.toml'}) as boundary:
            config = config if config is not None else load_speed_toml(str(root))
            validated_config = settings(config)
            boundary.success(config,schema='SpeedConfiguration')
        recorder.prune(validated_config['cache_retention_days'])
        if _lease is not None and _lease.root != root:
            raise DomainError('INVALID_LEASE','Build reservation belongs to another repository')
        recorder.progress('lock','Acquiring the repository discovery build lock')
        with _lease if _lease is not None else reserve_digest_build(root):
            if rebuild_discovery:
                recorder.progress('layer1','Rebuilding structural discovery')
                from .layer1 import build_layer1
                with recorder.boundary('layer1.build',{'fresh':True}) as boundary:
                    layer1 = build_layer1(str(root),fresh=True)
                    boundary.success(layer1,schema='Layer1BuildSummary')
            else:
                from .repository_digest import repository_digest_input_paths
                if not repository_digest_input_paths(str(root))['project_map'].is_file():
                    recorder.progress('project_map','Building project map')
                    from .project_map import build_project_map,save_project_map
                    with recorder.boundary('project_map.build',{}) as boundary:
                        project_map = build_project_map(str(root))
                        path = save_project_map(project_map,str(repository_digest_input_paths(str(root))['project_map'].parent))
                        boundary.success(project_map,schema='ProjectMap',
                            artifact=str(Path(path).resolve().relative_to(root)))
            with recorder.boundary('domain.discover',{
                    'configuration_loaded':True}) as boundary:
                model,status = discover(root,config,provider,lock_held=True,
                                        recorder=recorder,run_id=run_id)
                boundary.success({'model':model,'status':status},
                                 schema='DomainDiscoveryResult',
                                 metadata={'outcome':status['phase']})
            if status['error']:
                recorder.emit('domain.discover','error',error=status['error'])
            # Project the latest readable model and latest attempt even when
            # synthesis is unavailable. CLI exit status remains non-success.
            recorder.progress('digest','Building repository digest')
            with recorder.boundary('digest.build',{'narrative':narrative}) as boundary:
                digest = build_repository_digest(str(root),config=config,narrative=narrative)
                boundary.success(digest,schema='RepositoryDigest',
                    artifact='.speed/context/repository-digest.json')
            recorder.progress('digest','Repository digest validated and written')
            outcome = status['phase']
            coverage = status['coverage']
            warnings = list(digest.get('warnings',[]))
            warnings.append(f"Domain discovery: {coverage['anchors_processed']}/{coverage['anchors_total']} entrypoints processed; "
                            f"{coverage['anchors_pending']} pending, {coverage['anchors_excluded']} excluded.")
            units = status['limits']
            warnings.append(
                f"Semantic work: {units['semantic_units_validated']}/{units['semantic_units_total']} validated; "
                f"{units['semantic_units_cached']} cached, {units['semantic_units_active']} active, "
                f"{units['semantic_units_failed']} failed, {units['semantic_units_pending']} pending.")
            result.update(ok=outcome in ('complete','partial'),outcome=outcome,
                build_id=status['attempt_build_id'],domain_build_id=model['build_id'] if model else None,
                has_readable_digest=True,warnings=warnings,
                error=status['error'])
            refresh_boundary.success(result,schema='DigestRefreshResult')
    except (DomainError,DigestInputError) as exc:
        if refresh_boundary:
            refresh_boundary.__exit__(type(exc),exc,exc.__traceback__)
        result['error'] = exc.record() if isinstance(exc,DomainError) else {'code':'DIGEST_FAILED','message':str(exc)}
        result['outcome'] = 'busy' if getattr(exc,'code',None) == 'BUILD_BUSY' else 'failed'
        result['has_readable_digest'] = load_repository_digest(str(root)) is not None
    except KeyboardInterrupt:
        if refresh_boundary:
            refresh_boundary.__exit__(KeyboardInterrupt,KeyboardInterrupt(),None)
        result.update(outcome='cancelled',error={'code':'CANCELLED','message':'Refresh interrupted'})
    except Exception as exc:
        if refresh_boundary:
            refresh_boundary.__exit__(type(exc),exc,exc.__traceback__)
        raise
    finally:
        if recorder is not None:
            recorder.progress('refresh',
                              f"Digest refresh {result['outcome']}; log: {recorder.relative_path}",
                              level='success' if result['ok'] else 'error')
            recorder.finish(result['outcome'],result)
    return result
