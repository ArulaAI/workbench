"""React-only enrichment over normalized TSX rule outputs."""
from __future__ import annotations

import re

from . import rules, ts_semantic


PREPARE_PHASE = 75
_RUNTIME_CALLS = frozenset({
    'createContext', 'createElement', 'forwardRef', 'lazy', 'memo',
    'useCallback', 'useContext', 'useEffect', 'useMemo', 'useReducer',
    'useRef', 'useState',
})


def _owner(source, start, end):
    return min((unit for unit in source.units
                if unit.start <= start < end <= unit.end),
               key=lambda unit: unit.end - unit.start, default=None)


def _component_for(source, start, end, markers):
    enclosing = [(left, right) for left, right in markers
                 if left <= start < end <= right]
    if not enclosing:
        return None
    left, right = min(enclosing, key=lambda item: item[1] - item[0])
    unit = next((candidate for candidate in source.units
                 if candidate.start == left and candidate.end == right), None)
    return unit.name if unit else None


def prepare(sources, units, diagnostics=None):
    for source in sources:
        markers = [rules.span(source, match) for match in source.rule_outputs
                   if match.output_type == 'component_marker'
                   and match.attributes.get('framework') == 'react']
        boundaries = getattr(source, 'framework_call_boundaries', {})
        enrichments = getattr(source, 'ui_enrichments', [])
        imports = rules._import_bindings(source)
        setters = {}
        state_matches = []
        transition_matches = []
        for match in source.rule_outputs:
            if match.attributes.get('framework') != 'react':
                continue
            if match.output_type == 'ui_state':
                state_matches.append(match)
            elif match.output_type == 'ui_transition':
                transition_matches.append(match)
        for match in state_matches:
            start, end = rules.span(source, match)
            owner = _owner(source, start, end)
            component = _component_for(source, start, end, markers)
            label = rules.capture(match, match.attributes.get('name_var')) or 'React component state'
            setter = rules.capture(match, match.attributes.get('setter_var'))
            if setter and owner:
                setters[setter] = (component or owner.name, label)
            if owner:
                enrichments.append({'kind':'state', 'owner':owner,
                    'component':component or owner.name, 'label':label,
                    'start':start, 'end':end})
        for match in transition_matches:
            start, end = rules.span(source, match)
            owner = _owner(source, start, end)
            component = _component_for(source, start, end, markers)
            target = rules.capture(match, match.attributes.get('target_var'))
            hook = setters.get(target)
            if owner and (component or hook):
                enrichments.append({'kind':'transition', 'owner':owner,
                    'component':component or hook[0],
                    'label':hook[1] if hook else 'React component state',
                    'start':start, 'end':end})
        for reference in source.references:
            if reference.kind != 'call' or not reference.callee_name:
                continue
            start, end = rules.span(source, {'range':reference.source_range})
            component = _component_for(source, start, end, markers)
            react_owned = (reference.callee_name == 'setState'
                           and (reference.name or '').startswith('this.') and component)
            imported_runtime = (reference.callee_name in _RUNTIME_CALLS
                and ((reference.receiver is None
                      and imports.get(reference.callee_name) == 'react')
                     or (reference.receiver == 'React'
                         and imports.get('React') == 'react')))
            if react_owned or imported_runtime:
                boundaries[(start, reference.callee_name)] = ('react',
                    f'{reference.callee_name} is provided by the evidenced React runtime.')
        source.framework_call_boundaries = boundaries
        source.ui_enrichments = enrichments
    routes = [unit for unit in units
              if getattr(unit, 'anchor_registration_kind', None) == 'route' and unit.route]
    for source in sources:
        _navigation_relations(source, routes)


# React Router navigation
#
# ``router.push(location)`` and ``router.replace(location)`` make the router
# activate the route matching the new location. A component that issues them
# through the router React Router puts in its context (an import of
# react-router and a ``contextTypes`` entry for ``router``) is linked to what
# that activation runs: the route's own registration, or, when the route is
# the one rendering the navigating component, that component's
# ``componentWillReceiveProps``, since it stays mounted and receives the new
# location as props. Routes are tried in declaration order and the first that
# matches wins, so a later route never answers for an earlier one; a runtime
# path segment that could equal an earlier literal keeps every such route as a
# candidate rather than picking one.

_NAVIGATIONS = frozenset({'push', 'replace'})
_CONTEXT_ROUTER = re.compile(r'\bcontextTypes\s*=\s*\{[^}]*\brouter\s*:')


def _route_segment(written, route):
    """'definite', 'possible' or None for one path segment against a route's."""
    if re.fullmatch(r':[\w$]+', route):
        return 'definite'
    if any(mark in route for mark in '*()'):
        return 'possible'
    if '{' in written:
        return 'possible'
    return 'definite' if written == route else None


def _route_match(segments, route):
    if route.strip() in {'*', '/*'}:
        return 'definite'
    if not route.startswith('/'):
        # A relative child route depends on its parent's path, which this
        # matcher does not compose; it can only ever be a candidate.
        return 'possible'
    pattern = [item for item in route.split('/') if item]
    if len(pattern) != len(segments):
        return 'possible' if any('*' in item or '(' in item for item in pattern) else None
    results = [_route_segment(written, expected)
               for written, expected in zip(segments, pattern)]
    if None in results:
        return None
    return 'possible' if 'possible' in results else 'definite'


def _matching_routes(path, routes):
    """Routes the router can activate for a path, in declaration order."""
    query = re.search(r'[?#]', re.sub(r'\{[^{}]*\}', lambda found: '_' * len(found.group(0)), path))
    segments = [item for item in (path[:query.start()] if query else path).split('/') if item]
    by_file = {}
    for route in sorted(routes, key=lambda unit: (unit.source.path, unit.start)):
        by_file.setdefault(route.source.path, []).append(route)
    matched = []
    for ordered in by_file.values():
        for route in ordered:
            result = _route_match(segments, route.route)
            if result:
                matched.append((route, result))
            if result == 'definite':
                break
    return matched


def _router_evidence(source, owner):
    """The class's ``contextTypes`` router entry, when React Router supplies it."""
    if 'react-router' not in rules._import_bindings(source).values() or owner is None:
        return None
    classes = [unit for unit in source.units if unit.kind == 'class' and unit.name == owner]
    if len(classes) != 1:
        return None
    found = _CONTEXT_ROUTER.search(classes[0].text)
    return (source, classes[0].start + found.start(), classes[0].start + found.end()) if found else None


def _navigation_path(scope, call, start):
    """The path values of a navigation call's location argument."""
    opening = call.find('(')
    closing = ts_semantic._close(call, opening)
    pieces = ts_semantic._split(call[opening + 1:closing], ',')
    location, at = ts_semantic._strip(pieces[0][0], start + opening + 1 + pieces[0][1])
    if location.startswith('{') and ts_semantic._close(location, 0) == len(location) - 1:
        for entry, offset in ts_semantic._split(location[1:-1], ','):
            entry, entry_at = ts_semantic._strip(entry, at + 1 + offset)
            key = re.match(r'''(?:(["'])pathname\1|pathname)\s*:''', entry)
            if key:
                return ts_semantic._evaluate(scope, entry[key.end():], entry_at + key.end())
        return []
    return ts_semantic._evaluate(scope, location, at)


def _navigation_target(unit, route, routes):
    """What activating a route runs, seen from the navigating unit."""
    component = getattr(route, 'anchor_context_unit', None)
    rendering = [item for item in routes
                 if getattr(item, 'anchor_context_unit', None) is not None
                 and item.anchor_context_unit.source is unit.source
                 and item.anchor_context_unit.owner == unit.owner]
    if (component is not None and unit.owner and component.source is unit.source
            and component.owner == unit.owner and len(rendering) == 1
            and rendering[0] is route):
        receiving = [item for item in unit.source.units
                     if item.owner == unit.owner and item.name == 'componentWillReceiveProps'
                     and item.executable_body]
        return receiving[0] if len(receiving) == 1 else component
    return route


def _navigation_relations(source, routes):
    for reference in source.references:
        if (reference.kind != 'call' or reference.callee_name not in _NAVIGATIONS
                or not re.fullmatch(r'this\.context\.router', reference.receiver or '')):
            continue
        start, end = rules.span(source, {'range': reference.source_range})
        unit = min((item for item in source.units
                    if item.kind in {'function', 'method'} and item.start <= start < end <= item.end),
                   key=lambda item: item.end - item.start, default=None)
        if unit is None:
            continue
        router = _router_evidence(source, unit.owner)
        if router is None:
            continue
        scope = ts_semantic._Scope(unit, None, ts_semantic._parameters(unit), 0)
        call = source.text[start:end]
        for value in _navigation_path(scope, call, start):
            path, _ = ts_semantic._rendered(value.parts)
            if path is None or any(part[0] == 'param' for part in value.parts):
                continue
            matched = [(route, result) for route, result in _matching_routes(path, routes)
                       if route.source.service_scope == source.service_scope]
            definite = [route for route, result in matched if result == 'definite']
            spans = [router, *value.spans] + [(route.source, route.start, route.end)
                                              for route, _ in matched]
            relation = {'source': unit, 'kind': 'navigates_to', 'start': start, 'end': end,
                        'evidence_spans': ts_semantic._unique(spans)}
            if len(matched) == 1 and definite:
                target = _navigation_target(unit, definite[0], routes)
                relation.update(target=target, resolution='resolved', reason=None)
            elif len(matched) > 1:
                relation.update(target=None, resolution='ambiguous', outcome='ambiguous',
                    candidate_targets=[route for route, _ in matched],
                    diagnostic_code='UI_NAVIGATION_TARGET_AMBIGUOUS',
                    reason=(f'Navigation to {path} can activate '
                            + ', '.join(route.route for route, _ in matched)
                            + ': a runtime path segment could equal a literal one.'))
            else:
                relation.update(target=None, resolution='unresolved', outcome='unresolved',
                    diagnostic_code='UI_NAVIGATION_TARGET_UNRESOLVED',
                    reason=(f'Navigation to {path} matches no registered route.' if not matched
                            else f'Navigation to {path} activates {matched[0][0].route} only '
                                 'if a runtime path segment equals a literal one.'))
            source.normalized_relations = getattr(source, 'normalized_relations', [])
            source.normalized_relations.append(relation)
