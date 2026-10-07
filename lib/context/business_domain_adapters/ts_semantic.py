"""TypeScript and JavaScript semantics over the shared declarative reader.

The rules adapter remains the single owner of declarations, references,
routes, bindings, operations, and base UI records.  This adapter adds the
language-specific boundary decisions that require JavaScript module meaning.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from types import MappingProxyType

from . import CATALOG, rules
from .base import SemanticResult
from ..layer1_domain_clustering import resolve_typescript_path_alias
from ..business_domain_schema import identifier, record


PREPARE_PHASE = 50


def extract(source):
    return rules.extract(source)


def _modules(source):
    return sorted({
        (reference.module or '').strip('\'"')
        for reference in source.references
        if reference.module
    })


def activation_evidence(source):
    """Expose normalized imports; this never searches source text."""
    return {'imports': _modules(source)}


def _external_import_boundaries(source):
    bindings = rules._import_bindings(source)
    boundaries = {}
    for reference in source.references:
        if reference.kind != 'call' or not reference.callee_name:
            continue
        root = rules._receiver_root(reference)
        module = bindings.get(root)
        if not module or module.startswith(('.', '/')):
            continue
        target = source.resolved_module_targets.get(module)
        if target is not None and target['state'] in {'resolved', 'ambiguous'}:
            continue
        start, _ = rules.span(source, {'range': reference.source_range})
        if (start, reference.callee_name) in getattr(
                source, 'resolved_call_targets', {}):
            continue
        boundaries[(start, reference.callee_name)] = (module,
            f'{reference.callee_name} is reached through {root}, imported '
            f'from external module {module}.')
    return boundaries


def prepare(sources, units, diagnostics=None):
    # Path aliases resolve against the configuration the supporting consumer
    # chose for each source; no alias match leaves the import as it was.
    source_paths = tuple(sorted(source.path for source in sources))
    for source in sources:
        selected = source.supporting_inputs.get(
            'typescript_module_resolution', {})
        tsconfig = selected.get('tsconfig', {})
        typings = selected.get('typings', {})
        aliases = tsconfig.get('aliases', ())
        external = {item['name']
            for item in typings.get('declared_external_modules', ())}
        resolved = {}
        for module in _modules(source):
            # TypeScript applies ``paths`` to bare specifiers only.
            if module.startswith(('.', '/')):
                continue
            result = resolve_typescript_path_alias(
                module, tsconfig.get('scope_dir', '.'), aliases, source_paths)
            if result['state'] == 'unmatched':
                if module not in external:
                    continue
                state = 'external'
            else:
                state = result['state']
            if state == 'unresolved' and module in external:
                state = 'external'
            resolved[module] = MappingProxyType({
                'state': state,
                'candidate_source_paths': tuple(result['candidates']),
                'external': state == 'external',
            })
        source.resolved_module_targets = MappingProxyType(resolved)
    rules.prepare(sources, units, diagnostics)
    _prepare_prop_callbacks(sources)
    definitions = _build_definitions(sources)
    for source in sources:
        source.external_import_boundaries = _external_import_boundaries(source)
        source.build_definitions = definitions
    return _prepare_action_labels(sources, units) or None


def calls(unit):
    """Avoid a duplicate call edge for a call already modeled as an effect."""
    effects = set()
    for match in unit.source.rule_outputs:
        if match.output_type != 'semantic_effect':
            continue
        start, end = rules.span(unit.source, match)
        if rules.owns(unit, start, end):
            effects.add((start - unit.start, end - unit.start))
    return [call for call in rules.calls(unit)
            if (call['position'], call['end']) not in effects]


# Callback props. A function component that destructures a prop such as
# ``onChange`` and calls it receives the handler each JSX usage passes. The
# handlers are only known when every usage is visible and passes a named
# function; a spread, an inline function, a missing prop or any use of the
# component other than as a JSX tag leaves the call unresolved. Test sources
# are ignored, so a test double cannot widen a production callback.

_DESTRUCTURED_PROPS = re.compile(
    r'\A\s*(?:export\s+default\s+)?(?:function\s*[\w$]*\s*)?\(\s*\{([^{}]*)\}')
_HANDLER = re.compile(r'(?:this\.)?([A-Za-z_$][\w$]*)')
_SCRIPT_SUFFIXES = ('', '.tsx', '.ts', '.jsx', '.js',
                    '/index.tsx', '/index.ts', '/index.jsx', '/index.js')


def _destructured_props(component):
    """Local names of the props a function component destructures."""
    found = _DESTRUCTURED_PROPS.match(component.text)
    if not found:
        return {}
    props = {}
    for part in found.group(1).split(','):
        declared = part.split('=', 1)[0].strip()
        if not declared or declared.startswith('...'):
            continue
        prop, _, local = declared.partition(':')
        props[(local or prop).strip()] = prop.strip()
    return props


def _opening_tag(text):
    """The opening tag of a JSX element, without its children."""
    depth, quote = 0, None
    for index, character in enumerate(text):
        if quote:
            quote = None if character == quote else quote
        elif character in '"\'`':
            quote = character
        elif character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
        elif character == '>' and depth == 0:
            return text[:index + 1]
    return text


def _attribute(tag, prop):
    """The expression the element's own attribute passes, or None when absent.

    Only the tag's top level counts: a JSX element nested inside another
    attribute's expression carries its own props.
    """
    depth, quote = 0, None
    pattern = re.compile(rf'(?<![\w$-]){re.escape(prop)}\s*=\s*\{{')
    for index, character in enumerate(tag):
        if quote:
            quote = None if character == quote else quote
        elif character in '"\'`':
            quote = character
        elif character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
        elif depth == 0 and (found := pattern.match(tag, index)) and (
                index == 0 or not re.match(r'[\w$-]', tag[index - 1])):
            nested, start = 1, found.end()
            for end in range(start, len(tag)):
                nested += {'{': 1, '}': -1}.get(tag[end], 0)
                if nested == 0:
                    return tag[start:end].strip()
            return None
    return None


def _handler(origin, expression):
    """The one unit a handler expression names in its rendering scope, or None."""
    if not expression or not _HANDLER.fullmatch(expression):
        return None
    name = _HANDLER.fullmatch(expression).group(1)
    own = expression.startswith('this.')
    if not own and name in rules._import_bindings(origin.source):
        return None
    # ``this.x`` is a member of the rendering class; a bare name is a binding
    # in module scope, never a class method.
    found = [unit for unit in origin.source.units
             if unit.name == name and unit is not origin
             and (unit.owner == origin.owner if own else unit.owner is None)]
    return found[0] if len(found) == 1 else None


def _only_rendered(component, sources):
    """True when every reference to *component* in *sources* is a JSX tag."""
    target = component.source.path
    for source in sources:
        if _is_test(source):
            continue
        directory = posixpath.dirname(source.path)
        aliases = [alias for alias, module in rules._import_bindings(source).items()
                   if module.startswith('.') and any(
                       posixpath.normpath(posixpath.join(directory, module)) + suffix == target
                       for suffix in _SCRIPT_SUFFIXES)]
        for alias in aliases:
            text = '\n'.join(line for line in source.text.splitlines()
                             if not re.match(r'\s*import\b', line))
            uses = len(re.findall(rf'(?<![\w$.]){re.escape(alias)}(?![\w$])', text))
            tags = len(re.findall(rf'</?{re.escape(alias)}(?![\w$])', text))
            if uses != tags:
                return False
    return True


def _is_test(source):
    return bool(re.search(CATALOG['test_path_pattern'], source.path))


def _prepare_prop_callbacks(sources):
    for source in sources:
        for component in source.units:
            usages = [usage for usage in getattr(component, 'jsx_usages', None) or ()
                      if not _is_test(usage[0].source)]
            props = _destructured_props(component) if usages else {}
            if not props or not _only_rendered(component, sources):
                continue
            targets = {}
            for local, prop in props.items():
                handlers = []
                for origin, start, end in usages:
                    tag = _opening_tag(origin.source.text[start:end])
                    if re.search(r'\{\s*\.\.\.', tag):
                        handlers = None
                        break
                    handler = _handler(origin, _attribute(tag, prop))
                    if handler is None:
                        handlers = None
                        break
                    if handler not in handlers:
                        handlers.append(handler)
                if handlers:
                    targets[local] = tuple(handlers)
            component.prop_callback_targets = targets


def _prop_callback(unit, receiver, name):
    """Handlers a call to a destructured callback prop reaches, or None."""
    if receiver:
        return None
    components = sorted((candidate for candidate in unit.source.units
                         if getattr(candidate, 'prop_callback_targets', None)
                         and candidate.start <= unit.start and unit.end <= candidate.end),
                        key=lambda candidate: candidate.end - candidate.start)
    if not components or name not in components[0].prop_callback_targets:
        return None
    component = components[0]
    # A local declaration of the same name between the call and the component
    # shadows the prop.
    body = component.text[_DESTRUCTURED_PROPS.match(component.text).end():]
    escaped = re.escape(name)
    shadowing = (rf'\b(?:const|let|var)\s+[^=;]*(?<![\w$.]){escaped}(?![\w$])[^=;]*=',
                 rf'\bfunction\s+{escaped}\b',
                 rf'(?<![\w$.]){escaped}\s*=>',
                 rf'\([^()]*(?<![\w$.]){escaped}(?![\w$])[^()]*\)\s*=>')
    if any(re.search(pattern, body) for pattern in shadowing) or any(
            name == parameter for scope in unit.source.units
            if component.start < scope.start and scope.start <= unit.start
            and unit.end <= scope.end for parameter, _ in scope.params):
        return None
    return list(component.prop_callback_targets[name])


def candidates(unit, receiver, name, available, position=None):
    lexical = rules.lexical_candidates(unit, receiver, name, available)
    if lexical:
        return lexical
    bindings = rules._import_bindings(unit.source)
    bound = receiver.split('.', 1)[0] if receiver else name
    module = bindings.get(bound)
    target = unit.source.resolved_module_targets.get(module)
    if target is None:
        found = rules.candidates(unit, receiver, name, available, position)
        return found or _prop_callback(unit, receiver, name) or []
    if target['state'] in {'resolved', 'ambiguous'}:
        paths = set(target['candidate_source_paths'])
        return sorted((candidate for candidate in available
            if candidate.source.path in paths),
            key=lambda candidate: candidate.qualified)
    if target['state'] == 'external':
        return []
    # An alias matched but named no local file: TypeScript falls back to
    # ordinary resolution, so the alias proves nothing either way.
    return rules.candidates(unit, receiver, name, available, position)


def resolve_call(unit, receiver, name, candidates, position, evidence_id=None):
    evidence = (evidence_id or unit.evidence_id,)
    boundary = getattr(unit.source, 'framework_call_boundaries', {}).get(
        (unit.start + position, name))
    code = 'JS_EXTERNAL_CALL'
    if not boundary:
        boundary = getattr(unit.source, 'external_import_boundaries', {}).get(
            (unit.start + position, name))
    if boundary and not candidates:
        owner, reason, *provider = boundary
        return SemanticResult(capability='callable_resolution', outcome='external',
            subject_id=unit.symbol_id,
            target_id=identifier('resource', 'javascript-external-call', owner, name),
            evidence_ids=evidence, diagnostic_code=code, reason=reason,
            provider=provider[0] if provider else f'module:{owner}')
    return rules.resolve_call(unit, receiver, name, candidates, position, evidence_id)


def _enriched_interaction(unit, evidence, facts, result):
    if not result:
        return result
    traced = {sid for trace in facts['traces'].values()
              if trace['anchor_id'] == unit.anchor_id for sid in trace['symbol_ids']}
    events = {event['handler_symbol_id']: event['id']
              for event in result['events'].values() if event['handler_symbol_id']}
    states = {}
    additions = getattr(unit.source, 'ui_enrichments', [])
    context = getattr(unit, 'anchor_context_unit', None) or unit
    components = {context.name, context.owner}
    for item in additions:
        if item['component'] not in components or item['kind'] != 'state':
            continue
        eid = evidence(unit.source, item['start'], item['end'])
        sid = identifier('ui_state', unit.anchor_id, item['component'], item['label'])
        states[(item['component'], item['label'])] = sid
        result['states'][sid] = record('UIState', id=sid, label=item['label'],
            render_evidence_ids=[eid], evidence_ids=[eid], resolution='resolved', reason=None)
    for item in additions:
        owner_symbol_id = item['owner'].symbol_id
        if owner_symbol_id not in traced or item['kind'] != 'transition':
            continue
        event_id = events.get(owner_symbol_id)
        state_id = states.get((item['component'], item['label']))
        if not event_id or not state_id:
            continue
        eid = evidence(unit.source, item['start'], item['end'])
        tid = identifier('ui_transition', unit.anchor_id, event_id, item['start'])
        result['transitions'][tid] = record('UITransition', id=tid,
            from_state_id=state_id, event_id=event_id, guard_evidence_ids=[],
            to_state_id=state_id, call_ids=[], output_ids=[], evidence_ids=[eid],
            resolution='resolved', reason=None)
    return result


def interaction(unit, evidence, facts):
    return _enriched_interaction(unit, evidence, facts,
                                 rules.interaction(unit, evidence, facts))


def bindings(unit):
    return rules.bindings(unit)


def resources(unit):
    return rules.resources(unit)


def observations(unit):
    return rules.observations(unit)


def operations(unit):
    result = rules.operations(unit)
    occupied = {(item['position'], item['end']) for item in result}
    for match in getattr(unit.source, 'framework_operations', []):
        start, end = rules.span(unit.source, match)
        relative = (start-unit.start, end-unit.start)
        if rules.owns(unit, start, end) and relative not in occupied:
            method = rules.capture(match, match.attributes.get('method_var'))
            result.append(rules.http_operation(unit, match, {
                'effect_kind': 'external_action', 'resource_kind': 'service',
                'protocol': 'http',
                'method': method.upper() if method else None,
                'target_var': match.attributes['target_var'],
            }))
    return result


def relations(source):
    return rules.relations(source)


def symbol_key(name):
    return name


# HTTP endpoint requests
#
# The core links a client request to the server endpoint that answers it, so it
# needs each request as the source composes it: the method, and the URL the call
# really builds, base included. JavaScript decides both, so they are evaluated
# here, from literals, templates, concatenation, conditional choices, constants,
# wrapper functions such as ``url(path)``, build-time globals a bundler defines,
# and the arguments a helper such as ``submitForm(method, path)`` receives at
# each of its call sites. Anything else stays unknown and carries its reason.

_IDENTIFIER = r'[A-Za-z_$][\w$]*'
_NAME = re.compile(rf'{_IDENTIFIER}(?:\.{_IDENTIFIER})*')
_CALL = re.compile(rf'({_IDENTIFIER})\s*\(')
_DEFINE_PLUGIN = re.compile(r'\bDefinePlugin\s*\(\s*\{')
_MAX_ALTERNATIVES = 32
_MAX_CALL_DEPTH = 4


def _skip_comment(text, index):
    """Index past a comment starting at index, or index itself."""
    if text.startswith('//', index):
        end = text.find('\n', index)
        return len(text) if end < 0 else end
    if text.startswith('/*', index):
        end = text.find('*/', index + 2)
        return len(text) if end < 0 else end + 2
    return index


def _skip_literal(text, index):
    """Index just past the string or template literal opening at index."""
    quote = text[index]
    cursor = index + 1
    while cursor < len(text):
        character = text[cursor]
        if character == '\\':
            cursor += 2
        elif character == quote:
            return cursor + 1
        elif quote == '`' and text.startswith('${', cursor):
            cursor = _close(text, cursor + 1) + 1
        else:
            cursor += 1
    return len(text)


def _scan(text, start=0):
    """Yield (index, character, depth) outside comments and literals."""
    depth = 0
    cursor = start
    while cursor < len(text):
        skipped = _skip_comment(text, cursor)
        if skipped != cursor:
            cursor = skipped
            continue
        character = text[cursor]
        if character in '\'"`':
            cursor = _skip_literal(text, cursor)
            continue
        if character in ')]}':
            depth -= 1
        yield cursor, character, depth
        if character in '([{':
            depth += 1
        cursor += 1


def _close(text, index):
    """Index of the bracket closing the one opening at index."""
    for cursor, character, depth in _scan(text, index):
        if depth == 0 and character in ')]}' and cursor > index:
            return cursor
    return len(text)


def _top_level(text):
    return [(index, character) for index, character, depth in _scan(text)
            if depth == 0 and character not in '([{)]}']


def _split(text, separator):
    """Top-level pieces of text, each with its offset."""
    pieces, start = [], 0
    for index, character in _top_level(text):
        if character == separator:
            pieces.append((text[start:index], start))
            start = index + 1
    pieces.append((text[start:], start))
    return pieces


def _strip(text, start):
    return text.strip(), start + len(text) - len(text.lstrip())


def _statement_end(text, start):
    """End of the expression statement whose value starts at start."""
    for index, character, depth in _scan(text, start):
        if depth < 0 or (depth == 0 and character == ';'):
            return index
        if depth == 0 and character == '\n':
            before = text[start:index].rstrip()
            after = text[index:].lstrip()
            if (before and before[-1] not in '+-*/%?:=,(&|'
                    and not (after[:1] and after[0] in '+-*/%?:.=,)&|')):
                return index
    return len(text)


def _concatenation(text):
    """Top-level binary ``+`` operands of text, with their offsets."""
    cuts = []
    for index, character in _top_level(text):
        if character != '+' or text[index + 1:index + 2] in ('+', '=') \
                or text[index - 1:index] == '+':
            continue
        before = text[:index].rstrip()
        if before and before[-1] not in '=(,?:!&|+-*/%<>[{':
            cuts.append(index)
    pieces, start = [], 0
    for cut in cuts:
        pieces.append((text[start:cut], start))
        start = cut + 1
    pieces.append((text[start:], start))
    return pieces


def _conditional(text):
    """The test and both branches of a top-level ``a ? b : c``, or None."""
    marks = [(index, character) for index, character in _top_level(text)
             if character in '?:']

    def question(index):
        return (text[index] == '?' and text[index + 1:index + 2] not in ('.', '?')
                and text[index - 1:index] != '?')

    first = next((position for position, (index, _) in enumerate(marks)
                  if question(index)), None)
    if first is None:
        return None
    nested = 0
    opening = marks[first][0]
    for index, character in marks[first + 1:]:
        if question(index):
            nested += 1
        elif character == ':':
            if nested == 0:
                return ((text[:opening], 0), (text[opening + 1:index], opening + 1),
                        (text[index + 1:], index + 1))
            nested -= 1
    return None


def _string(text):
    if len(text) >= 2 and text[0] in '\'"' and _skip_literal(text, 0) == len(text):
        return re.sub(r'\\(.)', r'\1', text[1:-1])
    return None


def _template(text):
    """Literal and expression parts of a whole template literal, or None."""
    if len(text) < 2 or text[0] != '`' or _skip_literal(text, 0) != len(text):
        return None
    parts, literal, cursor = [], [], 1
    while cursor < len(text) - 1:
        if text[cursor] == '\\':
            literal.append(text[cursor + 1:cursor + 2])
            cursor += 2
        elif text.startswith('${', cursor):
            end = _close(text, cursor + 1)
            if literal:
                parts.append(('lit', ''.join(literal), None))
                literal = []
            parts.append(('expr', text[cursor + 2:end], cursor + 2))
            cursor = end + 1
        else:
            literal.append(text[cursor])
            cursor += 1
    if literal:
        parts.append(('lit', ''.join(literal), None))
    return parts


@dataclass(frozen=True)
class _Value:
    """One value an expression can take.

    ``parts`` is a sequence of ``('lit', text)``, ``('var', expression)`` (a
    runtime value spliced into a string), ``('param', name)`` (decided by the
    caller) and ``('unknown', reason)``. ``conditions`` are the branch choices
    that select it, as ``(test, taken)`` pairs, and ``spans`` its evidence.
    """
    parts: tuple
    conditions: tuple = ()
    spans: tuple = ()


def _unique(spans):
    seen, result = set(), []
    for span in spans:
        key = (id(span[0]), span[1], span[2])
        if key not in seen and span[1] < span[2]:
            seen.add(key)
            result.append(span)
    return tuple(result)


def _value(parts, spans=(), conditions=()):
    merged = []
    for part in parts:
        if merged and part[0] == 'lit' and merged[-1][0] == 'lit':
            merged[-1] = ('lit', merged[-1][1] + part[1])
        else:
            merged.append(part)
    return _Value(tuple(merged), tuple(conditions), _unique(spans))


def _unknown(reason, span=None):
    return _Value((('unknown', reason),), (), _unique((span,)) if span else ())


def _join(left, right):
    """Concatenate two values, or None when their branch choices contradict."""
    conditions = dict(left.conditions)
    for test, taken in right.conditions:
        if conditions.get(test, taken) != taken:
            return None
        conditions[test] = taken
    return _value(left.parts + right.parts, left.spans + right.spans,
                  tuple(conditions.items()))


def _product(lefts, rights):
    joined = [value for left in lefts for right in rights
              if (value := _join(left, right)) is not None]
    if len(joined) > _MAX_ALTERNATIVES:
        return [_unknown('The expression has too many alternative values to evaluate.')]
    return joined


def _extend(values, span=None, condition=None):
    addition = _Value((), (condition,) if condition else (), (span,) if span else ())
    return [value for value in (_join(item, addition) for item in values)
            if value is not None]


@dataclass
class _Scope:
    unit: object
    env: dict | None
    params: tuple
    depth: int


def _parameters(unit):
    shape = _function_shape(unit)
    return tuple(name for name in shape[0] if name) if shape else ()


def _function_shape(unit):
    """Parameter names, returned expression and its offset, or None."""
    if unit.kind not in {'function', 'method'}:
        return None
    text = unit.text
    opening = text.find('(')
    if opening < 0:
        return None
    closing = _close(text, opening)
    inner = text[opening + 1:closing]
    params = []
    for piece, _ in (_split(inner, ',') if inner.strip() else []):
        piece = piece.strip()
        if piece.startswith('...'):
            piece = piece[3:]
        name = re.match(_IDENTIFIER, piece)
        params.append(name.group(0) if name and piece[:1] not in '{[' else None)
    head = re.compile(r'\s*(?::[^{=]*?)?\s*(=>|\{)').match(text, closing + 1)
    if not head:
        return params, None, None
    if head.group(1) == '=>':
        body, at = _strip(text[head.end():], head.end())
        if not body.startswith('{'):
            return params, body.rstrip(';').rstrip(), unit.start + at
        block = head.end() + text[head.end():].index('{')
    else:
        block = head.end() - 1
    inner_end = _close(text, block)
    top = {index for index, _ in _top_level(text[block + 1:inner_end])}
    returns = [found for found in re.finditer(r'\breturn\b', text[block + 1:inner_end])
               if found.start() in top]
    if len(returns) != 1:
        return params, None, None
    at = block + 1 + returns[0].end()
    end = _statement_end(text, at)
    body, at = _strip(text[at:end], at)
    return params, body, unit.start + at


def _call_target(source, name, start):
    return getattr(source, 'resolved_call_targets', {}).get((start, name))


def _constant(unit, name, before):
    """The last ``const name = ...`` in the unit before an offset."""
    text = unit.source.text
    found = list(re.finditer(rf'\bconst\s+{re.escape(name)}\b(?:\s*:[^=;]+)?\s*=(?!=)',
                             text[unit.start:before]))
    if not found:
        return None
    at = unit.start + found[-1].end()
    end = _statement_end(text, at)
    return text[at:end], at, (unit.start + found[-1].start(), end)


def _module_constant(source, name):
    found = re.search(rf'(?m)^(?:export\s+)?const\s+{re.escape(name)}\b(?:\s*:[^=;\n]+)?\s*=(?!=)',
                      source.text)
    if not found:
        return None
    end = _statement_end(source.text, found.end())
    return source.text[found.end():end], found.end(), (found.start(), end)


def _build_global(source, name):
    """Values a bundler defines for a declared build-time global, or None."""
    declared = re.search(rf'\bdeclare\s+(?:var|let|const)\s+{re.escape(name)}\b[^;\n]*',
                         source.text)
    if not declared:
        return None
    span = (source, declared.start(), declared.end())
    definitions = getattr(source, 'build_definitions', {}).get(
        (source.service_scope, name), [])
    if not definitions:
        return [_unknown(f'Build-time global {name} has no statically declared '
                         'definition.', span)]
    return [_value((('lit', value),), (span, (where, start, end)),
                   ((f"{name} = '{value}' ({where.path})", True),))
            for value, where, start, end in definitions]


def _build_global_test(source, test):
    """``(name, undefined_when_true)`` when *test* checks a declared build-time global."""
    found = re.fullmatch(r"typeof\s+([A-Za-z_$][\w$]*)\s*(===|!==|==|!=)\s*(['\"])undefined\3", test)
    if not found or not re.search(rf'\bdeclare\s+(?:var|let|const)\s+{re.escape(found.group(1))}\b',
                                  source.text):
        return None
    return found.group(1), found.group(2) in ('===', '==')


def _evaluate(scope, text, start):
    """Every value an expression can take."""
    text, start = _strip(text, start)
    source = scope.unit.source
    if not text:
        return [_unknown('The expression is empty.')]
    span = (source, start, start + len(text))
    if text[0] == '(' and _close(text, 0) == len(text) - 1:
        return _evaluate(scope, text[1:-1], start + 1)
    conditional = _conditional(text)
    if conditional:
        (test, _), (yes, yes_at), (no, no_at) = conditional
        test = ' '.join(test.split())
        build = _build_global_test(scope.unit.source, test)
        if build:
            # A build-time global's default branch is named by the value it
            # falls back to; its defined branch needs no condition of its own,
            # because each bundler definition states its value and file.
            name, undefined_first = build
            (default, default_at), (defined, defined_at) = (
                ((yes, yes_at), (no, no_at)) if undefined_first else ((no, no_at), (yes, yes_at)))
            labelled = []
            for value in _evaluate(scope, default, start + default_at):
                literal = (value.parts[0][1] if len(value.parts) == 1 and value.parts[0][0] == 'lit'
                           else None)
                label = (f"{name} is undefined at build time, so the source default "
                         f"'{literal}' ({scope.unit.source.path}) applies" if literal is not None
                         else f'{name} is undefined at build time')
                labelled.extend(_extend([value], span, (label, True)))
            values = labelled + _extend(_evaluate(scope, defined, start + defined_at), span)
            return values if len(values) <= _MAX_ALTERNATIVES else [
                _unknown('The expression has too many alternative values to evaluate.', span)]
        values = (_extend(_evaluate(scope, yes, start + yes_at), span, (test, True))
                  + _extend(_evaluate(scope, no, start + no_at), span, (test, False)))
        return values if len(values) <= _MAX_ALTERNATIVES else [
            _unknown('The expression has too many alternative values to evaluate.', span)]
    pieces = _concatenation(text)
    if len(pieces) > 1:
        values = [_value(())]
        for piece, at in pieces:
            values = _product(values, _embedded(scope, piece, start + at))
        return _extend(values, span)
    literal = _string(text)
    if literal is not None:
        return [_value((('lit', literal),), (span,))]
    template = _template(text)
    if template is not None:
        values = [_value(())]
        for kind, part, at in template:
            values = _product(values, [_value((('lit', part),))] if kind == 'lit'
                              else _embedded(scope, part, start + at))
        return _extend(values, span)
    call = _CALL.match(text)
    if call and _close(text, call.end() - 1) == len(text) - 1:
        return _evaluate_call(scope, call.group(1), text, start, call.end())
    if _NAME.fullmatch(text):
        return _evaluate_name(scope, text, start, span)
    return [_unknown(f'`{" ".join(text.split())}` is not a statically evaluable value.', span)]


def _embedded(scope, text, start):
    """A value spliced into a string: an unknown one is a runtime variable.

    A parameter spliced into a URL is a runtime value such as a path variable,
    so it stays a variable here. Only a parameter that is the whole method or
    destination is left to the caller to decide.
    """
    stripped, at = _strip(text, start)
    if stripped in scope.params and not (scope.env is not None and stripped in scope.env):
        return [_value((('var', stripped),), ((scope.unit.source, at, at + len(stripped)),))]
    values = _evaluate(scope, text, start)
    if any(part[0] == 'unknown' for value in values for part in value.parts):
        text, start = _strip(text, start)
        return [_value((('var', ' '.join(text.split())),),
                       ((scope.unit.source, start, start + len(text)),))]
    return values


def _evaluate_name(scope, name, start, span):
    source = scope.unit.source
    if '.' not in name:
        if scope.env is not None and name in scope.env:
            return _extend(scope.env[name], span)
        if name in scope.params:
            return [_value((('param', name),), (span,))]
        declaration = _constant(scope.unit, name, start)
        if declaration:
            text, at, declared = declaration
            return _extend(_evaluate(scope, text, at), (source, *declared))
        declaration = _module_constant(source, name)
        if declaration:
            text, at, declared = declaration
            module = _Scope(scope.unit, None, (), scope.depth)
            return _extend(_evaluate(module, text, at), (source, *declared))
        defined = _build_global(source, name)
        if defined is not None:
            return defined
    return [_unknown(f'`{name}` is not established by a literal, a constant or a '
                     'call-site argument.', span)]


def _arguments(scope, text, start, params):
    """Each parameter's values from a call's argument list text."""
    pieces = _split(text, ',') if text.strip() else []
    env = {}
    for index, param in enumerate(params):
        if param is None:
            continue
        if index < len(pieces):
            piece, at = pieces[index]
            env[param] = _evaluate(scope, piece, start + at)
        else:
            env[param] = [_unknown(f'Argument {param} is not supplied.')]
    return env


def _evaluate_call(scope, name, text, start, opening):
    source = scope.unit.source
    span = (source, start, start + len(text))
    target = _call_target(source, name, start)
    if target is None:
        return [_unknown(f'Call to {name} has no resolved source target.', span)]
    shape = _function_shape(target)
    if scope.depth >= _MAX_CALL_DEPTH or not shape or shape[1] is None:
        return [_unknown(f'{name} does not return one statically evaluable expression.', span)]
    params, body, body_at = shape
    env = _arguments(scope, text[opening:-1], start + opening, params)
    inner = _Scope(target, env, tuple(param for param in params if param), scope.depth + 1)
    return _extend(_extend(_evaluate(inner, body, body_at), span),
                   (target.source, target.start, target.end))


def _method_value(value):
    if any(part[0] in {'unknown', 'param'} for part in value.parts):
        return value
    written = ''.join(part[1] for part in value.parts if part[0] == 'lit')
    if any(part[0] == 'var' for part in value.parts) or not re.fullmatch(r'[A-Za-z]+', written):
        return _Value((('unknown', 'The HTTP method is not a literal token.'),),
                      value.conditions, value.spans)
    return _Value((('lit', written.upper()),), value.conditions, value.spans)


def _options_method(scope, text, start):
    """Methods a request options argument selects; GET when it names none."""
    text, start = _strip(text, start)
    source = scope.unit.source
    span = (source, start, start + len(text))
    if text.startswith('{') and _close(text, 0) == len(text) - 1:
        spread = False
        for entry, at in _split(text[1:-1], ','):
            entry, entry_at = _strip(entry, start + 1 + at)
            if entry.startswith('...'):
                spread = True
                continue
            key = re.match(r'''(?:(["'])(\w+)\1|(\w+))\s*(:)?''', entry)
            if not key or (key.group(2) or key.group(3)) != 'method':
                continue
            value, value_at = ((entry[key.end():], entry_at + key.end()) if key.group(4)
                               else (entry, entry_at))
            return [_method_value(item) for item in _evaluate(scope, value, value_at)]
        if spread:
            return [_unknown('Spread request options may supply the HTTP method.', span)]
        # The Fetch standard defaults a request without a method to GET.
        return [_value((('lit', 'GET'),), (span,))]
    if re.fullmatch(_IDENTIFIER, text) and text not in scope.params and not (
            scope.env is not None and text in scope.env):
        declaration = _constant(scope.unit, text, start)
        if declaration:
            init, at, declared = declaration
            return _extend(_options_method(scope, init, at), (source, *declared))
    return [_unknown('The request options are not a statically evaluable object.', span)]


def _http_matches(unit):
    source = unit.source
    found = []
    for match in source.rule_outputs:
        if match.output_type == 'semantic_effect' and match.attributes.get('protocol') == 'http':
            start, end = rules.span(source, match)
            if rules.owns(unit, start, end):
                found.append((match, match.attributes, start, end))
    for match in getattr(source, 'framework_operations', []):
        start, end = rules.span(source, match)
        if rules.owns(unit, start, end):
            found.append((match, match.attributes, start, end))
    return found


def _match_requests(scope, match, metadata, start, end):
    source = scope.unit.source
    target = rules.capture(match, metadata.get('target_var'))
    if not target or match.text.find(target) < 0:
        return []
    span = (source, start, end)
    urls = _evaluate(scope, target, start + match.text.find(target))
    if metadata.get('method'):
        methods = [_value((('lit', metadata['method'].upper()),), (span,))]
    elif metadata.get('method_var'):
        written = rules.capture(match, metadata['method_var'])
        methods = [_method_value(_value((('lit', written),), (span,)))] if written else [
            _unknown('The HTTP method is not captured at the call.', span)]
    else:
        options = rules.capture(match, metadata.get('request_var'))
        methods = (_options_method(scope, options, start + match.text.find(options))
                   if options and match.text.find(options) >= 0
                   else [_value((('lit', 'GET'),), (span,))])
    requests = []
    for method in methods:
        for url in urls:
            joined = _join(_Value((), method.conditions, method.spans),
                           _Value((), url.conditions, url.spans + (span,)))
            if joined is not None:
                requests.append({'method_parts': method.parts, 'url_parts': url.parts,
                                 'conditions': joined.conditions, 'spans': joined.spans})
    return requests[:_MAX_ALTERNATIVES]


def _parametric(request):
    return any(part[0] == 'param'
               for part in request['method_parts'] + request['url_parts'])


def _requests(unit, env=None, depth=0, stack=()):
    """Requests issued by a unit, its parameters bound by env when given.

    A request whose method or URL is a parameter is decided by the caller, so
    each call site re-evaluates the callee with that call's arguments; the
    result is attributed to the calling unit, never to the shared helper.

    Without bindings the result still depends on how deep the walk is and
    which callers it came through, so it is cached under that context: a unit
    first reached deep in another unit's walk keeps its full result for depth 0.
    """
    if env is None:
        cache = getattr(unit, '_endpoint_requests', None)
        if cache is None:
            cache = unit._endpoint_requests = {}
        if (depth, stack) in cache:
            return cache[(depth, stack)]
    source = unit.source
    scope = _Scope(unit, env, _parameters(unit), depth)
    results = []
    for match, metadata, start, end in _http_matches(unit):
        for request in _match_requests(scope, match, metadata, start, end):
            results.append({**request, 'position': start - unit.start,
                            'end': end - unit.start})
    if depth < _MAX_CALL_DEPTH:
        for reference in source.references:
            if reference.kind != 'call' or not reference.callee_name:
                continue
            start, end = rules.span(source, {'range': reference.source_range})
            if not rules.owns(unit, start, end):
                continue
            target = _call_target(source, reference.callee_name, start)
            if target is None or target is unit or id(target) in stack:
                continue
            # Only the requests the callee leaves to its caller are re-evaluated
            # here; the others are already the callee's own.
            deferred = {(request['position'], request['end'])
                        for request in _requests(target, None, depth + 1, stack + (id(unit),))
                        if _parametric(request)}
            if not deferred:
                continue
            call = source.text[start:end]
            named = call.find(reference.callee_name)
            opening = call.find('(', named + len(reference.callee_name)) if named >= 0 else -1
            shape = _function_shape(target)
            if opening < 0 or not shape:
                continue
            closing = _close(call, opening)
            target_env = _arguments(scope, call[opening + 1:closing], start + opening + 1,
                                    shape[0])
            for request in _requests(target, target_env, depth + 1, stack + (id(unit),)):
                if (request['position'], request['end']) not in deferred:
                    continue
                results.append({**request, 'spans': _unique(
                    request['spans'] + ((source, start, end),)),
                    'position': start - unit.start, 'end': end - unit.start})
    if env is None:
        cache[(depth, stack)] = results
    return results


def _rendered(parts):
    unknown = next((part[1] for part in parts if part[0] == 'unknown'), None)
    if unknown:
        return None, unknown
    return ''.join(part[1] if part[0] == 'lit' else '{' + part[1] + '}'
                   for part in parts), None


def endpoint_requests(unit):
    """The HTTP requests this unit issues, composed as its source builds them."""
    result, seen = [], set()
    for request in _requests(unit):
        if _parametric(request):
            continue
        method, method_reason = _rendered(request['method_parts'])
        url, url_reason = _rendered(request['url_parts'])
        spans = sorted(request['spans'], key=lambda span: (span[0].path, span[1], span[2]))
        item = {'position': request['position'], 'end': request['end'],
                'method': method.upper() if method else None, 'method_reason': method_reason,
                'url': url, 'url_reason': url_reason,
                'conditions': [list(condition) for condition in request['conditions']],
                'evidence_spans': spans}
        key = (item['position'], item['end'], method, url,
               tuple(request['conditions']))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _defined_value(text):
    """The string a DefinePlugin entry substitutes, when it is a literal."""
    text = text.strip()
    stringified = re.fullmatch(r'JSON\.stringify\(\s*(.*?)\s*\)', text, re.DOTALL)
    if stringified:
        return _string(stringified.group(1))
    code = _string(text)
    return _string(code.strip()) if code else None


def _build_definitions(sources):
    """Literal string values webpack DefinePlugin configurations assign."""
    index = {}
    for source in sources:
        for found in _DEFINE_PLUGIN.finditer(source.text):
            opening = found.end() - 1
            closing = _close(source.text, opening)
            for entry, at in _split(source.text[opening + 1:closing], ','):
                entry, entry_at = _strip(entry, opening + 1 + at)
                key = re.match(r'''(?:(["'])([\w$.]+)\1|([A-Za-z_$][\w$]*))\s*:\s*''', entry)
                value = _defined_value(entry[key.end():]) if key else None
                if value is not None:
                    index.setdefault((source.service_scope, key.group(2) or key.group(3)),
                                     []).append((value, source, entry_at, entry_at + len(entry)))
    return index


# Action labels
#
# A button whose text is a JSX expression is labelled only by the string
# literals that expression can produce: a literal, a conditional over
# literals, or a ``const`` assigned only such values. A choice between several
# literals is made per route, and only when the page on that route passes a
# literal value for every flag the choice tests: the prop itself, an object
# literal (directly, through a ``const`` or a function returning one) holding
# the flag, or an object literal without it, which leaves the flag undefined.
# A flag read from component state counts only when the constructor seeds that
# state from the prop, so the choice is the label the screen first renders.
# Any other value leaves every literal a candidate; an expression with a
# runtime part leaves the action explicitly unlabeled.

LABEL_RUNTIME_CODE = 'UI_ACTION_LABEL_RUNTIME'
LABEL_AMBIGUOUS_CODE = 'UI_ACTION_LABEL_AMBIGUOUS'
_MAX_LABEL_DEPTH = 4
_PROPS_SOURCE = re.compile(r'\bconst\s*\{([^{}]*)\}\s*=\s*(this\.props|this\.state|props)\s*;?')


def _literal_value(text):
    """``(True, value)`` for a JavaScript literal token, else ``(False, None)``."""
    text = text.strip()
    tokens = {'true': True, 'false': False, 'null': None, 'undefined': None}
    if text in tokens:
        return True, tokens[text]
    if re.fullmatch(r'-?\d+(?:\.\d+)?', text):
        return True, float(text)
    string = _string(text)
    return (True, string) if string is not None else (False, None)


def _truthy(value):
    return value not in (None, False, 0, 0.0, '')


def _object_entries(text):
    """Key -> value text and offset of an object literal, or None if it may hide keys."""
    entries = {}
    for entry, at in _split(text[1:-1], ','):
        entry, entry_at = _strip(entry, 1 + at)
        if not entry:
            continue
        if entry.startswith('...') or entry.startswith('['):
            return None
        key = re.match(r'''(?:(["'])([\w$]+)\1|([A-Za-z_$][\w$]*))\s*(:)?''', entry)
        if not key:
            return None
        name = key.group(2) or key.group(3)
        if key.group(4):
            entries[name] = (entry[key.end():], entry_at + key.end())
        elif key.end() == len(entry):
            entries[name] = (name, entry_at)
        else:
            # A method or accessor: the key exists, its value is not a literal.
            entries[name] = (None, entry_at)
    return entries


def _path_value(unit, text, start, path, spans, depth=0):
    """``(True, value)`` when *text* followed by *path* is a literal, else ``(False, reason)``."""
    text, start = _strip(text, start)
    source = unit.source
    if depth > _MAX_LABEL_DEPTH:
        return False, 'a value built through too many steps to follow'
    if text.startswith('(') and _close(text, 0) == len(text) - 1:
        return _path_value(unit, text[1:-1], start + 1, path, spans, depth + 1)
    if text.startswith('{') and _close(text, 0) == len(text) - 1:
        if not path:
            return True, {}
        entries = _object_entries(text)
        if entries is None:
            return False, 'an object with spread or computed keys'
        spans.append((source, start, start + len(text)))
        if path[0] not in entries:
            # A literal object without the key leaves it undefined.
            return ((True, None) if len(path) == 1 else
                    (False, f'an object without {path[0]}'))
        value, at = entries[path[0]]
        if value is None:
            return False, f'an object whose {path[0]} is not a literal value'
        return _path_value(unit, value, start + at, path[1:], spans, depth + 1)
    if not path:
        known, value = _literal_value(text)
        if known:
            spans.append((source, start, start + len(text)))
            return True, value
    call = _CALL.match(text)
    if call and _close(text, call.end() - 1) == len(text) - 1:
        target = _call_target(source, call.group(1), start)
        shape = _function_shape(target) if target else None
        if not shape or shape[1] is None:
            return False, f'{call.group(1)}(), which does not return one evaluable expression'
        spans.append((source, start, start + len(text)))
        spans.append((target.source, target.start, target.end))
        return _path_value(target, shape[1], shape[2], path, spans, depth + 1)
    if re.fullmatch(_IDENTIFIER, text):
        declaration = _constant(unit, text, start) or _module_constant(source, text)
        if declaration:
            value, at, declared = declaration
            spans.append((source, *declared))
            return _path_value(unit, value, at, path, spans, depth + 1)
    return False, f'`{" ".join(text.split())}`, a runtime value'


def _component_name(unit):
    return f'{unit.owner}.{unit.name}' if unit.owner else unit.name


def _seeded_state(owner, key):
    """The prop a class component's constructor seeds state *key* from, or None."""
    classes = [unit for unit in owner.source.units
               if unit.kind == 'class' and unit.name == owner.owner]
    constructors = [unit for unit in owner.source.units
                    if unit.owner == owner.owner and unit.name == 'constructor']
    if len(classes) != 1 or len(constructors) != 1:
        return None
    constructor = constructors[0]
    if re.search(r'(?m)^\s*(?:(?:public|private|protected|readonly)\s+)*state\s*(?::[^=;\n]+)?=(?!=)',
                 classes[0].text):
        return None
    assignments = list(re.finditer(r'\bthis\.state\s*=(?!=)', classes[0].text))
    if len(assignments) != 1:
        return None
    at = classes[0].start + assignments[0].end()
    text, at = _strip(owner.source.text[at:_statement_end(owner.source.text, at)], at)
    if not (text.startswith('{') and _close(text, 0) == len(text) - 1
            and constructor.start <= at < constructor.end):
        return None
    entries = _object_entries(text)
    value = entries.get(key) if entries else None
    if not value or value[0] is None:
        return None
    seeded = ' '.join(value[0].split())
    props = r'(?:this\.props' + ('|props' if _parameters(constructor)[:1] == ('props',)
                                 else '') + r')'
    found = (re.fullmatch(rf'{props}\.({_IDENTIFIER})', seeded)
             or re.fullmatch(rf'Object\.assign\(\s*\{{\s*\}}\s*,\s*{props}\.({_IDENTIFIER})\s*\)', seeded)
             or re.fullmatch(rf'\{{\s*\.\.\.\s*{props}\.({_IDENTIFIER})\s*,?\s*\}}', seeded))
    if not found:
        return None
    return found.group(1), [(owner.source, assignments[0].start() + classes[0].start,
                             at + len(text))]


def _flag_prop(owner, names, before):
    """``(prop, path, spans)`` when a flag is read from one of *owner*'s props."""
    if names[:2] == ['this', 'props'] and len(names) > 2:
        return names[2], names[3:], []
    if names[:2] == ['this', 'state'] and len(names) > 2:
        seeded = _seeded_state(owner, names[2])
        return (seeded[0], names[3:], seeded[1]) if seeded else None
    if names[0] == 'props' and len(names) > 1 and _parameters(owner)[:1] == ('props',):
        return names[1], names[2:], []
    bindings = []
    signature = _DESTRUCTURED_PROPS.match(owner.text)
    if signature:
        for part in signature.group(1).split(','):
            key, _, local = part.partition(':')
            if (local or key).split('=', 1)[0].strip() == names[0]:
                bindings.append(('props', key.strip(), '=' in part,
                                 (owner.source, owner.start, owner.start + signature.end())))
    text = owner.source.text
    for found in _PROPS_SOURCE.finditer(text, owner.start, before):
        for part in found.group(1).split(','):
            key, _, local = part.partition(':')
            if (local or key).split('=', 1)[0].strip() == names[0]:
                bindings.append((found.group(2), key.strip(), '=' in part,
                                 (owner.source, found.start(), found.end())))
    if len(bindings) != 1 or bindings[0][2]:
        return None
    origin, key, _, span = bindings[0]
    if origin == 'this.state':
        seeded = _seeded_state(owner, key)
        return (seeded[0], names[1:], [span, *seeded[1]]) if seeded else None
    return key, names[1:], [span]


def _top_level_text(text):
    top = [' '] * len(text)
    for index, character, depth in _scan(text):
        if depth == 0:
            top[index] = character
    return ''.join(top)


# State spread into a component carries a literal flag only along one chain,
# each step of which the source fixes:
#
#   const LITERAL = {...}                  the flag, in an object nothing else uses
#   Promise.resolve(LITERAL)               a promise of exactly that object
#   load(..., promise, ...)                load() returns only
#                                            Promise.all([..., param, ...])
#                                            .then(results => ({key: results[i]}))
#   .then(model => this.setState(model))   the only state the page ever sets
#   if (!this.state) return ...;           nothing renders before that state
#   <Component {...this.state} />          state keys become props
#
# Any other step (a loaded value, a second state write, an initial state, a
# reused literal) leaves the flag unknown.

_THEN = re.compile(r'\.\s*then\s*\(')
_SET_STATE_CALLBACKS = (
    re.compile(rf'\(?\s*({_IDENTIFIER})\s*(?::[^()=]*)?\)?\s*=>\s*this\.setState\(\s*\1\s*\)'),
    re.compile(rf'\(?\s*({_IDENTIFIER})\s*(?::[^()=]*)?\)?\s*=>\s*'
               rf'\{{\s*this\.setState\(\s*\1\s*\)\s*;?\s*\}}'),
    re.compile(r'this\.setState\.bind\(\s*this\s*\)'),
)
_STATE_WRITE = re.compile(
    r'(?m)\bthis\.state(?:\s*[.\[][\w$.\[\]\'"]*)?\s*(?:(?<![=!<>])=(?![=>])|\+\+|--)'
    r'|^\s*(?:(?:public|private|protected|readonly)\s+)*state\s*(?::[^=;\n]+)?=(?!=)')


def _arguments_text(text, opening):
    """Top-level arguments of the call whose ``(`` is at *opening*, or None on a spread."""
    closing = _close(text, opening)
    pieces = [_strip(piece, opening + 1 + at)
              for piece, at in _split(text[opening + 1:closing], ',')]
    if pieces and not pieces[-1][0]:
        pieces.pop()
    if any(not piece or piece.startswith('...') for piece, _ in pieces):
        return None
    return pieces


def _sole_use(source, name, declared, used):
    """Why the ``const`` *name* may not hold its literal, or None when *used* is its only use."""
    start, end = declared
    line = source.text[source.text.rfind('\n', 0, start) + 1:end]
    if re.match(r'\s*export\b', line):
        return f'{name} is exported, so other modules may change it'
    for found in re.finditer(rf'(?<![\w$.]){re.escape(name)}(?![\w$])', source.text):
        if found.start() != used and not start <= found.start() < end:
            number = source.text.count('\n', 0, found.start()) + 1
            return f'{name} is also used on line {number}, so the object may be changed'
    return None


def _promise_value(unit, text, start, path, spans, depth=0):
    """``(True, value)`` when the promise *text* resolves to a literal at *path*."""
    text, start = _strip(text, start)
    source = unit.source
    if depth > _MAX_LABEL_DEPTH:
        return False, 'a value built through too many steps to follow'
    resolve = re.match(r'Promise\s*\.\s*resolve\s*\(', text)
    if resolve and _close(text, resolve.end() - 1) == len(text) - 1:
        arguments = _arguments_text(text, resolve.end() - 1)
        if not arguments or len(arguments) != 1:
            return False, f'`{" ".join(text.split())}`, which has no single argument'
        value, at = arguments[0]
        at += start
        if re.fullmatch(_IDENTIFIER, value):
            declaration = _constant(unit, value, at) or _module_constant(source, value)
            why = declaration and _sole_use(source, value, declaration[2], at)
            if why:
                return False, why
        spans.append((source, start, start + len(text)))
        return _path_value(unit, value, at, path, spans, depth + 1)
    if re.fullmatch(_IDENTIFIER, text):
        declaration = _constant(unit, text, start)
        if declaration:
            value, at, declared = declaration
            spans.append((source, *declared))
            return _promise_value(unit, value, at, path, spans, depth + 1)
    return False, f'`{" ".join(text.split())}`, a runtime value'


def _model_value(unit, name, call_at, opening, key, path, spans):
    """``(True, value)`` for ``key.path`` of the object a call to *name* resolves to.

    The callee must return ``Promise.all([...]).then(results => ({...}))``
    and nothing else; ``results[i]`` is the i-th array element, either a
    parameter the caller binds or a promise the callee builds itself.
    """
    source = unit.source
    target = _call_target(source, name, call_at)
    shape = _function_shape(target) if target else None
    if not shape or shape[1] is None:
        return False, f'{name}() does not return one evaluable expression'
    params, body, body_at = shape
    # _function_shape counts top-level returns only; a nested one is another path.
    code = {index for index, _, _ in _scan(target.text)}
    returns = [found for found in re.finditer(r'(?<![\w$.])return(?![\w$])', target.text)
               if found.start() in code]
    if len(returns) > 1:
        return False, f'{name}() has {len(returns)} return statements'
    shown = f'{name}() does not return Promise.all([...]).then(results => ({{...}}))'
    every = re.match(r'Promise\s*\.\s*all\s*\(', body)
    if not every:
        return False, shown
    closing = _close(body, every.end() - 1)
    array, array_at = _strip(body[every.end():closing], every.end())
    if not (array.startswith('[') and _close(array, 0) == len(array) - 1):
        return False, shown
    elements = [_strip(piece, array_at + 1 + at) for piece, at in _split(array[1:-1], ',')]
    if elements and not elements[-1][0]:
        elements.pop()
    if any(not piece or piece.startswith('...') for piece, _ in elements):
        return False, f'{name}() passes Promise.all an array with holes or spreads'
    then = _THEN.match(body, closing + 1)
    if not then or body[_close(body, then.end() - 1) + 1:].strip():
        return False, shown
    handlers = _arguments_text(body, then.end() - 1)
    if not handlers or len(handlers) != 1:
        return False, f'{name}() handles Promise.all with other than one callback'
    handler, handler_at = handlers[0]
    arrow = re.match(rf'\(?\s*({_IDENTIFIER})\s*(?::[^()=]*)?\)?\s*=>\s*', handler)
    if not arrow:
        return False, shown
    result, result_at = _strip(handler[arrow.end():], handler_at + arrow.end())
    # ``=> {`` opens a block, so only a parenthesized object literal is returned.
    if not (result.startswith('(') and _close(result, 0) == len(result) - 1):
        return False, shown
    result, result_at = _strip(result[1:-1], result_at + 1)
    if not (result.startswith('{') and _close(result, 0) == len(result) - 1):
        return False, shown
    entries = _object_entries(result)
    if entries is None:
        return False, f'{name}() resolves to an object with spread or computed keys'
    if key not in entries or entries[key][0] is None:
        return False, f'{name}() resolves to an object without a {key} value'
    value, value_at = _strip(entries[key][0], result_at + entries[key][1])
    found_spans = [(target.source, target.start, target.end)]
    index = re.fullmatch(rf'{re.escape(arrow.group(1))}\s*\[\s*(\d+)\s*\]', value)
    if not index:
        known, found = _path_value(target, value, body_at + value_at, path, found_spans)
    elif int(index.group(1)) >= len(elements):
        return False, f'{name}() reads {value} past the end of its Promise.all array'
    else:
        element, element_at = elements[int(index.group(1))]
        if element in params:
            uses = re.findall(rf'(?<![\w$.]){re.escape(element)}(?![\w$])', target.text)
            if len(uses) != 2 or params.count(element) != 1:
                return False, f'{name}() uses or reassigns its parameter {element} elsewhere'
            arguments = _arguments_text(source.text, opening)
            position = params.index(element)
            if arguments is None or position >= len(arguments):
                return False, f'the call to {name}() does not pass {element}'
            argument, argument_at = arguments[position]
            known, found = _promise_value(unit, argument, argument_at, path, found_spans)
        else:
            known, found = _promise_value(target, element, body_at + element_at,
                                          path, found_spans)
    if not known:
        return False, f'{name}() resolves {key} from {found}'
    spans.extend(found_spans)
    return True, found


def _state_value(origin, usage, key, path, spans):
    """``(True, value)`` when ``this.state.key.path`` is a literal wherever *usage* renders."""
    source = origin.source
    classes = [unit for unit in source.units
               if unit.kind == 'class' and unit.name == origin.owner]
    if origin.kind != 'method' or len(classes) != 1:
        return False, 'reads this.state outside one class component'
    page = classes[0]
    text = page.text
    if not re.match(rf'class\s+{re.escape(page.name)}\b[^{{]*?\bextends\s+'
                    r'(?:React\s*\.\s*)?(?:Pure)?Component\b', text):
        return False, f'{page.name} extends a class that may set state itself'
    if _STATE_WRITE.search(text):
        return False, f'{page.name} assigns this.state directly'
    writes = list(re.finditer(r'\b(?:setState|replaceState)\b', text))
    if len(writes) != 1:
        return False, (f'{page.name} sets state in {len(writes)} places' if writes
                       else f'{page.name} never sets state')
    write = writes[0].start()
    # Without an initial state, ``this.state`` is null until the one write;
    # the guard keeps the usage from rendering before then.
    before = source.text[origin.start:usage]
    depths = {index: depth for index, _, depth in _scan(before)}
    guards = [found for found in
              re.finditer(r'\bif\s*\(\s*!\s*this\.state\s*\)\s*\{?\s*return\b', before)
              if depths.get(found.start()) == 1]
    if not guards:
        return False, (f'{_component_name(origin)} may render it before {page.name} '
                       'sets state, with no `if (!this.state) return` guard')
    thens = [(found, _close(text, found.end() - 1)) for found in _THEN.finditer(text)
             if found.end() - 1 < write < _close(text, found.end() - 1)]
    if not thens:
        return False, f'{page.name} sets state outside a promise callback'
    then, then_close = thens[-1]
    callback = text[then.end():then_close].strip()
    if not any(pattern.fullmatch(callback) for pattern in _SET_STATE_CALLBACKS):
        return False, f'{page.name} sets state to other than the resolved value'
    calls = [found for found in _CALL.finditer(text, 0, then.start())
             if not re.match(r'[\w$.]', text[found.start() - 1:found.start()])
             and _close(text, found.end() - 1) < then.start()
             and not text[_close(text, found.end() - 1) + 1:then.start()].strip()]
    if len(calls) != 1:
        return False, f'{page.name} sets state from a promise that is not one direct call'
    call = calls[0]
    owners = [unit for unit in source.units if unit.owner == page.name
              and unit.kind == 'method' and unit.start <= page.start + call.start() < unit.end]
    if len(owners) != 1:
        return False, f'{page.name} sets state outside one of its methods'
    known, value = _model_value(owners[0], call.group(1), page.start + call.start(),
                                page.start + call.end() - 1, key, path, spans)
    if not known:
        return False, value
    spans.append((source, page.start + call.start(), page.start + then_close + 1))
    spans.append((source, origin.start + guards[-1].start(), origin.start + guards[-1].end()))
    return True, value


def _passed_value(owner, origin, start, end, prop, path, spans):
    """``(True, value)`` for the literal a JSX usage passes for ``prop.path``."""
    tag = _opening_tag(origin.source.text[start:end])
    top = _top_level_text(tag)
    spreads = re.findall(r'\{\s*\.\.\.\s*([^{}]*?)\s*\}', tag)
    if (spreads == ['this.state'] and len(re.findall(r'\{\s*\.\.\.', tag)) == 1
            and not re.search(rf'(?<![\w$.-]){re.escape(prop)}(?![\w$-])', top)):
        found = [(origin.source, start, start + len(tag))]
        known, value = _state_value(origin, start, prop, path, found)
        if not known:
            return False, f'spreads this.state into the component, and {value}'
        spans.extend(found)
        return True, value
    if re.search(r'\{\s*\.\.\.', tag):
        return False, f'spreads runtime props into the component, so {prop} has no literal value'
    for found in re.finditer(rf'(?<![\w$.-]){re.escape(prop)}\s*=\s*(["\'{{])', tag):
        if top[found.start()] == ' ':
            continue
        opening = found.start(1)
        if tag[opening] == '{':
            closing = _close(tag, opening)
            known, value = _path_value(origin, tag[opening + 1:closing],
                                       start + opening + 1, path, spans)
        else:
            known, value = _path_value(origin, tag[opening:_skip_literal(tag, opening)],
                                       start + opening, path, spans)
        return (known, value) if known else (False, f'passes {prop} as {value}')
    spans.append((origin.source, start, start + len(tag)))
    if re.search(rf'(?<![\w$.-]){re.escape(prop)}(?![\w$-])(?!\s*=)', top):
        return (True, True) if not path else (False, f'passes {prop} as a bare flag')
    if path:
        return False, f'does not pass {prop}'
    if re.search(r'\bdefaultProps\b', owner.source.text):
        return False, f'does not pass {prop}, which may take a default value'
    return True, None


def _test_truth(owner, test, before, usage, spans):
    """``(truth, None)`` for a flag the usage fixes, else ``(None, why)``."""
    origin, start, end = usage
    negated, text = False, ' '.join(test.split())
    while True:
        if text.startswith('!'):
            negated, text = not negated, text[1:].strip()
        elif text.startswith('(') and _close(text, 0) == len(text) - 1:
            text = text[1:-1].strip()
        else:
            break
    flag = _flag_prop(owner, text.split('.'), before) if _NAME.fullmatch(text) else None
    if flag is None:
        return None, f'`{text}` is not read from a prop of {_component_name(owner)}'
    prop, path, flag_spans = flag
    found = []
    known, value = _passed_value(owner, origin, start, end, prop, path, found)
    if not known:
        return None, f'{_component_name(origin)} {value}'
    spans.extend(flag_spans + found)
    return _truthy(value) != negated, None


def _choose_label(owner, values, before, contexts):
    """The label each route shows, as ``(labels, conditions, spans, why)``."""
    if not contexts:
        return None, None, [], 'no route displays this component'
    if any(not chain for _, chain in contexts):
        return None, None, [], ('the route renders this component itself, so no page '
                                'passes the flags its label tests')
    kept, spans, whys = {}, [], []
    for _, chain in contexts:
        for value in values:
            selected = True
            for test, taken in value.conditions:
                truth, why = _test_truth(owner, test, before, chain[-1], spans)
                if truth is None:
                    whys.append(why)
                elif truth != taken:
                    selected = False
                    break
            if selected:
                kept.setdefault(value.parts[0][1].strip(), value)
    why = '; '.join(dict.fromkeys(whys)) or None
    if len(kept) == 1:
        [(label, value)] = kept.items()
        conditions = ' && '.join(test if taken else f'!({test})'
                                 for test, taken in value.conditions) or None
        return label, conditions, spans + list(value.spans), None
    return list(kept), None, spans, why


def _prepare_action_labels(sources, units):
    selected = {id(source) for source in sources}
    diagnostics = []
    for unit in units:
        if (id(unit.source) not in selected or _is_test(unit.source)
                or getattr(unit, 'anchor_registration_kind', None) != 'action'
                or unit.anchor_label or not getattr(unit, 'anchor_label_expression', None)
                or getattr(unit, 'anchor_owner_unit', None) is None):
            continue
        owner = unit.anchor_owner_unit
        text, at = _strip(*unit.anchor_label_expression)
        written = ' '.join(text.split())
        where = unit.route or _component_name(owner)
        values = _evaluate(_Scope(owner, None, _parameters(owner), 0), text, at)
        literal = all(len(value.parts) == 1 and value.parts[0][0] == 'lit'
                      and value.parts[0][1].strip() for value in values)
        unit.anchor_label_evidence_spans = [(unit.source, at, at + len(text))]
        code = None
        if not literal:
            code = LABEL_RUNTIME_CODE
            unit.anchor_label_reason = (f'Visible action label on {where} is the runtime '
                f'expression `{written}`; no literal text names this action.')
        else:
            labels = list(dict.fromkeys(value.parts[0][1].strip() for value in values))
            if len(labels) == 1:
                unit.anchor_label = labels[0]
                unit.anchor_label_evidence_spans += [span for value in values
                                                     for span in value.spans]
            else:
                chosen, condition, spans, why = _choose_label(
                    owner, values, at, getattr(unit, 'anchor_route_contexts', []))
                if isinstance(chosen, str):
                    unit.anchor_label = chosen
                    unit.anchor_label_condition = condition
                    unit.anchor_label_evidence_spans += spans
                else:
                    code = LABEL_AMBIGUOUS_CODE
                    candidates = chosen or labels
                    unit.anchor_label_candidates = candidates
                    unit.anchor_label_evidence_spans += spans
                    unit.anchor_label_reason = (
                        f'Visible action label on {where} is one of '
                        + ', '.join(f"'{label}'" for label in candidates)
                        + f': {why or "no source evidence selects one"}.')
        rules.declare_action(unit)
        if code:
            diagnostics.append({'source_id': unit.source.resource_id, 'code': code,
                                'reason': unit.anchor_label_reason,
                                'span': (at, at + len(text))})
    return diagnostics
