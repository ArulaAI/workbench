"""Normalize existing declarative extraction matches into evidence records.

This adapter does not recognize language keywords, decorators or frameworks.
Those decisions belong to the existing rules/{language} catalog.
"""
import re
from .base import (SemanticResult, Unit, declare_anchor_registration,
                   declare_anchor_representation,
                   declare_operation_observation, declare_trace_contract,
                   http_identity)
from . import CATALOG
from ..csg import resolve_source_reference
from ..language_registry import registry
from ..treesitter_extract import (ExtractionResult, match_source,
    _parse_ast_grep_matches, normalize_rule_outputs)
from ..business_domain_schema import record, identifier


def span(source, match):
    if hasattr(match, 'source_range'):
        match = {'range': match.source_range}
    raw = source.text.encode()
    offsets = match.get('range', {}).get('byteOffset')
    if offsets:
        return len(raw[:offsets['start']].decode()), len(raw[:offsets['end']].decode())
    lines = source.text.splitlines(keepends=True)
    bounds = match['range']
    return tuple(sum(len(line) for line in lines[:bounds[side]['line']])+
                 len(lines[bounds[side]['line']].encode()[:bounds[side]['column']].decode())
                 for side in ('start', 'end'))


def capture(match, key):
    if hasattr(match, 'captures'):
        return match.captures.get(key)
    return match.get('metaVariables', {}).get('single', {}).get(key, {}).get('text')


def owns(unit,start,end):
    return unit.start <= start < end <= unit.end and not any(
        other is not unit and unit.start <= other.start <= start < end <= other.end <= unit.end
        and (other.start,other.end)!=(unit.start,unit.end) for other in unit.source.units)


def extract(source):
    matches = match_source(source.text, source.language)
    source.rule_outputs = normalize_rule_outputs(matches)
    source.definitions, source.references, _ = _parse_ast_grep_matches(matches, source.path, source.path)
    units = []
    for definition in source.definitions:
        if definition.structural_only:
            continue
        extracted_kind = definition.kind
        kind = CATALOG['symbol_kind_aliases'].get(extracted_kind, extracted_kind)
        name = definition.name
        start, end = span(source, {'range': definition.source_range})
        if any(u.start == start and u.end == end for u in units):
            continue
        units.append(Unit(source, name, '', start, end, kind,anchor_kind=definition.anchor_kind,
                          executable_body=definition.executable_body))
    # Rules may select both a decorated declaration and its wrapped body.
    # They denote one symbol when name/end coincide; retain the evidence span
    # that also contains the declaration metadata.
    units = [u for u in units if not any(v.name == u.name and v.end == u.end
              and v.start < u.start for v in units)]
    for unit in units:
        enclosing = sorted([u for u in units if u.start <= unit.start and u.end >= unit.end
                            and (u.start, u.end) != (unit.start, unit.end)], key=lambda u: u.end-u.start)
        unit.owner = enclosing[0].name if enclosing else None
        unit.qualified = source.path+'::'+'.'.join(filter(None, [unit.owner, unit.name]))
        # Position disambiguates anonymous/overloaded declarations; body content
        # never contributes a business label.
        peers = [u for u in units if u.name == unit.name]
        if len(peers) > 1:
            unit.qualified += ':'+str(sorted(peers, key=lambda u:u.start).index(unit))
        for match in source.rule_outputs:
            metadata = match.attributes
            start, end = span(source, match)
            if (match.output_type == 'entrypoint_implementation'
                    and (start, end) == (unit.start, unit.end)):
                unit.anchor_role = 'implementation'
                unit.anchor_eligibility = 'supporting'
                unit.anchor_visibility = 'internal'
                unit.ui_implementation = True
            if match.output_type != 'business_anchor':
                continue
            if (start,end) == (unit.start,unit.end) and unit.kind in metadata.get('symbol_kinds', [unit.kind]):
                unit.anchor_kind = metadata['anchor_kind']
                unit.method = metadata.get('method')
                if metadata.get('method_var'):
                    method = capture(match,metadata['method_var'])
                    unit.method = method.upper() if method else None
                unit.route = capture(match, metadata.get('route_var'))
                if unit.route and metadata.get('route_pattern'):
                    literal = re.fullmatch(metadata['route_pattern'],unit.route)
                    unit.route = literal.group(1) if literal else None
        if unit.anchor_kind:
            unit.anchor_resolution = 'unresolved'
            unit.anchor_reason = 'Entry-point registration and effective identity have not been fully resolved.'
            if unit.anchor_kind == 'http' and unit.method and unit.route:
                unit.anchor_resolution = 'resolved'
                unit.anchor_reason = None
            identity_key = (http_identity(source, unit.method, unit.route)
                            if unit.anchor_kind == 'http' else None)
            declare_anchor_representation(unit,
                'registration' if unit.anchor_kind != 'ui' else 'exposure',
                identity_key,
                'eligible' if identity_key else 'unresolved',
                'external' if unit.anchor_kind in {'http', 'ui'} else 'internal')
            if unit.anchor_role in {'registration', 'exposure'}:
                declare_anchor_registration(unit,
                    'http_route' if unit.anchor_kind == 'http' else 'invocation',
                    event=unit.method,
                    target=unit.name, scope=source.service_scope,
                    resolution=unit.anchor_resolution, reason=unit.anchor_reason)
        elif unit.executable_body:
            unit.anchor_role = 'implementation'
            unit.anchor_eligibility = 'supporting'
            unit.anchor_visibility = 'internal'
        declare_trace_contract(unit, 'implementation' if unit.executable_body else 'declaration')
    registrations = []
    for match in source.rule_outputs:
        if match.output_type != 'entrypoint_registration':
            continue
        metadata = match.attributes
        start, end = span(source, match)
        owners = sorted((unit for unit in units
                         if unit.start <= start and end <= unit.end),
                        key=lambda unit: unit.end-unit.start)
        owner = owners[0] if owners else None
        registration_kind = metadata['registration_kind']
        target = capture(match, metadata.get('target_var'))
        raw_route = capture(match, metadata.get('route_var'))
        route = raw_route
        if metadata.get('route_dynamic'):
            route = None
        elif route and metadata.get('route_pattern'):
            literal = re.fullmatch(metadata['route_pattern'], route)
            route = literal.group(1) if literal else None
        label = None
        if metadata.get('label_pattern'):
            label_match = re.search(metadata['label_pattern'], match.text)
            label = label_match.group(1).strip() if label_match else None
            label = label or None
        method = metadata.get('method')
        name = (target or 'dynamic route') if registration_kind == 'route' else (
            label or 'unlabeled action')
        qualified = (f'{source.path}::registration.{registration_kind}.'
                     f'{start}.{end}')
        identity_key = (f'ui:{source.service_scope}:route:{route}' if route else
            f'ui:{source.service_scope}:action:{owner.qualified if owner else source.path}:'
            f'{method}:{start}:{end}' if registration_kind == 'action' else None)
        registration = Unit(source, name, qualified, start, end,
            'declarative_operation', owner=owner.name if owner else None,
            anchor_kind=metadata['anchor_kind'], method=method, route=route,
            anchor_resolution='unresolved',
            anchor_reason='Registration target has not been semantically resolved.')
        registration.anchor_registration_kind = registration_kind
        registration.anchor_target_name = target
        registration.anchor_route_expression = raw_route
        registration.anchor_owner_unit = owner
        registration.anchor_label = label
        registration.anchor_match = match
        registration.anchor_correspondence_relationship_kind = metadata['edge_kind']
        declare_anchor_representation(registration, metadata['role'], identity_key,
            'eligible' if identity_key else 'unresolved', 'external')
        declare_trace_contract(registration, 'declaration')
        registrations.append(registration)
    units.extend(registrations)
    source.units = units
    return units


def _implementation_target(unit, units):
    """Select the executable component body behind an exact symbol target."""
    if unit.kind != 'class':
        return unit
    renders = [candidate for candidate in units
               if candidate.source is unit.source and candidate.owner == unit.name
               and candidate.name == 'render' and candidate.executable_body]
    return renders[0] if len(renders) == 1 else unit


def _import_bindings(source):
    """Map every identifier this file imports to the module it came from."""
    bindings = {}
    for reference in source.references:
        if reference.kind != 'import':
            continue
        module = (reference.module or '').strip('\'"')
        if not module:
            continue
        for symbol in reference.symbols:
            # One import statement matches several declarative patterns, and a
            # clause may rename what it binds. The bound name is the one a call
            # site can reach, so `browserHistory as history` binds `history`
            # and `* as React` binds `React`.
            for clause in symbol.strip().strip('{}').split(','):
                bound = clause.strip().rsplit(' as ', 1)[-1].strip()
                if re.fullmatch(r'[A-Za-z_$][\w$]*', bound):
                    bindings[bound] = module
    return bindings


def _receiver_root(reference):
    """Return the identifier a call is rooted at, or None if it is an expression.

    A rule may elide an implicit receiver so lexical scoping still reaches a
    sibling declaration, but the written text keeps it. Reading the root from
    that text is what stops `this.location()` being taken for a call on the
    ambient `location`.
    """
    if reference.receiver:
        head = reference.receiver
    elif '.' in (reference.name or ''):
        head = reference.name
    else:
        head = reference.callee_name or ''
    root = head.split('.', 1)[0].strip()
    return root if re.fullmatch(r'[A-Za-z_$][\w$]*', root) else None


def _ambient_boundaries(source, resolve_name):
    """Index the calls reached through a name the language binds, not this tree.

    A root the canonical resolver cannot place, that this file does not import,
    and that the language binds ambiently, is a platform call: no repository
    declares it because no repository ever declares one. Any other unplaceable
    root is a local binding this extractor does not see -- a parameter, a
    destructured prop, a lambda argument -- and stays unresolved, because an
    unknown receiver is not evidence of a boundary.
    """
    ambient = registry.ambient_globals(source.language)
    if not ambient:
        return {}
    bindings = _import_bindings(source)
    boundaries = {}
    for reference in source.references:
        if reference.kind != 'call' or not reference.callee_name:
            continue
        root = _receiver_root(reference)
        if root not in ambient or root in bindings or resolve_name(root) is not None:
            continue
        start, _end = span(source, {'range': reference.source_range})
        boundaries[(start, reference.callee_name)] = (root,
            f'{root} is a name {source.language} binds ambiently and this '
            f'repository neither declares nor imports.' if root == reference.callee_name
            else f'{reference.callee_name} is reached through {root}, a name '
                 f'{source.language} binds ambiently and this repository '
                 f'neither declares nor imports.')
    return boundaries


def prepare(sources, units, diagnostics=None):
    """Resolve normalized UI registrations/composition through the CSG owner."""
    relevant = [unit for unit in units if unit.source in sources]
    resolvable = [unit for unit in relevant
                  if not getattr(unit, 'anchor_registration_kind', None)]
    nodes = [{'id': unit.qualified, 'name': unit.name, 'file': unit.source.path,
              'kind': unit.kind} for unit in resolvable]
    extractions = {source.path: ExtractionResult(source.path, source.language,
        definitions=source.definitions, references=source.references)
        for source in sources}
    by_id = {unit.qualified: unit for unit in resolvable}

    # Reuse the canonical CSG resolver for exact lexical/import call links.
    # The connection phase still owns edge materialization; this adapter-owned
    # index only supplies the evidenced target selected by that resolver.
    for source in sources:
        source.resolved_call_targets = {}
        for reference in source.references:
            if reference.kind != 'call' or not reference.callee_name:
                continue
            start, end = span(source, {'range': reference.source_range})
            target_id = resolve_source_reference(reference.callee_name,
                source.path, nodes, extractions)
            target = by_id.get(target_id)
            if target:
                source.resolved_call_targets[(start, reference.callee_name)] = target
        # The same canonical resolver answers the complementary question: a root
        # it cannot place, that the file never imports, and that the language
        # binds ambiently, ends the path rather than breaking it.
        source.ambient_call_boundaries = _ambient_boundaries(
            source, lambda name: resolve_source_reference(
                name, source.path, nodes, extractions))

    def resolve(name, source):
        if not name or not re.fullmatch(r'(?:this\.)?[A-Za-z_$][\w$]*', name):
            return None
        target_id = resolve_source_reference(name, source.path, nodes, extractions)
        target = by_id.get(target_id)
        return _implementation_target(target, relevant) if target else None

    registrations = [unit for unit in relevant
        if getattr(unit, 'anchor_registration_kind', None)]
    lifecycle_targets = []
    for source in sources:
        for match in source.rule_outputs:
            if (match.output_type != 'semantic_relation'
                    or not match.attributes.get('route_activation')):
                continue
            start, end = span(source, match)
            targets = [candidate for candidate in relevant
                if candidate.source is source
                and candidate.start == start and candidate.end == end]
            if len(targets) == 1:
                lifecycle_targets.append((targets[0], match, start, end))
    dynamic_selections = {}
    for source in sources:
        for match in source.rule_outputs:
            if match.output_type != 'dynamic_selection':
                continue
            selector = capture(match, match.attributes.get('selector_var'))
            selected = [resolve(capture(match, name), source)
                for name in match.attributes.get('candidate_vars', [])]
            selected = [target for target in selected if target]
            if selector and selected:
                dynamic_selections[(source.path, selector)] = selected
    route_context = {}
    for unit in registrations:
        if unit.anchor_registration_kind != 'route':
            continue
        target = resolve(unit.anchor_target_name, unit.source)
        targets = ([target] if target else dynamic_selections.get(
            (unit.source.path, unit.anchor_target_name), []))
        for candidate in targets:
            route_context.setdefault(id(candidate), []).append(unit.route)
        complete = bool(unit.route and len(targets) == 1)
        ambiguous = len(targets) > 1
        unit.anchor_correspondence_units = targets
        unit.anchor_correspondence_state = ('resolved' if complete else
            'ambiguous' if ambiguous else 'unresolved')
        unit.anchor_correspondence_reason = (None if complete else
            'Route target or path is dynamically selected from multiple evidenced candidates.'
            if ambiguous else
            'Route target is dynamic, ambiguous, or not resolved through source/import evidence.')
        unit.anchor_resolution = ('resolved' if complete else
            'ambiguous' if ambiguous else 'unresolved')
        unit.anchor_reason = unit.anchor_correspondence_reason
        declare_anchor_registration(unit, 'route', target=unit.anchor_target_name,
            scope=unit.source.service_scope, resolution=unit.anchor_resolution,
            reason=unit.anchor_reason,
            candidate_targets=[f'{target.owner}.{target.name}' if target.owner else target.name
                for target in targets] if ambiguous else [])
        unit.anchor_context_unit = targets[0] if len(targets) == 1 else None
        unit.source.normalized_relations = getattr(unit.source, 'normalized_relations', [])
        unit.source.normalized_relations.append({'source': unit,
            'target': targets[0] if complete else None,
            'candidate_targets': targets if ambiguous else [],
            'kind': unit.anchor_correspondence_relationship_kind,
            'start': unit.start, 'end': unit.end,
            'resolution': unit.anchor_resolution,
            'outcome': 'exact' if complete else 'ambiguous' if ambiguous else 'unresolved',
            'diagnostic_code': None if complete else
                'UI_ROUTE_TARGET_AMBIGUOUS' if ambiguous else 'UI_ROUTE_TARGET_UNRESOLVED',
            'reason': unit.anchor_correspondence_reason})
        if complete:
            for lifecycle, match, start, end in lifecycle_targets:
                if (lifecycle.source is not targets[0].source
                        or lifecycle.owner != targets[0].owner):
                    continue
                unit.source.normalized_relations.append({'source': unit,
                    'target': lifecycle, 'kind': match.attributes['edge_kind'],
                    'start': unit.start, 'end': unit.end,
                    'evidence_spans': [(unit.source, unit.start, unit.end),
                        (lifecycle.source, start, end)],
                    'resolution': 'resolved', 'reason': None})

    for unit in registrations:
        if unit.anchor_registration_kind != 'action':
            continue
        target = resolve(unit.anchor_target_name, unit.source)
        owner = getattr(unit, 'anchor_owner_unit', None)
        contexts = route_context.get(id(owner), [])
        unit.route = contexts[0] if len(contexts) == 1 else None
        scope = unit.route or (owner.qualified if owner else unit.source.path)
        unit.anchor_identity_key = (f'ui:{unit.source.service_scope}:action:'
            f'{scope}:{unit.method}:{unit.start}:{unit.end}')
        complete = bool(target and unit.anchor_label)
        reason = None if complete else (
            'Visible action label is not statically resolved.' if target else
            'Action callback is dynamic, ambiguous, or not resolved through lexical/import evidence.')
        unit.anchor_correspondence_units = [target] if target else []
        unit.anchor_correspondence_state = 'resolved' if target else 'unresolved'
        unit.anchor_correspondence_reason = (None if target else reason)
        unit.anchor_resolution = 'resolved' if complete else 'unresolved'
        unit.anchor_reason = reason
        semantic_target = (f'{target.owner}.{target.name}' if target and target.owner
                           else target.name if target else unit.anchor_target_name)
        declare_anchor_registration(unit, 'action', event=unit.method,
            target=semantic_target, scope=scope, label=unit.anchor_label,
            resolution=unit.anchor_resolution, reason=unit.anchor_reason)
        unit.anchor_context_unit = owner
        unit.source.normalized_relations = getattr(unit.source, 'normalized_relations', [])
        unit.source.normalized_relations.append({'source': unit, 'target': target,
            'kind': unit.anchor_correspondence_relationship_kind,
            'start': unit.start, 'end': unit.end,
            'resolution': 'resolved' if target else 'unresolved',
            'reason': None if target else reason})
        if owner and owner is not target:
            unit.source.normalized_relations.append({'source': unit, 'target': owner,
                'kind': 'composes', 'start': unit.start, 'end': unit.end,
                'resolution': 'resolved', 'reason': None})

    for source in sources:
        for match in source.rule_outputs:
            if match.output_type != 'component_composition':
                continue
            start, end = span(source, match)
            origins = sorted((unit for unit in relevant
                if unit.source is source and getattr(unit, 'ui_implementation', False)
                and unit.start <= start and end <= unit.end),
                key=lambda unit: unit.end-unit.start)
            if not origins:
                continue
            target_name = capture(match, match.attributes.get('target_var'))
            target = resolve(target_name, source)
            reason = None if target else (
                'Child component is dynamic, ambiguous, or not resolved through source/import evidence.')
            source.normalized_relations = getattr(source, 'normalized_relations', [])
            source.normalized_relations.append({'source': origins[0], 'target': target,
                'kind': match.attributes['edge_kind'], 'start': start, 'end': end,
                'resolution': 'resolved' if target else 'unresolved', 'reason': reason})


def parameter_direction(type_name):
    return 'input'


def bindings(unit):
    result = []
    for match in unit.source.rule_outputs:
        metadata = match.attributes
        if match.output_type != 'binding':
            continue
        if unit.kind not in metadata.get('symbol_kinds',[unit.kind]):
            continue
        start,end = span(unit.source,match)
        if not owns(unit,start,end):
            continue
        expression = capture(match, metadata.get('expression_var')) or match.text
        name = capture(match, metadata.get('name_var')) or metadata.get('direction','value')+'@'+str(start)
        result.append({'name':name,'value_type':capture(match,metadata.get('type_var')) or 'unknown',
                       'direction':metadata['direction'],'expression':expression})
    return result


def resources(unit):
    return []


def calls(unit):
    result = []
    for reference in unit.source.references:
        if reference.kind != 'call':
            continue
        start, end = span(unit.source, {'range': reference.source_range})
        if not owns(unit,start,end):
            continue
        result.append({'receiver': reference.receiver,
            'name': reference.callee_name, 'position': start-unit.start,
            'end': end-unit.start})
    return result


def candidates(unit, receiver, name, available, position=None):
    # Only lexical calls are proven here. Receiver/type/import binding is a
    # separate capability; a globally unique name does not prove a call target.
    if receiver:
        declared_types = set()
        for match in unit.source.rule_outputs:
            metadata = match.attributes
            if match.output_type != 'receiver_binding':
                continue
            if capture(match,metadata.get('receiver_var')) != receiver:
                continue
            start,end = span(unit.source,match)
            enclosing = sorted((u for u in unit.source.units if u.start <= start and end <= u.end),
                               key=lambda u:u.end-u.start)
            # A binding belongs to its nearest declaration. A sibling method's
            # parameter is not visible merely because both share an outer class.
            if not enclosing or not (enclosing[0].start <= unit.start and unit.end <= enclosing[0].end):
                continue
            declared = capture(match,metadata.get('type_var'))
            if declared:
                declared_types.add(declared)
        return [c for c in available if c.owner in declared_types]
    scopes = [unit.name,unit.owner]
    enclosing = sorted([u for u in unit.source.units if u.start < unit.start and unit.end <= u.end],
                       key=lambda u:u.end-u.start)
    scopes.extend(u.owner for u in enclosing)
    for owner in scopes:
        candidates = [c for c in available if c.source.path == unit.source.path and c.owner == owner]
        if candidates:
            return candidates
    imported = getattr(unit.source, 'resolved_call_targets', {}).get(
        (unit.start + position, name)) if position is not None else None
    if imported:
        return [imported]
    return []


def resolve_call(unit, receiver, name, candidates, position, evidence_id=None):
    """Separate a platform call from a call this repository fails to answer.

    Lexical candidates still decide every call the repository does answer; the
    boundary index is consulted only after they come back empty, so this can
    never override a proven target.
    """
    evidence = (evidence_id or unit.evidence_id,)
    if len(candidates) == 1:
        return SemanticResult(capability='callable_resolution', outcome='exact',
            subject_id=unit.symbol_id, target_id=candidates[0].symbol_id,
            evidence_ids=evidence)
    if candidates:
        return SemanticResult(capability='callable_resolution', outcome='ambiguous',
            subject_id=unit.symbol_id,
            candidate_target_ids=tuple(sorted(c.symbol_id for c in candidates)),
            evidence_ids=evidence, diagnostic_code='CALL_TARGET_AMBIGUOUS',
            reason=f'Call target {name}: {len(candidates)} source candidates')
    boundary = getattr(unit.source, 'ambient_call_boundaries', {}).get(
        (unit.start + position, name))
    if boundary:
        root, reason = boundary
        return SemanticResult(capability='callable_resolution', outcome='external',
            subject_id=unit.symbol_id,
            target_id=identifier('resource', 'ambient-call',
                                 unit.source.language, root, name),
            evidence_ids=evidence, diagnostic_code='RULES_AMBIENT_CALL',
            reason=reason)
    return SemanticResult(capability='callable_resolution', outcome='unresolved',
        subject_id=unit.symbol_id, evidence_ids=evidence,
        diagnostic_code='CALL_TARGET_UNRESOLVED',
        reason=f'Call target {name}: 0 source candidates')


def observations(unit):
    result = []
    for match in unit.source.rule_outputs:
        metadata = match.attributes
        if match.output_type != 'rule_observation':
            continue
        start, end = span(unit.source, match)
        if owns(unit,start,end):
            result.append({'span':(start-unit.start,end-unit.start),
                'source_location_kind':metadata['source_location_kind'],
                'native_expression':capture(match,metadata.get('expression_var')) or match.text})
    return result


def _http_target(unit, expression, before, seen=()):
    """Resolve only literal, wrapper-literal, or local constant HTTP targets."""
    expression = (expression or '').strip()
    quoted = re.fullmatch(r'''(["'`])(.*)\1''', expression, re.DOTALL)
    if quoted:
        body = quoted.group(2)
        variables = re.findall(r'\$\{([^{}]+)\}', body)
        if not variables:
            return body, True, True, []
        if all(re.fullmatch(r'\s*[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\s*',
                            variable) for variable in variables):
            return re.sub(r'\$\{([^{}]+)\}',
                lambda match: '{'+match.group(1).strip()+'}', body), True, False, []
    pieces = re.split(r'\s*\+\s*', expression)
    if len(pieces) > 1:
        canonical = []
        for piece in pieces:
            literal = re.fullmatch(r'''(["'])(.*)\1''', piece, re.DOTALL)
            if literal:
                canonical.append(literal.group(2))
            elif re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*', piece):
                canonical.append('{'+piece+'}')
            else:
                canonical = []
                break
        if canonical:
            return ''.join(canonical), True, False, []
    wrapped = re.fullmatch(r'url\((.*)\)', expression, re.DOTALL)
    if wrapped:
        return _http_target(unit, wrapped.group(1), before, seen)
    if re.fullmatch(r'[A-Za-z_$][\w$]*', expression) and expression not in seen:
        declarations = list(re.finditer(
            rf'\b(?:const|let|var)\s+{re.escape(expression)}(?:\s*:[^=;]+)?\s*=\s*([^;]+);',
            unit.text[:before], re.DOTALL))
        if declarations:
            name, resolved, value_resolved, spans = _http_target(unit,
                declarations[-1].group(1), declarations[-1].start(1),
                (*seen, expression))
            return name, resolved, value_resolved, [
                (declarations[-1].start(), declarations[-1].end()), *spans]
    return (f'{unit.source.path}::{expression or "unknown destination"}',
            False, False, [])


def _operation_binding(unit, name, expression, start, resolution, reason):
    return {'name': name, 'value_type': 'http', 'expression': expression,
        'position': start, 'end': start + len(expression),
        'resolution': resolution, 'reason': reason}


def http_operation(unit, match, metadata=None):
    """Normalize one tree-selected HTTP call for every frontend reader."""
    metadata = metadata or match.attributes
    start, end = span(unit.source, match)
    expression = capture(match, metadata.get('target_var'))
    operation_start = start - unit.start
    target_name, target_resolved, target_value_resolved, target_evidence = \
        _http_target(unit, expression, operation_start)
    expression_at = match.text.find(expression) if expression else -1
    if expression_at < 0:
        raise ValueError('HTTP operation target capture is outside its exact call span')
    target_start = operation_start + expression_at
    dynamic_reason = None if target_resolved else (
        'HTTP destination value is dynamic; its call-site expression is retained.')
    inputs = [_operation_binding(unit, f'http.target@{operation_start}',
        expression, target_start,
        'resolved' if target_value_resolved else 'unresolved',
        None if target_value_resolved else
            ('The endpoint pattern is known, but its runtime values are not.'
             if target_resolved else dynamic_reason))]
    request = capture(match, metadata.get('request_var'))
    if request:
        request_at = match.text.find(request, expression_at+len(expression))
        if request_at < 0:
            raise ValueError('HTTP request capture is outside its exact call span')
        inputs.append(_operation_binding(unit, f'http.request@{operation_start}',
            request, operation_start+request_at, 'unresolved',
            'Request expression is evidenced; runtime request values are unavailable.'))
    outputs = [_operation_binding(unit, f'http.response@{operation_start}',
        match.text, operation_start, 'unresolved',
        'Response mapping is evidenced only after the remote call executes.')]
    projection_gaps = [{
        'projection': 'completion',
        'code': 'HTTP_OUTCOME_UNVERIFIED',
        'reason': 'The call is declared, but its runtime completion is not established.',
    }, {
        'projection': 'condition',
        'code': 'HTTP_CONTROL_FLOW_NOT_ESTABLISHED',
        'reason': 'Path-sensitive execution conditions are not established by this rule.',
    }, {
        'projection': 'output_bindings',
        'code': 'HTTP_RESPONSE_MAPPING_UNRESOLVED',
        'reason': 'The response expression is known, but its runtime value and mapping are not.',
    }]
    if any(binding['resolution'] != 'resolved' for binding in inputs):
        projection_gaps.append({
            'projection': 'input_bindings',
            'code': 'HTTP_REQUEST_MAPPING_UNRESOLVED',
            'reason': 'The request expressions are known, but one or more runtime values are not.',
        })
    if not target_resolved:
        projection_gaps.append({
            'projection': 'target',
            'code': 'HTTP_TARGET_DYNAMIC',
            'reason': dynamic_reason,
        })
    return declare_operation_observation(unit,
        position=operation_start, end=end-unit.start,
        kind=metadata['effect_kind'],
        resource={'kind':metadata['resource_kind'], 'name':target_name,
            'resolution':'resolved' if target_resolved else 'unresolved',
            'reason':None if target_resolved else dynamic_reason},
        input_bindings=inputs, output_bindings=outputs,
        protocol=metadata.get('protocol'), outcome=match.text,
        completion='declared', resolution='unresolved',
        supporting_evidence_spans=target_evidence,
        projection_gaps=projection_gaps,
        reason=('Call expression is present; runtime outcome and destination '
                'implementation are not established.'))


def operations(unit):
    result = []
    for match in unit.source.rule_outputs:
        if match.output_type != 'semantic_effect':
            continue
        start, end = span(unit.source, match)
        if owns(unit, start, end):
            result.append(http_operation(unit, match))
    return result


def relations(source):
    """Normalize declarative graph links and callback registrations."""
    result = list(getattr(source, 'normalized_relations', []))
    for definition in source.definitions:
        if not definition.structural_only:
            continue
        start, end = span(source, {'range': definition.source_range})
        origins = [u for u in source.units if u.name == definition.name
                   and u.start <= start and end <= u.end]
        if not origins:
            raise ValueError('Normalized structural relationship has no source declaration')
        origin = min(origins, key=lambda u: u.end-u.start)
        for kind, names in (('inherits', definition.base_classes), ('implements', definition.implements)):
            for name in names:
                result.append({'source':origin,'target':None,'kind':kind,
                    'start':start,'end':end,'resolution':'unresolved',
                    'reason':f'Declared structural target {name}; semantic type resolution is unavailable.'})
    for match in source.rule_outputs:
        metadata = match.attributes
        start,end = span(source,match)
        enclosing = sorted((u for u in source.units if u.start <= start and end <= u.end),key=lambda u:u.end-u.start)
        if metadata.get('connect_to_enclosing') and len(enclosing)>1:
            result.append({'source':enclosing[1],'target':enclosing[0],'kind':'declares',
                'start':start,'end':end,'resolution':'resolved','reason':None})
        if (match.output_type == 'semantic_relation'
                and metadata.get('route_activation')):
            continue
        if (match.output_type != 'semantic_relation' and not metadata.get('also_relation')) or not enclosing:
            continue
        if (match.output_type == 'ui_event'
                and getattr(enclosing[0], 'anchor_registration_kind', None) == 'action'):
            continue
        if metadata.get('source_kind') and enclosing[0].kind != metadata['source_kind']:
            continue
        source_name = capture(match,metadata.get('from_var'))
        target_name = capture(match,metadata.get('to_var'))
        if metadata.get('requires_endpoint_kind') and not any(u.kind==metadata['requires_endpoint_kind']
                and u.name in (source_name,target_name) for u in source.units):
            continue
        sources = candidates(enclosing[0],None,source_name,[u for u in source.units if u.name == source_name]) if source_name else [enclosing[0]]
        origin = sources[0] if len(sources)==1 else enclosing[0]
        separator = metadata.get('target_separator')
        receiver = None
        if separator and target_name and separator in target_name:
            receiver,target_name = target_name.rsplit(separator,1)
        if receiver == metadata.get('implicit_receiver'):
            receiver = None
        targets = candidates(origin,receiver,target_name,[u for u in source.units if u.name == target_name])
        resolved = len(sources)==len(targets)==1
        result.append({'source':origin,'target':targets[0] if resolved else None,'kind':metadata['edge_kind'],
            'start':start,'end':end,'resolution':'resolved' if resolved else 'unresolved',
            'reason':None if resolved else 'Declarative link has an unresolved source or target expression.'})
    return result


def hydrate_ui_calls(unit, facts, result, traced_symbols=None):
    """Attach calls after any reader has finished resolving UI handlers."""
    traced_symbols = traced_symbols or {
        sid for trace in facts['traces'].values()
        if trace['anchor_id'] == unit.anchor_id for sid in trace['symbol_ids']}
    outgoing = {}
    for edge in facts['edges'].values():
        if edge['resolution'] == 'resolved' and edge['to_ref']:
            outgoing.setdefault(edge['from_ref']['id'], set()).add(
                edge['to_ref']['id'])
    for event in result['events'].values():
        if not event['handler_symbol_id']:
            continue
        pending = [event['handler_symbol_id']]
        visited = set()
        while pending:
            current = pending.pop()
            if current in visited or current not in traced_symbols:
                continue
            visited.add(current)
            pending.extend(outgoing.get(current, set()) - visited)
        for effect in facts['effects'].values():
            origin = effect.get('origin_ref')
            if (effect['protocol'] and effect['kind'] == 'external_action'
                    and origin and origin['id'] in visited):
                cid = identifier('ui_call', event['id'], effect['id'])
                result['calls'][cid] = record('UICall', id=cid,
                    event_id=event['id'],
                    caller_symbol_id=event['handler_symbol_id'],
                    request_binding_ids=effect['input_binding_ids'],
                    response_binding_ids=effect['output_binding_ids'],
                    evidence_ids=sorted(set(
                        event['evidence_ids'] + effect['evidence_ids'])),
                    resolution='unresolved',
                    reason='Registered handler can reach this call expression; request mapping, remote implementation and outcome remain unverified.')
    return result


def interaction(unit,evidence,facts):
    if unit.anchor_kind != 'ui':
        return None
    result = record('UIInteraction')
    view_id = identifier('ui_element',unit.anchor_id,'view')
    context = getattr(unit, 'anchor_context_unit', None) or unit
    label = (getattr(unit, 'anchor_target_name', None)
             if getattr(unit, 'anchor_registration_kind', None) == 'route'
             else context.owner or context.name)
    result['elements'][view_id] = record('UIElement',id=view_id,kind='view',
        symbol_id=context.symbol_id,label=label,
        evidence_ids=sorted({unit.evidence_id, context.evidence_id}),
        route_patterns=[{'pattern':unit.route,'evidence_ids':[unit.evidence_id]}] if unit.route else None,
        routing_resolution='resolved' if unit.route else 'unresolved',resolution='resolved',
        reason=None if unit.route else 'No route registration has been linked to this view.')
    controls = []
    for match in unit.source.rule_outputs:
        metadata = match.attributes
        if match.output_type == 'ui_route':
            start,end = span(unit.source,match)
            if owns(unit,start,end):
                route = capture(match,metadata.get('route_var'))
                literal = re.fullmatch(metadata['route_pattern'],route) if route else None
                eid = evidence(unit.source,start,end)
                route_id = identifier('ui_element',unit.anchor_id,start,'route')
                result['elements'][route_id] = record('UIElement',id=route_id,kind='view',
                    label=capture(match,metadata.get('view_var')),parent_view_id=view_id,evidence_ids=[eid],
                    route_patterns=[{'pattern':literal.group(1),'evidence_ids':[eid]}] if literal else None,
                    routing_resolution='resolved' if literal else 'unresolved',resolution='unresolved',
                    reason='Route declaration is captured; component implementation is not yet linked.')
        if match.output_type != 'ui_control':
            continue
        start,end = span(unit.source,match)
        if not owns(unit,start,end):
            continue
        eid = evidence(unit.source,start,end)
        control_id = identifier('ui_element',unit.anchor_id,start,end)
        result['elements'][control_id] = record('UIElement',id=control_id,kind='control',
            parent_view_id=view_id,label=capture(match,metadata.get('label_var')),
            evidence_ids=[eid],routing_resolution='unresolved',resolution='resolved')
        controls.append((start,end,control_id))
    for match in unit.source.rule_outputs:
        metadata = match.attributes; kind = match.output_type
        if kind not in ('ui_event','ui_validation'):
            continue
        start,end = span(unit.source,match)
        parents = sorted((c for c in controls if c[0]<=start<end<=c[1]),key=lambda c:c[1]-c[0])
        if not parents and not metadata.get('attribute_event'):
            continue
        element_id = parents[0][2] if parents else view_id
        eid = evidence(unit.source,start,end)
        event_id = identifier('ui_event',unit.anchor_id,start,end)
        handler = capture(match,metadata.get('handler_var'))
        trigger = capture(match,metadata.get('trigger_var')) or metadata.get('trigger','unknown')
        if metadata.get('attribute_event'):
            attribute = re.fullmatch(
                r'''\s*\(([^)]+)\)\s*=\s*["']\s*([A-Za-z_$][\w$]*)\s*\([^"']*["']\s*''',
                match.text, re.DOTALL)
            if attribute:
                trigger, handler = attribute.groups()
        separator = metadata.get('handler_separator')
        receiver,name = (handler.rsplit(separator,1) if separator and handler and separator in handler else (None,handler))
        if receiver == metadata.get('implicit_receiver'):
            receiver = None
        targets = candidates(unit,receiver,name,[u for u in unit.source.units if u.name == name]) if handler else []
        target = targets[0] if len(targets)==1 else None
        result['events'][event_id] = record('UIEvent',id=event_id,element_id=element_id,
            trigger=trigger,
            handler_symbol_id=target.symbol_id if target else None,evidence_ids=[eid],
            resolution='resolved' if target else ('ambiguous' if targets else 'unresolved'),
            reason=None if target else 'Event registration is present; invocation behavior is not fully resolved.')
        if kind == 'ui_validation':
            validation_id = identifier('ui_validation',event_id)
            result['validations'][validation_id] = record('UIValidation',id=validation_id,event_id=event_id,
                predicate_evidence_ids=[eid],enforcement=metadata['enforcement'],evidence_ids=[eid],
                rule_observation_id=next((o['id'] for o in facts['rule_observations'].values() if eid in o['evidence_ids']),None),
                resolution='unresolved',reason='Declared constraint; submission path and bypass conditions require tracing.')
    traced_symbols = {sid for trace in facts['traces'].values() if trace['anchor_id']==unit.anchor_id
                      for sid in trace['symbol_ids']}
    bindings = [v for v in facts['bindings'].values() if v['source']
                and v['source']['kind'] == 'symbol'
                and v['source']['id'] in traced_symbols]
    result['binding_ids'] = [v['id'] for v in bindings]
    hydrate_ui_calls(unit, facts, result, traced_symbols)
    for binding in bindings:
        if binding['direction'] == 'output':
            oid = identifier('ui_output',unit.anchor_id,binding['id'])
            result['outputs'][oid] = record('UIOutput',id=oid,kind='render',target_ref={'kind':'ui_element','id':view_id},
                binding_ids=[binding['id']],evidence_ids=binding['evidence_ids'],resolution=binding['resolution'],reason=binding['reason'])
    return result
