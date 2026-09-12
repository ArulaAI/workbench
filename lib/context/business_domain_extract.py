"""Language-independent evidence inventory, normalization and bounded tracing.

All syntax and framework recognition lives behind the source adapter contract.
"""
from __future__ import annotations
import os
import re
import subprocess
import uuid
from pathlib import Path
from .business_domain_adapters import (CATALOG, adapter_for, descriptor,
    enricher_descriptors, enrichers_for)
from .business_domain_adapters.base import (
    MAX_SEMANTIC_CANDIDATES, TRACE_ROLES, SemanticResult, Source, Unit,
    normalize_operation_observation,
)
from .business_domain_identity import reconcile_anchors
from .language_registry import SOURCE_ADAPTER_CAPABILITIES
from .business_domain_schema import (DEFAULTS, DomainError, account_artifact_bytes,
    atomic_write, digest, identifier, implementation_hash, limits, now, record,
    validate, read_json)
from .repository_digest_schema import is_credential_path

IGNORED = set(CATALOG['ignored_directories'])
def source_paths(root: Path) -> list[str]:
    try:
        result = subprocess.run(['git', '-C', str(root), 'ls-files', '-co', '--exclude-standard', '-z'], capture_output=True, timeout=30, check=True)
        paths = result.stdout.decode().split('\0')
    except (subprocess.SubprocessError, UnicodeError):
        paths = []
        for directory, folders, files in os.walk(root, followlinks=False):
            folders[:] = [name for name in folders if name not in IGNORED and not (Path(directory)/name).is_symlink()]
            paths.extend((Path(directory)/name).relative_to(root).as_posix() for name in files)
    return sorted({p for p in paths if p and not any(part in IGNORED for part in Path(p).parts)
                   and descriptor(p) is not None and not is_credential_path(Path(p))})

def inventory(root: Path, config: dict) -> tuple[list[Source], list[dict]]:
    sources, diagnostics = [], []
    relatives = source_paths(root)
    markers = set(CATALOG.get('service_scope_markers', []))
    scope_directories = {Path(relative).parent.as_posix()
        for relative in relatives if Path(relative).name in markers}
    for relative in relatives:
        path = root / relative
        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
            diagnostics.append(record('Diagnostic', code='UNSAFE_SOURCE', message='Excluded source outside repository containment', subject_ids=[], evidence_ids=[]))
            continue
        try:
            with path.open('rb') as stream:
                raw = stream.read(config['max_source_bytes'] + 1)
        except OSError:
            diagnostics.append(record('Diagnostic', code='SOURCE_UNAVAILABLE', message=f'Cannot read source: {relative}', subject_ids=[], evidence_ids=[]))
            continue
        if len(raw) > config['max_source_bytes']:
            diagnostics.append(record('Diagnostic', code='SOURCE_LIMIT', message=f'Excluded oversized source: {relative}', subject_ids=[], evidence_ids=[]))
            continue
        try:
            text = raw.decode('utf-8')
        except UnicodeError:
            diagnostics.append(record('Diagnostic', code='SOURCE_ENCODING', message=f'Unsupported source encoding: {relative}', subject_ids=[], evidence_ids=[]))
            continue
        source = Source(relative, descriptor(relative)['language'], text, digest(raw),
            identifier('resource', relative))
        parents = [parent.as_posix() for parent in Path(relative).parents]
        service_scope = max(
            (scope for scope in scope_directories if scope in parents),
            key=lambda scope: len(Path(scope).parts), default=None)
        source.service_scope = ('repository' if service_scope in (None, '.')
            else service_scope)
        sources.append(source)
    return sources, diagnostics

def redacted(text: str) -> str:
    # Keep line count and keys; do not send literal credentials in evidence.
    return re.sub(r'(?im)((?:password|secret|api[_-]?key|access[_-]?token)[\"\']?\s*[=:]\s*[\"\']?)[^\s\"\',;]+', r'\1[REDACTED]', text)


def redact_values(value):
    """Apply the same credential filter to normalized expressions as excerpts."""
    if isinstance(value,str):
        return redacted(value)
    if isinstance(value,list):
        return [redact_values(item) for item in value]
    if isinstance(value,dict):
        return {key:redact_values(item) for key,item in value.items()}
    return value

class Extractor:
    def __init__(self, root: Path, config: dict, build_id: str | None = None):
        self.root=root.resolve();self.config=config
        self.sources,self.diagnostics=inventory(self.root,config)
        self.facts=record('FactsArtifact',generated_at=now(),build_id=build_id or str(uuid.uuid4()),limits=limits(config))
        self.facts['warnings']=self.diagnostics
        self.units: list[Unit]=[]
        self.anchor_units: dict[int, tuple[str, str]] = {}
        self.snapshot_objects: dict[str,dict]={}
        self.external_freshness = 'not_applicable'
        self.snapshot_inputs = {}
        previous = read_json(self.root/'.speed/context/business-domain-facts.json')
        self.previous_snapshots = previous.get('source_snapshots', {}) if previous else {}

    def evidence(self, source: Source, start: int, end: int) -> str:
        excerpt=redacted(source.text[start:end]);sid=identifier('snapshot',source.path,source.source_hash,start,end)
        eid=identifier('ev',source.path,source.source_hash,start,end)
        if eid in self.facts['evidence']:return eid
        snapshot=record('SnapshotArtifact',snapshot_id=sid,source_hash=source.source_hash,fragments=[{
            'id':identifier('fragment',eid),'original_locator':source.path,'text':excerpt,'excerpt_hash':digest(excerpt.encode())}])
        blob=digest(snapshot)
        self.snapshot_objects[blob]=snapshot
        path=f'.speed/context/business-domain-snapshots/{blob}.json'
        previous = self.previous_snapshots.get(sid)
        captured_at = previous['retrieved_at'] if previous and previous['content_hash'] == source.source_hash else now()
        self.facts['source_snapshots'][sid]=record('Snapshot',id=sid,resource_kind=source.language,resource_identity=source.path,content_hash=source.source_hash,local_blob_path=path,retrieved_at=captured_at)
        kind='test' if re.search(CATALOG['test_path_pattern'],source.path) else descriptor(source.path)['source_kind']
        self.facts['evidence'][eid]=record('Evidence',id=eid,source_kind=kind,locator={'kind':'repository_span','path':source.path,'start_line':source.text.count('\n',0,start)+1,'end_line':source.text.count('\n',0,max(start,end-1))+1,'source_hash':source.source_hash,'snapshot_id':sid,'pointer':'/fragments/0/text'},content_hash=digest(excerpt.encode()),excerpt=excerpt,claim_kind='source_observation',extractor=source.adapter_id,extractor_version=source.adapter_version)
        return eid

    def add_unit(self, unit: Unit) -> None:
        unit.symbol_id=identifier('symbol',unit.qualified)
        unit.evidence_id=self.evidence(unit.source,unit.start,unit.end)
        self.facts['symbols'][unit.symbol_id]=record('Symbol',id=unit.symbol_id,qualified_name=unit.qualified,signature=unit.name+'('+','.join(t for _,t in unit.params)+')',kind=unit.kind,file=unit.source.path,evidence_ids=[unit.evidence_id])
        if self.facts['evidence'][unit.evidence_id]['source_kind']=='test':unit.anchor_kind=None
        trace_contract = (
            getattr(unit, 'trace_role', None),
            getattr(unit, 'required_relationships', None),
            getattr(unit, 'required_capabilities', None),
            getattr(unit, 'valid_terminal', None),
        )
        if unit.kind in {'function', 'method', 'declarative_operation'}:
            if any(value is None for value in trace_contract):
                raise DomainError('INVALID_ADAPTER_CONTRACT',
                    'Callable producer must declare its trace role, relationship and capability obligations, and terminal status')
            if unit.trace_role not in TRACE_ROLES \
                    or set(unit.required_relationships) - {'implementation_selection'} \
                    or set(unit.required_capabilities) - SOURCE_ADAPTER_CAPABILITIES \
                    or type(unit.valid_terminal) is not bool \
                    or (unit.valid_terminal and (
                        unit.trace_role != 'implementation' or not unit.executable_body)) \
                    or (unit.trace_role not in {'implementation', 'external_boundary'}
                        and 'implementation_selection' not in unit.required_relationships):
                raise DomainError('INVALID_ADAPTER_CONTRACT',
                    'Callable producer supplied an inconsistent normalized trace contract')
        if unit.anchor_kind:
            unit.anchor_id=identifier('anchor',unit.qualified,unit.anchor_kind)
            anchor_evidence = {unit.evidence_id}
            anchor_evidence.update(self.evidence(source, start, end)
                for source, start, end in unit.anchor_evidence_spans)
            service_id = identifier('resource', 'service', unit.source.service_scope)
            self.facts['resources'].setdefault(service_id, record('Resource',
                id=service_id, kind='service', name=unit.source.service_scope,
                language=None, evidence_ids=[], resolution='resolved', reason=None))
            operation=record('Operation',protocol=unit.anchor_kind,name=unit.name,
                method=unit.method,path=unit.route,service_resource_id=service_id)
            role = getattr(unit, 'anchor_role', None) or (
                'contract' if unit.trace_role in {'contract', 'interface', 'declaration'}
                else 'implementation')
            if role in {'registration', 'exposure'} and unit.anchor_registration is None:
                raise DomainError('INVALID_ADAPTER_CONTRACT',
                    'Entry-point registration representation requires normalized registration metadata')
            identity_key = getattr(unit, 'anchor_identity_key', None)
            eligibility = getattr(unit, 'anchor_eligibility', None) or (
                'eligible' if unit.anchor_resolution == 'resolved' and identity_key
                and role in {'registration', 'exposure', 'contract'} else 'supporting'
                if role == 'implementation' else 'unresolved')
            representation_id = identifier('anchor_representation', unit.qualified, role)
            registration = None
            if unit.anchor_registration is not None:
                spans = unit.anchor_registration_evidence_spans or [
                    (unit.source, unit.start, unit.end)]
                registration = record('EntryPointRegistration',
                    **unit.anchor_registration,
                    evidence_ids=sorted({self.evidence(source, start, end)
                        for source, start, end in spans}))
                anchor_evidence.update(registration['evidence_ids'])
            representation = record('AnchorRepresentation', id=representation_id,
                role=role, identity_key=identity_key, source_id=unit.source.resource_id,
                symbol_id=unit.symbol_id, operation=operation, eligibility=eligibility,
                visibility=getattr(unit, 'anchor_visibility', None) or
                    ('external' if eligibility == 'eligible' else 'internal'),
                registration=registration, evidence_ids=sorted(anchor_evidence), resolution=unit.anchor_resolution,
                reason=unit.anchor_reason)
            self.facts['anchors'][unit.anchor_id]=record('Anchor',id=unit.anchor_id,
                kind=unit.anchor_kind,source_id=unit.source.resource_id,
                symbol_id=unit.symbol_id,operation=operation,status='candidate',
                evidence_ids=sorted(anchor_evidence),resolution=unit.anchor_resolution,
                reason=unit.anchor_reason,representations=[representation])
            if unit.anchor_kind in {'http', 'rpc', 'graphql'}:
                endpoint_edge = identifier('edge', unit.symbol_id,
                                           'exposes_endpoint', unit.anchor_id)
                self.facts['edges'][endpoint_edge] = record(
                    'Edge', id=endpoint_edge,
                    from_ref={'kind':'symbol', 'id':unit.symbol_id},
                    to_ref={'kind':'anchor', 'id':unit.anchor_id},
                    kind='exposes_endpoint', evidence_ids=sorted(anchor_evidence),
                    resolution='resolved', reason=None)
                self.facts['coverage']['edges_resolved'] += 1
            self.anchor_units[id(unit)] = (unit.anchor_id, representation_id)
        for binding in adapter_for(unit.source).bindings(unit):
            binding = redact_values(binding)
            position = binding.pop('position', None)
            end = binding.pop('end', None)
            if (position is None) != (end is None) or (position is not None and (
                    type(position) is not int or type(end) is not int
                    or not 0 <= position < end <= len(unit.text))):
                raise ValueError('Adapter binding requires a valid unit-relative span')
            evidence_id = (unit.evidence_id if position is None else
                self.evidence(unit.source, unit.start+position, unit.start+end))
            bid=identifier('binding',unit.symbol_id,binding['name'],binding['direction'])
            self.facts['bindings'][bid]=record('Binding',id=bid,
                source={'kind':'symbol','id':unit.symbol_id},target={'kind':'symbol','id':unit.symbol_id},
                evidence_ids=[evidence_id],**binding)

    def extract(self) -> tuple[dict,list[Unit]]:
        selected_adapters = {}
        for source in self.sources:
            self.facts['resources'][source.resource_id]=record('Resource',id=source.resource_id,kind='repository_file',name=source.path,language=source.language)
            adapter = None
            try:
                entry = descriptor(source) or {}
                selected = entry.get('capability') or {}
                adapter_id = selected.get('id') or entry.get('adapter') or 'business-domain-static'
                parser_id = selected.get('parser')
                source.adapter_id = f'{adapter_id}/{parser_id}' if parser_id else adapter_id
                source.adapter_version = selected.get('parser_version') or selected.get('version') or '1'
                source.declared_capabilities = dict(selected.get('capabilities', {}))
                source.parser_required = bool(parser_id)
                adapter = adapter_for(source)
                units = adapter.extract(source) if adapter else []
                if adapter is None:
                    code = ('ADAPTER_REGISTRY_INVALID' if entry.get('registry_error') else
                            'AMBIGUOUS_ADAPTER' if len(entry.get('candidates', [])) > 1 else
                            'SOURCE_CAPABILITY_UNAVAILABLE')
                    self.diagnostics.append(record('Diagnostic', code=code,
                        message='No unique installed parser capability matches this source.', subject_ids=[source.resource_id]))
                    for diagnostic_code in (entry.get('capability') or {}).get('diagnostic_codes', []):
                        if diagnostic_code != code:
                            self.diagnostics.append(record('Diagnostic', code=diagnostic_code,
                                message='Selected source capability is unavailable for this input.',
                                subject_ids=[source.resource_id]))
            except (ImportError,ValueError,TypeError,RuntimeError,subprocess.SubprocessError) as exc:
                source.adapter_failed = True
                adapter = None
                self.diagnostics.append(record('Diagnostic',code='ADAPTER_UNAVAILABLE',message=f'{source.language}: {type(exc).__name__}',subject_ids=[source.resource_id],evidence_ids=[]));units=[]
            self.units.extend(units)
            if adapter:
                selected_adapters.setdefault(id(adapter), (adapter, []))[1].append(source)
        # Resolve cross-file semantics through installed provider hooks. Core
        # orchestration does not inspect language or framework identities.
        for adapter, sources in sorted(selected_adapters.values(),
                key=lambda item: (getattr(item[0], 'PREPARE_PHASE', 100),
                                  getattr(item[0], '__name__', type(item[0]).__name__))):
            prepare = getattr(adapter, 'prepare', None)
            if prepare:
                prepare(sources, self.units, self.diagnostics)
            diagnostics = getattr(adapter, 'diagnostics', None)
            if diagnostics:
                for source in sources:
                    for diagnostic in diagnostics(source):
                        if not isinstance(diagnostic, dict):
                            raise ValueError('Adapter diagnostic must be a normalized record')
                        span = diagnostic.get('span')
                        reason = diagnostic.get('reason')
                        code = diagnostic.get('code')
                        if (not isinstance(span, (tuple, list)) or len(span) != 2
                                or any(type(value) is not int for value in span)
                                or not 0 <= span[0] <= span[1] <= len(source.text)
                                or not isinstance(code, str) or not code
                                or not isinstance(reason, str) or not reason):
                            raise ValueError('Adapter diagnostic requires code, reason, and a valid source span')
                        evidence_id = self.evidence(source, span[0], span[1])
                        self.diagnostics.append(record('Diagnostic', code=code, message=reason,
                            subject_ids=[source.resource_id], evidence_ids=[evidence_id]))
        selected_enrichers = {}
        for source in self.sources:
            if source.adapter_failed:
                continue
            adapter = adapter_for(source)
            evidence = getattr(adapter, 'activation_evidence', lambda _: {})(source) if adapter else {}
            for enricher in enrichers_for(source, evidence):
                selected_enrichers.setdefault(id(enricher), (enricher, []))[1].append(source)
        for enricher, sources in selected_enrichers.values():
            prepare = getattr(enricher, 'prepare', None)
            if prepare:
                prepare(sources, self.units, self.diagnostics)
        for unit in self.units:
            self.add_unit(unit)
        self._connections()
        self._anchor_correspondences()
        self._observations()
        self._canonicalize_anchors()
        self._documentation_edges()
        self._capabilities()
        self._traces()
        from .business_domain_snapshots import capture_supplied
        self.external_freshness,self.snapshot_inputs = capture_supplied(self)
        self.facts['coverage']['anchors_total']=len(self.facts['anchors'])
        self.facts['coverage']['anchors_pending']=len(self.facts['anchors'])
        self.facts['coverage']['evidence_valid']=len(self.facts['evidence'])
        self.facts['limits']['source_bytes']=sum(len(s.text.encode()) for s in self.sources)
        self.facts['limits']['semantic_units_total']=len(self.facts['traces'])
        self.facts['limits']['semantic_units_pending']=len(self.facts['traces'])
        installed = Path(__file__).parent
        fp = dict(sources=digest({s.path:s.source_hash for s in self.sources}),
            configuration=digest(self.config),
            extractors=implementation_hash(Path(__file__),installed/'business_domain_adapters',
                installed/'rules',installed/'data',installed/'language_registry.py',
                installed/'treesitter_extract.py',installed/'business_domain_schema.py',
                installed/'business_domain_snapshots.py',
                installed/'business_domain_identity.py',installed/'business_domain_policies.json',
                installed/'business_domain_reference_targets.json',
                installed/'business_domain_artifacts.schema.json'),
            prompts=digest({}),provider=digest({}),overrides=digest({}),
            snapshots=digest({'records':self.facts['source_snapshots'],'inputs':self.snapshot_inputs}))
        fp['value']=digest(fp);self.facts['fingerprint']=fp
        for blob,snapshot in self.snapshot_objects.items():atomic_write(self.root/'.speed/context/business-domain-snapshots'/f'{blob}.json',snapshot)
        account_artifact_bytes(self.facts)
        validate(self.facts,'FactsArtifact')
        return self.facts,self.units

    def _anchor_correspondences(self) -> None:
        """Materialize adapter-provided identity evidence without source rules."""
        entries = []
        for unit in self.units:
            owned = self.anchor_units.get(id(unit))
            if not owned or owned[0] not in self.facts['anchors']:
                continue
            anchor = self.facts['anchors'][owned[0]]
            entries.append((unit, anchor, anchor['representations'][0]))
        by_unit = {id(unit): (anchor, representation)
            for unit, anchor, representation in entries}
        assigned = set()
        resolved_pairs = set()
        ambiguous_groups = set()

        def relationship_edges(representations):
            symbols = {item['symbol_id'] for item in representations if item['symbol_id']}
            return sorted(edge['id'] for edge in self.facts['edges'].values()
                if edge['from_ref']['id'] in symbols and (
                    edge['to_ref'] and edge['to_ref']['kind'] == 'symbol'
                    and edge['to_ref']['id'] in symbols
                    or set(edge.get('candidate_target_ids', [])) & symbols))

        def add(source, targets, state, reason):
            source_anchor, source_representation = source
            target_representations = sorted(
                {target[1]['id']: target[1] for target in targets}.values(),
                key=lambda item: item['id'])[:MAX_SEMANTIC_CANDIDATES]
            if not target_representations:
                target_representations = [source_representation]
            all_representations = [source_representation, *target_representations]
            edge_ids = relationship_edges(all_representations)
            evidence_ids = sorted({evidence_id for item in all_representations
                for evidence_id in item['evidence_ids']} | {
                evidence_id for edge_id in edge_ids
                for evidence_id in self.facts['edges'][edge_id]['evidence_ids']})
            correspondence_id = identifier('anchor_correspondence',
                source_representation['id'], sorted(item['id'] for item in target_representations), state)
            source_anchor['correspondences'].append(record('AnchorCorrespondence',
                id=correspondence_id,
                from_representation=source_representation['id'],
                to_representations=sorted({item['id'] for item in target_representations}),
                relationship_edges=edge_ids, state=state,
                evidence_ids=evidence_ids, reason=reason))
            assigned.update(item['id'] for item in all_representations)
            target_ids = frozenset(item['id'] for item in target_representations)
            if state == 'resolved':
                resolved_pairs.update(frozenset((source_representation['id'], target_id))
                    for target_id in target_ids)
            elif state == 'ambiguous':
                ambiguous_groups.add(frozenset({source_representation['id'], *target_ids}))

        def contextual_target(source, unit):
            """Retain a supporting implementation without promoting its body."""
            source_anchor, source_representation = source
            representation_id = identifier('anchor_representation',
                source_representation['id'], unit.qualified, 'implementation')
            existing = next((item for item in source_anchor['representations']
                if item['id'] == representation_id), None)
            if existing:
                return source_anchor, existing
            service_id = identifier('resource', 'service', unit.source.service_scope)
            self.facts['resources'].setdefault(service_id, record('Resource',
                id=service_id, kind='service', name=unit.source.service_scope,
                language=None, evidence_ids=[], resolution='resolved', reason=None))
            operation = record('Operation', protocol=source_anchor['kind'],
                name=unit.name, service_resource_id=service_id)
            representation = record('AnchorRepresentation', id=representation_id,
                role='implementation', identity_key=source_representation['identity_key'],
                source_id=unit.source.resource_id, symbol_id=unit.symbol_id,
                operation=operation, registration=None, eligibility='supporting',
                visibility='internal', evidence_ids=[unit.evidence_id],
                resolution='resolved', reason=None)
            source_anchor['representations'].append(representation)
            return source_anchor, representation

        # Exact semantic links (for example, SQL contract/body selection) take
        # precedence over protocol-key and unresolved-candidate grouping.
        for unit, _, representation in entries:
            declared_targets = getattr(unit, 'anchor_correspondence_units', [])
            targets = [(by_unit[id(target)] if id(target) in by_unit else
                        contextual_target(by_unit[id(unit)], target))
                       for target in declared_targets]
            if not declared_targets:
                continue
            state = getattr(unit, 'anchor_correspondence_state', None) or (
                'resolved' if len(targets) == 1 else 'ambiguous')
            add(by_unit[id(unit)], targets, state,
                getattr(unit, 'anchor_correspondence_reason', None) or
                ('Adapter resolved these source representations.' if state == 'resolved'
                 else 'Several adapter-supported source representations remain viable.'))

        exact = {}
        for unit, anchor, representation in entries:
            if representation['identity_key']:
                exact.setdefault(representation['identity_key'], []).append(
                    (unit, anchor, representation))
        for group in exact.values():
            if len(group) < 2:
                continue
            implementations = [item for item in group
                if item[2]['role'] == 'implementation']
            registrations = [item for item in group
                if item[2]['role'] == 'registration']
            state = ('ambiguous' if len(implementations) > 1
                     or len(registrations) > 1 else 'resolved')
            source = next((item for item in group
                if item[2]['role'] in {'registration', 'exposure', 'contract'}), group[0])
            targets = [by_unit[id(item[0])] for item in group if item is not source]
            if state == 'resolved':
                for target in targets:
                    pair = frozenset((source[2]['id'], target[1]['id']))
                    if pair not in resolved_pairs:
                        add(by_unit[id(source[0])], [target], state,
                            'Exact adapter-established operation identity links these representations.')
            else:
                group_ids = frozenset(item[2]['id'] for item in group)
                if group_ids not in ambiguous_groups:
                    add(by_unit[id(source[0])], targets, state,
                        'Exact operation identity has multiple viable implementations or registrations.')

        candidates = {}
        for unit, anchor, representation in entries:
            key = getattr(unit, 'anchor_candidate_key', None) or (
                unit.source.service_scope, unit.anchor_kind, unit.name.casefold())
            if representation['id'] not in assigned and key:
                candidates.setdefault(key, []).append((unit, anchor, representation))
        for group in candidates.values():
            contracts = [item for item in group if item[2]['role'] == 'contract']
            implementations = [item for item in group if item[2]['role'] == 'implementation']
            if not contracts or not implementations:
                continue
            for source in contracts:
                targets = [by_unit[id(item[0])] for item in implementations]
                add(by_unit[id(source[0])], targets,
                    'ambiguous' if len(targets) > 1 else 'unresolved',
                    'A possible contract/implementation correspondence lacks exact relationship evidence.')

        for unit, anchor, representation in entries:
            if representation['id'] in assigned:
                continue
            resolved = (representation['eligibility'] == 'eligible'
                and representation['role'] in {'registration', 'exposure'})
            add(by_unit[id(unit)], [], 'resolved' if resolved else 'unresolved',
                'The registration directly establishes this canonical entry point.'
                if resolved else 'No exact implementation correspondence is available.')

    def _capabilities(self) -> None:
        """Materialize selected source capabilities before semantic tracing."""
        capabilities = {}
        for source in self.sources:
            source.capability_statuses = {}
            entry = descriptor(source)
            selected = entry.get('capability') or {}
            fallback_codes = ['ADAPTER_REGISTRY_INVALID'] if entry.get('registry_error') else ['SOURCE_CAPABILITY_UNAVAILABLE']
            unavailable = {feature:'unsupported' for feature in SOURCE_ADAPTER_CAPABILITIES}
            if source.adapter_failed:
                selected = {**selected, 'capabilities': unavailable,
                    'diagnostic_codes': sorted(set(selected.get('diagnostic_codes', [])) | {'ADAPTER_UNAVAILABLE'})}
            providers = [selected]
            adapter = None if source.adapter_failed else adapter_for(source)
            if adapter:
                evidence = getattr(adapter, 'activation_evidence', lambda _: {})(source)
                providers.extend(enricher_descriptors(source, evidence))
            for provider in providers:
                for feature, status in provider.get('capabilities', unavailable).items():
                    source.capability_statuses.setdefault(feature, set()).add(status)
                    capability = record('Capability', language=source.language,
                        framework=provider.get('framework'), version=provider.get('framework_version'),
                        adapter=provider.get('id', 'unavailable'), adapter_version=provider.get('version', '1'),
                        feature=feature, status=status,
                        diagnostic_codes=provider.get('diagnostic_codes', fallback_codes))
                    capabilities[digest(capability)] = capability
        self.facts['capabilities'] = [capabilities[k] for k in sorted(capabilities)]

    def _documentation_edges(self) -> None:
        """Link authored documentation to exact operations or its service scope."""
        service_by_scope = {resource['name']: resource['id']
            for resource in self.facts['resources'].values()
            if resource['kind'] == 'service'}
        for source in self.sources:
            if source.language != 'markdown' or not source.text.strip():
                continue
            targets = set()
            lowered = source.text.casefold()
            for anchor in self.facts['anchors'].values():
                operation = anchor.get('operation') or {}
                tokens = [operation.get('path'), operation.get('name')]
                if any(token and len(token) > 2 and token.casefold() in lowered
                       for token in tokens):
                    targets.add(('anchor', anchor['id']))
            service_id = service_by_scope.get(source.service_scope)
            if not targets and service_id:
                targets.add(('resource', service_id))
            if not targets:
                continue
            evidence_id = self.evidence(source, 0, len(source.text))
            for kind, target_id in sorted(targets):
                edge_id = identifier('edge', source.resource_id,
                                     'documents_behavior', target_id)
                self.facts['edges'][edge_id] = record(
                    'Edge', id=edge_id,
                    from_ref={'kind':'resource', 'id':source.resource_id},
                    to_ref={'kind':kind, 'id':target_id},
                    kind='documents_behavior', evidence_ids=[evidence_id],
                    resolution='resolved', reason=None)
                self.facts['coverage']['edges_resolved'] += 1

    def _canonicalize_anchors(self) -> None:
        """Reconcile adapter-established identities before traces are scheduled."""
        replacements = reconcile_anchors(self.facts)
        # Reconciliation rebuilds containers while rewriting identifiers. Keep
        # subsequent adapter/snapshot diagnostics attached to the artifact.
        self.diagnostics = self.facts['warnings']
        for unit in self.units:
            if unit.anchor_id:
                unit.anchor_id = replacements.get(unit.anchor_id, unit.anchor_id)

    def _traces(self) -> None:
        """Evaluate mechanical traversal and semantic completion independently."""
        outgoing: dict[str, list[dict]] = {}
        for edge in self.facts['edges'].values():
            outgoing.setdefault(edge['from_ref']['id'], []).append(edge)
        units_by_symbol = {unit.symbol_id: unit for unit in self.units}
        for anchor in self.facts['anchors'].values():
            tid = identifier('trace', anchor['id'])
            obligations = []
            def require(kind, symbol, status, code, reason, edge=None, targets=(), identity=None):
                oid = identifier('trace_obligation', tid, kind, symbol, edge, code, identity)
                evidence_ids = (self.facts['edges'][edge] if edge else self.facts['symbols'][symbol])['evidence_ids']
                self.facts['trace_obligations'][oid] = record('TraceObligation', id=oid,
                    trace_id=tid, kind=kind, origin_ref={'kind':'symbol','id':symbol},
                    edge_id=edge, candidate_target_ids=sorted(targets), status=status,
                    reason_code=code, reason=reason, evidence_ids=evidence_ids)
                obligations.append(oid)
            start = units_by_symbol[anchor['symbol_id']]
            role = start.trace_role
            required_relationships = tuple(start.required_relationships)
            queue = [(anchor['symbol_id'], 0)]
            seen, edges, frontier, reasons = set(), set(), set(), set()
            if anchor['resolution'] != 'resolved':
                frontier.add(anchor['symbol_id']); reasons.add('unresolved_anchor')
                require('capability', anchor['symbol_id'], anchor['resolution'], 'UNRESOLVED_ANCHOR',
                        anchor['reason'] or 'Entry-point identity is not resolved.')

            def require_capabilities(unit, demonstrated=frozenset()):
                for capability in unit.required_capabilities or ():
                    statuses = unit.source.capability_statuses.get(capability, set())
                    # A capability this run exercised for this symbol is present,
                    # whatever the adapter owning the declaring file declares. An
                    # endpoint is anchored where it is declared, so a contract in
                    # openapi.yml would otherwise be judged by the YAML reader for
                    # work the Java enricher did.
                    available = (bool(statuses & {'supported', 'partial'})
                                 or capability in demonstrated)
                    require('capability', unit.symbol_id, 'satisfied' if available else 'unresolved',
                            'CAPABILITY_AVAILABLE' if available else 'CAPABILITY_UNAVAILABLE',
                            (f'The selected adapter provides {capability} for this evidenced source.' if available
                             else f'No selected adapter provides required capability {capability} for this source.'),
                            identity=capability)
                    if not available:
                        frontier.add(unit.symbol_id); reasons.add('capability_gap')

            # Implementation selection is a normalized obligation.  An
            # implementation may satisfy it itself only when its adapter has
            # positively identified a valid executable terminal.  Contracts
            # select through normalized relationships, including the reverse
            # direction of implementation-to-contract declarations.
            selection_status = None
            selection_targets: list[str] = []
            selection_reason = ''
            selection_edges: list[dict] = []
            selected_target = None
            if role == 'implementation' and start.valid_terminal and start.executable_body:
                selection_status = 'satisfied'
                selection_targets = [start.symbol_id]
                selection_reason = 'The adapter identified the anchor symbol as a concrete executable terminal.'
            elif 'implementation_selection' in required_relationships:
                for edge in self.facts['edges'].values():
                    if edge['kind'] == 'selects_implementation' and edge['from_ref']['id'] == start.symbol_id:
                        selection_edges.append(edge)
                        if edge['to_ref'] and edge['to_ref']['kind'] == 'symbol':
                            selection_targets.append(edge['to_ref']['id'])
                        selection_targets.extend(edge['candidate_target_ids'])
                    elif edge['kind'] == 'implements' and (
                            (edge['to_ref'] and edge['to_ref']['id'] == start.symbol_id)
                            or start.symbol_id in edge['candidate_target_ids']):
                        selection_edges.append(edge)
                        selection_targets.append(edge['from_ref']['id'])
                selection_targets = sorted(set(selection_targets))[:MAX_SEMANTIC_CANDIDATES]
                exact = [target for target in selection_targets
                         if target in units_by_symbol
                         and units_by_symbol[target].trace_role == 'implementation'
                         and units_by_symbol[target].valid_terminal
                         and units_by_symbol[target].executable_body]
                traversable = [target for target in selection_targets
                         if target in units_by_symbol
                         and units_by_symbol[target].trace_role == 'implementation'
                         and units_by_symbol[target].executable_body]
                uncertain = any(edge['resolution'] != 'resolved' for edge in selection_edges)
                if len(exact) == 1 and len(selection_targets) == 1 and not uncertain:
                    selection_status = 'satisfied'
                    selected_target = exact[0]
                    selection_reason = 'One evidenced implementation relationship selects a concrete executable terminal.'
                    queue.append((selected_target, 1))
                elif len(traversable) == 1 and len(selection_targets) == 1 and not uncertain:
                    selection_status = 'unresolved'
                    selected_target = traversable[0]
                    selection_reason = ('One evidenced implementation is available for partial traversal, '
                        'but its adapter did not establish a valid executable terminal.')
                    queue.append((selected_target, 1))
                elif len(selection_targets) > 1 or uncertain:
                    selection_status = 'ambiguous'
                    selection_reason = 'Multiple or ambiguous implementation relationships remain viable.'
                else:
                    selection_status = 'unresolved'
                    selection_reason = 'No evidenced relationship selects a concrete executable implementation.'
                edges.update(edge['id'] for edge in selection_edges)
            else:
                selection_status = 'external' if role == 'external_boundary' else 'unresolved'
                selection_reason = ('The entry point terminates at an explicit external implementation boundary.'
                    if role == 'external_boundary' else
                    'The adapter did not authorize this declaration as an executable implementation terminal.')

            # Capability obligations are answered after the relationships they
            # govern have been attempted, so an exercised capability can settle
            # its own question.
            require_capabilities(start, demonstrated=(
                frozenset({'relationship_resolution'})
                if selection_status == 'satisfied' else frozenset()))

            while queue:
                symbol, depth = queue.pop(0)
                if symbol in seen:
                    continue
                if len(seen) >= self.config['max_symbols_per_activity']:
                    require('symbol_limit', anchor['symbol_id'], 'limit_reached', 'SYMBOL_LIMIT',
                            'Symbol budget prevents completing this path.', targets=[symbol])
                    frontier.add(symbol); reasons.add('symbol_limit'); continue
                seen.add(symbol)
                for edge in outgoing.get(symbol, []):
                    if edge['kind'] in {'implements', 'inherits', 'has_field',
                            'accepts_type', 'returns_type', 'tests_behavior',
                            'documents_behavior', 'exposes_endpoint'} or (
                            edge['kind'] == 'selects_implementation'
                            and symbol == start.symbol_id
                            and 'implementation_selection' in required_relationships):
                        continue
                    edges.add(edge['id'])
                    if edge['kind'] in ('reads_data', 'writes_data'):
                        obligation_kind = 'data_target'
                    elif edge['kind'] in ('invokes_endpoint', 'emits') or (
                            edge['to_ref'] and edge['to_ref']['kind'] == 'resource'
                            and edge['kind'] == 'calls'):
                        obligation_kind = 'external_boundary'
                    else:
                        obligation_kind = 'call_target'
                    if edge['resolution'] != 'resolved' or not edge['to_ref']:
                        status = ('external' if obligation_kind == 'external_boundary' and edge['to_ref']
                                  else 'ambiguous' if edge['resolution']=='ambiguous' else 'unresolved')
                        require(obligation_kind, symbol, status,
                                'UNRESOLVED_TARGET', edge['reason'] or 'Relationship target is not resolved.',
                                edge['id'], edge['candidate_target_ids'] or (
                                    [edge['to_ref']['id']] if edge['to_ref'] else []))
                        frontier.add(edge['id'])
                        reasons.add('external_boundary' if status == 'external' else edge['resolution'])
                        continue
                    target = edge['to_ref']['id']
                    if edge['to_ref']['kind'] != 'symbol':
                        external = obligation_kind == 'external_boundary'
                        require(obligation_kind, symbol, 'external' if external else 'satisfied',
                                'EXTERNAL_IMPLEMENTATION_UNAVAILABLE' if external else 'RESOLVED_RESOURCE_TARGET',
                                ('The operation reaches an external resource whose implementation is unavailable.'
                                 if external else 'The relationship identifies a resource terminal.'),
                                edge['id'], [target])
                        if external:
                            frontier.add(edge['id']); reasons.add('external_boundary')
                        continue
                    if target in seen:
                        continue
                    if depth >= self.config['max_trace_depth']:
                        require('depth_limit', symbol, 'limit_reached', 'DEPTH_LIMIT',
                                'Depth budget prevents completing this relationship.', edge['id'], [target])
                        frontier.add(target); reasons.add('depth_limit'); continue
                    queue.append((target, depth + 1))

            for symbol in sorted(seen - {start.symbol_id}):
                require_capabilities(units_by_symbol[symbol])

            if selection_status == 'satisfied' and selected_target and selected_target not in seen:
                selection_status = 'unresolved'
                selection_reason = 'The selected implementation was not reached within traversal limits.'
            reason_code = {
                'satisfied': 'IMPLEMENTATION_REACHED',
                'ambiguous': 'IMPLEMENTATION_AMBIGUOUS',
                'external': 'EXTERNAL_IMPLEMENTATION_UNAVAILABLE',
                'unresolved': 'IMPLEMENTATION_NOT_REACHED',
            }[selection_status]
            require('implementation_selection', anchor['symbol_id'], selection_status,
                    reason_code, selection_reason, targets=selection_targets)
            if selection_status != 'satisfied':
                frontier.update(selection_targets or [anchor['symbol_id']])
                reasons.add('implementation_ambiguous' if selection_status == 'ambiguous'
                            else 'external_boundary' if selection_status == 'external'
                            else 'implementation_not_reached')
            for symbol in sorted(seen):
                if symbol != anchor['symbol_id'] and not outgoing.get(symbol) \
                        and not (units_by_symbol[symbol].valid_terminal
                                 and units_by_symbol[symbol].executable_body):
                    require('capability', symbol, 'unresolved', 'UNPROVEN_TERMINAL',
                            'Empty adjacency does not establish an executable terminal.')
                    frontier.add(symbol); reasons.add('unproven_terminal')
            evidence = sorted(
                {eid for sid in seen for eid in self.facts['symbols'][sid]['evidence_ids']}
                | {eid for edge_id in edges
                   for eid in self.facts['edges'][edge_id]['evidence_ids']})
            incomplete = any(self.facts['trace_obligations'][oid]['status'] != 'satisfied' for oid in obligations)
            hard_incomplete = any(self.facts['trace_obligations'][oid]['status'] in {
                'unresolved', 'external', 'limit_reached'} for oid in obligations)
            has_ambiguity = any(self.facts['trace_obligations'][oid]['status'] == 'ambiguous'
                                for oid in obligations)
            resolution = 'unresolved' if hard_incomplete else 'ambiguous' if has_ambiguity else 'resolved'
            traversal_complete = not any(reason in {'depth_limit', 'symbol_limit'} for reason in reasons)
            self.facts['traces'][tid] = record('Trace', id=tid, anchor_id=anchor['id'],
                symbol_ids=sorted(seen), edge_ids=sorted(edges), frontier_ids=sorted(frontier),
                obligation_ids=sorted(set(obligations)), stop_reasons=sorted(reasons), evidence_ids=evidence,
                traversal_complete=traversal_complete, resolution=resolution,
                reason='Trace has unsatisfied implementation, capability or traversal obligations.' if incomplete else None)
            unit = next(u for u in self.units if u.anchor_id == anchor['id'])
            interaction = getattr(adapter_for(unit.source),'interaction',None)
            if interaction:
                self.facts['traces'][tid]['ui_interaction'] = interaction(unit,self.evidence,self.facts)
            for effect in self.facts['effects'].values():
                origin = effect.get('origin_ref')
                if origin and origin['kind']=='symbol' and origin['id'] in seen and (
                        not effect.get('edge_id') or effect['edge_id'] in edges):
                    effect['trace_ids'].append(tid)
                    self.facts['traces'][tid]['evidence_ids'] = sorted(
                        set(self.facts['traces'][tid]['evidence_ids'])
                        | set(effect['evidence_ids']))
        for effect in self.facts['effects'].values():
            effect['trace_ids'] = sorted(set(effect['trace_ids']))

    def _connections(self) -> None:
        by_name:dict[str,list[Unit]]={}
        by_symbol = {unit.symbol_id: unit for unit in self.units}
        for u in self.units:
            normalize = getattr(adapter_for(u.source),'symbol_key',lambda name:name)
            by_name.setdefault(normalize(u.name),[]).append(u)
        for unit in self.units:
            if unit.kind=='class':continue
            adapter = adapter_for(unit.source)
            for call in adapter.calls(unit):
                if isinstance(call, dict):
                    receiver = call.get('receiver')
                    name = call.get('name')
                    call_position = call.get('position')
                    call_end = call.get('end')
                    if (not isinstance(name, str) or not name
                            or type(call_position) is not int or type(call_end) is not int
                            or not 0 <= call_position < call_end <= len(unit.text)):
                        raise ValueError('Adapter call record requires a name and valid unit-relative span')
                    call_evidence_id = self.evidence(unit.source,
                        unit.start + call_position, unit.start + call_end)
                else:
                    if unit.source.parser_required:
                        raise ValueError('Parser-backed adapter call records require exact source spans')
                    receiver, name, call_position = call
                    call_evidence_id = unit.evidence_id
                normalize = getattr(adapter,'symbol_key',lambda name:name)
                candidates = adapter.candidates(unit, receiver, name,
                    by_name.get(normalize(name), []), call_position)
                if len(candidates) > 1:
                    candidates = sorted(candidates, key=lambda candidate: candidate.symbol_id)[
                        :MAX_SEMANTIC_CANDIDATES]
                resolver = getattr(adapter, 'resolve_call', None)
                if resolver:
                    semantic = resolver(unit, receiver, name, candidates, call_position,
                        call_evidence_id)
                else:
                    target = candidates[0] if len(candidates) == 1 else None
                    semantic = SemanticResult(
                        capability='callable_resolution',
                        outcome='exact' if target else ('ambiguous' if candidates else 'unresolved'),
                        subject_id=unit.symbol_id,
                        target_id=target.symbol_id if target else None,
                        candidate_target_ids=tuple(sorted(candidate.symbol_id for candidate in candidates))
                            if len(candidates) > 1 else (),
                        evidence_ids=(call_evidence_id,),
                        diagnostic_code=None if target else
                            ('CALL_TARGET_AMBIGUOUS' if candidates else 'CALL_TARGET_UNRESOLVED'),
                        reason=None if target else f'Call target {name}: {len(candidates)} source candidates',
                    )
                result = semantic.normalized()
                if call_evidence_id not in result['evidence_ids']:
                    raise ValueError('Semantic call result must retain call-site evidence')
                unit.source.semantic_results.append(result)
                target = by_symbol.get(result['target_id']) if result['outcome'] == 'exact' else None
                if result['outcome'] == 'exact' and target is None:
                    raise ValueError('Semantic call result targets an unknown symbol')
                external_ref = None
                if result['outcome'] == 'external':
                    external_ref = {'kind':'resource', 'id':result['target_id']}
                    self.facts['resources'].setdefault(result['target_id'], record('Resource',
                        id=result['target_id'], kind='service', name=f'External call: {receiver or unit.owner}.{name}',
                        language=unit.source.language, evidence_ids=list(result['evidence_ids']),
                        resolution='unresolved', reason=result['reason']))
                edgeid=identifier('edge',unit.symbol_id,call_position,name)
                self.facts['edges'][edgeid]=record('Edge',id=edgeid,
                    from_ref={'kind':'symbol','id':unit.symbol_id},
                    to_ref={'kind':'symbol','id':target.symbol_id} if target else external_ref,
                    candidate_target_ids=result['candidate_target_ids'],
                    kind='calls',evidence_ids=result['evidence_ids'],
                    resolution='resolved' if result['outcome']=='exact' else
                               'ambiguous' if result['outcome']=='ambiguous' else 'unresolved',
                    reason=result['reason'])
                if (target and self.facts['evidence'][unit.evidence_id]['source_kind'] == 'test'
                        and self.facts['evidence'][target.evidence_id]['source_kind'] != 'test'):
                    test_edge_id = identifier('edge', unit.symbol_id,
                                              'tests_behavior', target.symbol_id,
                                              call_position)
                    self.facts['edges'][test_edge_id] = record(
                        'Edge', id=test_edge_id,
                        from_ref={'kind':'symbol', 'id':unit.symbol_id},
                        to_ref={'kind':'symbol', 'id':target.symbol_id},
                        kind='tests_behavior', evidence_ids=[call_evidence_id],
                        resolution='resolved', reason=None)
                    self.facts['coverage']['edges_resolved'] += 1
                key='edges_resolved' if target else ('edges_ambiguous'
                    if result['outcome']=='ambiguous' else 'edges_unresolved');self.facts['coverage'][key]+=1
        for source in self.sources:
            relations = getattr(adapter_for(source),'relations',None)
            if not relations:
                continue
            for relation in relations(source):
                origin,target = relation['source'],relation['target']
                eid = self.evidence(source,relation['start'],relation['end'])
                evidence_ids = {eid}
                for evidence_source, start, end in relation.get('evidence_spans', []):
                    if (not isinstance(evidence_source, Source)
                            or type(start) is not int or type(end) is not int
                            or not 0 <= start < end <= len(evidence_source.text)):
                        raise ValueError('Semantic relation has an invalid evidence span')
                    evidence_ids.add(self.evidence(evidence_source, start, end))
                evidence_ids = sorted(evidence_ids)
                candidates = sorted(candidate.symbol_id
                    for candidate in relation.get('candidate_targets', []))
                outcome = relation.get('outcome') or ('exact' if target else
                    'ambiguous' if relation['resolution']=='ambiguous' else 'unresolved')
                semantic = SemanticResult(
                    capability='relationship_resolution', outcome=outcome,
                    subject_id=origin.symbol_id,
                    target_id=(target.symbol_id if outcome=='exact' else
                               relation.get('external_target_id') if outcome=='external' else None),
                    candidate_target_ids=tuple(candidates) if outcome=='ambiguous' else (),
                    evidence_ids=tuple(evidence_ids),
                    diagnostic_code=None if outcome=='exact' else relation.get(
                        'diagnostic_code', 'RELATIONSHIP_'+outcome.upper()),
                    reason=None if outcome=='exact' else relation['reason'],
                ).normalized()
                source.semantic_results.append(semantic)
                edge_id = identifier('edge',origin.symbol_id,relation['kind'],relation['start'],relation['end'])
                external_ref = None
                if outcome == 'external' and semantic['target_id']:
                    external_ref = {'kind':'resource', 'id':semantic['target_id']}
                    self.facts['resources'].setdefault(semantic['target_id'], record(
                        'Resource', id=semantic['target_id'], kind='service',
                        name=f'External type: {relation.get("external_target_id")}',
                        language=source.language, evidence_ids=evidence_ids,
                        resolution='resolved', reason=None))
                self.facts['edges'][edge_id] = record('Edge',id=edge_id,
                    from_ref={'kind':'symbol','id':origin.symbol_id},
                    to_ref={'kind':'symbol','id':target.symbol_id} if target else external_ref,
                    candidate_target_ids=semantic['candidate_target_ids'],
                    kind=relation['kind'], resolution=relation['resolution'],
                    reason=None if relation['resolution']=='resolved' else relation['reason'],
                    evidence_ids=evidence_ids)
                self.facts['coverage']['edges_'+relation['resolution']] += 1

    def _observations(self) -> None:
        for unit in self.units:
            adapter = adapter_for(unit.source)
            if not adapter:
                continue
            for resource in adapter.resources(unit):
                rid = identifier('resource',resource['kind'],resource['name'].casefold())
                stored = self.facts['resources'].setdefault(rid,record('Resource',id=rid,
                    evidence_ids=[],**resource))
                if unit.evidence_id not in stored['evidence_ids']:
                    stored['evidence_ids'].append(unit.evidence_id)
            for observation in adapter.observations(unit):
                observation = redact_values(observation)
                start, end = observation.pop('span')
                eid = self.evidence(unit.source, unit.start+start, unit.start+end)
                resource = observation.pop('resource',None)
                if resource:
                    rid = identifier('resource',resource['kind'],resource['name'].casefold())
                    self.facts['resources'].setdefault(rid,record('Resource',id=rid,evidence_ids=[eid],**resource))
                    observation.setdefault('dependency_ids',[]).append(rid)
                oid = identifier('observation', unit.symbol_id, start)
                self.facts['rule_observations'][oid] = record('RuleObservation', id=oid,
                    evidence_ids=[eid], **{'resolution':'unresolved',
                    'reason':'Condition observed; outcome and enforcement scope require trace interpretation.',
                    **observation})
            for observed in adapter.operations(unit):
                self._hydrate_operation(unit, redact_values(observed))

    def _hydrate_operation(self, unit: Unit, raw: dict) -> None:
        """Atomically project one normalized operation into canonical facts."""
        observed = normalize_operation_observation(unit, raw)
        position, end = observed['position'], observed['end']
        origin = observed['origin_ref']
        target = observed['resource']
        target_ref = ({'kind': 'resource', 'id': identifier(
            'resource', target['kind'], target['name'].casefold())}
            if target else None)

        binding_ids = {'input': set(observed['input_binding_ids']),
                       'output': set(observed['output_binding_ids'])}
        binding_ids['input'].update(observed['header_binding_ids'])
        for direction in ('input', 'output'):
            names = set(observed[direction+'_binding_names'])
            matched = {
                bid for bid, binding in self.facts['bindings'].items()
                if binding['source'] == origin and binding['direction'] == direction
                and binding['name'] in names}
            matched_names = {self.facts['bindings'][bid]['name'] for bid in matched}
            if names - matched_names:
                raise ValueError(
                    f'Normalized operation references unknown {direction} binding names')
            binding_ids[direction].update(matched)

        gap_projections = {gap['projection'] for gap in observed['projection_gaps']}
        for direction in ('input', 'output'):
            missing_ids = binding_ids[direction] - self.facts['bindings'].keys()
            if missing_ids:
                raise ValueError(
                    f'Normalized operation references unknown {direction} binding IDs')
            incomplete = any(
                self.facts['bindings'][bid]['resolution'] != 'resolved'
                for bid in binding_ids[direction]) or any(
                    binding['resolution'] != 'resolved'
                    for binding in observed[direction+'_bindings'])
            projection = direction + '_bindings'
            if incomplete and (observed['resolution'] == 'resolved'
                               or projection not in gap_projections):
                raise ValueError(
                    'Incomplete operation binding requires an unresolved operation '
                    'and matching projection gap')

        evidence_id = self.evidence(unit.source, unit.start+position, unit.start+end)
        supporting_evidence_ids = sorted({self.evidence(unit.source,
            unit.start+start, unit.start+finish)
            for start, finish in observed['supporting_evidence_spans']})
        effect_evidence_ids = sorted({evidence_id, *supporting_evidence_ids})
        if target:
            rid = target_ref['id']
            stored = self.facts['resources'].setdefault(rid, record('Resource', id=rid,
                evidence_ids=[], **target))
            if evidence_id not in stored['evidence_ids']:
                stored['evidence_ids'].append(evidence_id)
        for direction in ('input', 'output'):
            for binding in observed[direction+'_bindings']:
                bid = identifier('binding', unit.symbol_id, direction, binding['name'],
                                 binding['position'], binding['end'])
                binding_evidence = self.evidence(unit.source,
                    unit.start+binding['position'], unit.start+binding['end'])
                source = origin if direction == 'input' or not target_ref else target_ref
                destination = target_ref if direction == 'input' and target_ref else origin
                self.facts['bindings'][bid] = record('Binding', id=bid,
                    name=binding['name'], value_type=binding['value_type'],
                    direction=direction, source=source, target=destination,
                    expression=binding['expression'], evidence_ids=[binding_evidence],
                    resolution=binding['resolution'], reason=binding['reason'])
                binding_ids[direction].add(bid)

        edge_kind = CATALOG['operation_edge_kinds'].get(observed['kind'])
        if edge_kind is None:
            raise ValueError('Normalized operation kind has no canonical edge projection')
        edge_id = identifier('edge', unit.symbol_id, edge_kind, position, target_ref)
        all_bindings = sorted(binding_ids['input'] | binding_ids['output'])
        self.facts['edges'][edge_id] = record('Edge', id=edge_id,
            from_ref=origin, to_ref=target_ref, kind=edge_kind,
            binding_ids=all_bindings, condition=observed['condition'],
            evidence_ids=[evidence_id], resolution=observed['resolution'],
            reason=observed['reason'])
        self.facts['coverage']['edges_'+observed['resolution']] += 1

        effect_id = None
        if observed['kind'] != 'data_read':
            effect_id = identifier('effect', unit.symbol_id, position)
            self.facts['effects'][effect_id] = record('Effect', id=effect_id,
                kind=observed['kind'], target=target_ref, origin_ref=origin,
                edge_id=edge_id, input_binding_ids=sorted(binding_ids['input']),
                output_binding_ids=sorted(binding_ids['output']),
                condition=observed['condition'], outcome=observed['outcome'],
                protocol=observed['protocol'], status=observed['status'],
                media_type=observed['media_type'],
                header_binding_ids=observed['header_binding_ids'],
                transaction_scope=observed['transaction_scope'],
                completion=observed['completion'], evidence_ids=effect_evidence_ids,
                resolution=observed['resolution'], reason=observed['reason'])

        if observed['resolution'] != 'resolved':
            subjects = [edge_id]
            for gap in observed['projection_gaps']:
                self.diagnostics.append(record('Diagnostic',
                    code=gap['code'],
                    message=f"{gap['projection']}: {gap['reason']}",
                    subject_ids=subjects, evidence_ids=effect_evidence_ids))
