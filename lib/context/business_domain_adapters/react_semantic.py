"""React-only enrichment over normalized TSX rule outputs."""
from __future__ import annotations

from . import rules


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
