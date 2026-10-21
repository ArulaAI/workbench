"""Resolve the declared types of TypeScript receiver expressions.

Only reads what the source writes: annotations, `as` casts, aliases,
interfaces, declared return types, constructors, literals and documented
platform return types. Nothing is inferred from usage. If any step can't be
read, the result is None.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache

from . import rules
from ..language_registry import registry

TYPED_LANGUAGES = frozenset({'typescript', 'tsx'})
_IDENTIFIER = r'[A-Za-z_$][\w$]*'
_MAX_DEPTH = 12

_PRIMITIVES = {'string': 'String', 'number': 'Number', 'boolean': 'Boolean',
               'bigint': 'BigInt', 'symbol': 'Symbol'}
_NULLISH = {'undefined', 'null', 'void'}
_UNTYPED = {'any', 'unknown', 'object', 'never', '{}', 'Function'}
_ITERABLE = {'Array', 'ReadonlyArray', 'Set', 'ReadonlySet', 'Iterator'}

# Return types of platform methods. Callback-dependent results are only typed
# as far as the platform fixes them: `map` gives an array of unknown elements,
# `reduce` takes the type of its initial value.
_SAME = 'same'
_ELEMENT = 'element'
_VALUE = 'value'
_KEY = 'key'
_RETURNS = {
    'String': {
        **dict.fromkeys(('replace', 'replaceAll', 'slice', 'substring', 'substr',
                         'padStart', 'padEnd', 'trim', 'trimStart', 'trimEnd',
                         'toUpperCase', 'toLowerCase', 'toLocaleUpperCase',
                         'toLocaleLowerCase', 'concat', 'repeat', 'normalize',
                         'charAt', 'toString', 'valueOf'), 'String'),
        **dict.fromkeys(('charCodeAt', 'codePointAt', 'indexOf', 'lastIndexOf',
                         'search', 'localeCompare'), 'Number'),
        **dict.fromkeys(('startsWith', 'endsWith', 'includes'), 'Boolean'),
        'split': ('Array', 'String'),
    },
    'Number': dict.fromkeys(('toString', 'toFixed', 'toPrecision', 'toExponential',
                             'toLocaleString'), 'String'),
    'BigInt': dict.fromkeys(('toString', 'toLocaleString'), 'String'),
    'Boolean': {'toString': 'String'},
    'Array': {
        **dict.fromkeys(('filter', 'slice', 'concat', 'reverse', 'sort', 'splice',
                         'toSorted', 'toReversed', 'fill', 'copyWithin'), _SAME),
        **dict.fromkeys(('find', 'findLast', 'at', 'pop', 'shift'), _ELEMENT),
        **dict.fromkeys(('join', 'toString', 'toLocaleString'), 'String'),
        **dict.fromkeys(('indexOf', 'lastIndexOf', 'findIndex', 'findLastIndex',
                         'push', 'unshift'), 'Number'),
        **dict.fromkeys(('includes', 'some', 'every'), 'Boolean'),
        'values': ('Iterator', _ELEMENT),
        'map': ('Array', None), 'flatMap': ('Array', None), 'flat': ('Array', None),
    },
    'Map': {'get': _VALUE, 'set': _SAME, 'has': 'Boolean', 'delete': 'Boolean',
            'values': ('Iterator', _VALUE), 'keys': ('Iterator', _KEY)},
    'Set': {'has': 'Boolean', 'delete': 'Boolean', 'add': _SAME,
            'values': ('Iterator', _ELEMENT)},
    'Date': {**dict.fromkeys(('getTime', 'valueOf', 'getFullYear', 'getMonth',
                              'getDate', 'getDay', 'getHours', 'getMinutes',
                              'getSeconds', 'getMilliseconds', 'getUTCFullYear',
                              'getUTCMonth', 'getUTCDate', 'getUTCHours'), 'Number'),
             **dict.fromkeys(('toISOString', 'toString', 'toJSON', 'toDateString',
                              'toTimeString', 'toLocaleDateString',
                              'toLocaleTimeString', 'toLocaleString',
                              'toUTCString'), 'String')},
    'RegExp': {'test': 'Boolean', 'toString': 'String'},
}
_RETURNS['ReadonlyArray'] = _RETURNS['Array']
# Static platform functions with a fixed result type.
_STATIC_RETURNS = {
    ('Date', 'now'): 'Number', ('Date', 'parse'): 'Number', ('Date', 'UTC'): 'Number',
    ('JSON', 'stringify'): 'String', ('Object', 'keys'): ('Array', 'String'),
    ('Array', 'isArray'): 'Boolean', ('Number', 'isInteger'): 'Boolean',
    ('Number', 'isFinite'): 'Boolean', ('Number', 'isNaN'): 'Boolean',
    ('Number', 'parseInt'): 'Number', ('Number', 'parseFloat'): 'Number',
    ('String', 'fromCharCode'): 'String',
    ('Object', 'values'): ('Array', None), ('Object', 'entries'): ('Array', None),
    ('Array', 'from'): ('Array', None), ('Array', 'of'): ('Array', None),
}
_GLOBAL_RETURNS = {'String': 'String', 'Number': 'Number', 'Boolean': 'Boolean',
                   'parseInt': 'Number', 'parseFloat': 'Number',
                   'encodeURIComponent': 'String', 'decodeURIComponent': 'String',
                   'encodeURI': 'String', 'decodeURI': 'String',
                   'isNaN': 'Boolean', 'isFinite': 'Boolean'}
_LENGTH = {'String', 'Array', 'ReadonlyArray'}


@dataclass(frozen=True)
class Type:
    """A declared type.

    name is a platform type, a repository class, '{}' (object type, members in
    body) or '{=}' (object literal). declared is the alias, interface or binding
    name of an object type. origin is (owner, member, path) or (None, name, path)
    when the value is shared state, and empty otherwise.
    """
    name: str
    args: tuple = ()
    body: str = ''
    path: str = ''
    offset: int = 0
    parts: tuple = ()
    steps: tuple = field(default=(), compare=False)
    declared: str = field(default='', compare=False)
    origin: tuple = field(default=(), compare=False)

    def note(self, step, first=False):
        if not step or step in self.steps:
            return self
        return replace(self, steps=(step, *self.steps) if first else (*self.steps, step))

    def after(self, earlier):
        """Return this type with the steps of earlier prepended."""
        if earlier is None:
            return self
        steps = tuple(step for step in earlier.steps if step != 'ambient')
        return replace(self, steps=(*steps, *(step for step in self.steps if step not in steps)))

    @property
    def label(self):
        if self.name == 'Array' and self.args and self.args[0] is not None \
                and self.args[0].name not in {'{}', '{=}'}:
            return f'{self.args[0].label}[]'
        if self.args and all(arg is not None and arg.name not in {'{}', '{=}'}
                             for arg in self.args):
            return f'{self.name}<{", ".join(arg.label for arg in self.args)}>'
        return self.name


# Scanning

def _skip(text, index):
    """Return the index past the comment or string literal at index, or index itself."""
    if text.startswith('//', index):
        end = text.find('\n', index)
        return len(text) if end < 0 else end
    if text.startswith('/*', index):
        end = text.find('*/', index + 2)
        return len(text) if end < 0 else end + 2
    quote = text[index] if index < len(text) else ''
    if quote not in '\'"`':
        return index
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


def _scan(text, start=0, angles=False):
    """Yield (index, character, depth) outside comments and literals.

    With angles=True, < and > nest like brackets, except the > in =>.
    """
    depth = 0
    cursor = start
    opening, closing = ('([{<', ')]}>') if angles else ('([{', ')]}')
    while cursor < len(text):
        skipped = _skip(text, cursor)
        if skipped != cursor:
            cursor = skipped
            continue
        character = text[cursor]
        arrow = character == '>' and cursor and text[cursor - 1] == '='
        if character in closing and not arrow:
            depth -= 1
        yield cursor, character, depth
        if character in opening:
            depth += 1
        cursor += 1


def _close(text, index, angles=False):
    """Return the index of the bracket that closes the one at index."""
    for cursor, character, depth in _scan(text, index, angles):
        if depth == 0 and cursor > index and character in ')]}>':
            return cursor
    return len(text)


def _split(text, separators, angles=False):
    """Split text on top-level separators."""
    pieces, start = [], 0
    for index, character, depth in _scan(text, 0, angles):
        if depth == 0 and character in separators:
            pieces.append(text[start:index])
            start = index + 1
    pieces.append(text[start:])
    return [piece for piece in (p.strip() for p in pieces) if piece]


def _top_level_find(text, token, angles=False, last=False):
    """Return the index of token outside brackets, comments and literals, or -1."""
    found = -1
    for index, _character, depth in _scan(text, 0, angles):
        if depth == 0 and text.startswith(token, index):
            if not last:
                return index
            found = index
    return found


def _statement_end(text, start):
    """Return the end of the expression at start.

    Stops at ;, an unmatched closing bracket, or a newline the next line
    doesn't continue.
    """
    for index, character, depth in _scan(text, start):
        if depth < 0 or (depth == 0 and character == ';'):
            return index
        if depth == 0 and character == '\n':
            before = text[start:index].rstrip()
            after = text[index:].lstrip()
            if (before and before[-1] not in '+-*/%?:=,(&|<'
                    and not (after[:1] and after[0] in '+-*/%?:.=,)&|>')):
                return index
    return len(text)


def _annotation_end(text, start):
    """Return the end of the type annotation at start.

    Stops at a top-level =, ;, ,, ) or {, or a newline the next line doesn't
    continue.
    """
    for index, character, depth in _scan(text, start, angles=True):
        if depth < 0:
            return index
        if depth == 0 and (character in ';,)' or (
                character == '=' and text[index + 1:index + 2] != '>')):
            return index
        if depth == 0 and character == '{' and text[start:index].strip() and \
                not re.search(r'(?:[&|:<,(]|=>)\s*$', text[start:index]):
            return index
        if depth == 0 and character == '\n':
            before = text[start:index].rstrip()
            after = text[index:].lstrip()
            if before and before[-1] not in '&|<,:(' and not after[:1] in {'&', '|'}:
                return index
    return len(text)


def _line(source, offset):
    return source.text.count('\n', 0, offset) + 1


def _normalize(expression):
    """Join a method chain split across lines."""
    return re.sub(r'\s*\n\s*(\??\.)', r'\1', expression.strip()).strip()


# Declarations

@dataclass
class _Declaration:
    kind: str          # alias | interface | class | value | function
    name: str
    source: object
    offset: int
    text: str = ''     # alias body, interface body, value expression
    annotation: str = ''
    extends: tuple = ()
    end: int = 0


class _Index:
    """Top-level declarations of all TypeScript sources, keyed by file."""

    def __init__(self, sources):
        self.sources = {source.path: source for source in sources}
        self.declarations = {source.path: _declarations(source) for source in sources}
        self.imports = {source.path: _imports(source) for source in sources}
        self.written = None

    def lookup(self, name, path, kinds, seen=()):
        """Find the declaration name refers to in path, following relative imports."""
        found = [item for item in self.declarations.get(path, {}).get(name, ())
                 if item.kind in kinds]
        if found:
            return found[0]
        module, imported = self.imports.get(path, {}).get(name, (None, None))
        target = self._module_path(path, module) if module else None
        if target and (target, imported) not in seen:
            return self.lookup(imported, target, kinds, (*seen, (target, imported)))
        return None

    def _module_path(self, path, module):
        if not module.startswith('.'):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(path), module))
        stem = re.sub(r'\.(?:[cm]?js|jsx)$', '', base)
        for candidate in (base, f'{stem}.ts', f'{stem}.tsx', f'{base}.ts', f'{base}.tsx',
                          f'{base}/index.ts', f'{base}/index.tsx'):
            if candidate in self.sources:
                return candidate
        return None


def _imports(source):
    """Map each named import's local name to (module, exported name)."""
    bound = {}
    for match in re.finditer(r'\bimport\s+(?:type\s+)?\{([^}]*)\}\s*from\s*([\'"])([^\'"]+)\2',
                             source.text):
        for clause in match.group(1).split(','):
            clause = re.sub(r'^\s*type\s+', '', clause).strip()
            if not clause:
                continue
            exported, _, local = clause.partition(' as ')
            local = (local or exported).strip()
            if re.fullmatch(_IDENTIFIER, local) and re.fullmatch(_IDENTIFIER, exported.strip()):
                bound[local] = (match.group(3), exported.strip())
    return bound


@lru_cache(maxsize=512)
def _depths(text):
    """Return the bracket depth at each character, outside comments and literals."""
    depths = [None] * (len(text) + 1)
    for index, _character, depth in _scan(text):
        depths[index] = depth
    return depths


_ALIAS = re.compile(rf'(?m)^[ \t]*(?:export\s+)?(?:declare\s+)?type\s+({_IDENTIFIER})\s*(?:<[^=]*?>)?\s*=')
_INTERFACE = re.compile(rf'(?m)^[ \t]*(?:export\s+)?(?:declare\s+)?interface\s+({_IDENTIFIER})\s*(?:<[^{{]*?>)?\s*(?:extends\s+([^{{]+))?\{{')
_CLASS = re.compile(rf'(?m)^[ \t]*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+({_IDENTIFIER})[^{{]*\{{')
_VALUE_DECLARATION = re.compile(rf'(?m)^[ \t]*(?:export\s+)?(?:const|let|var)\s+({_IDENTIFIER})\s*(:)?')
_FUNCTION = re.compile(rf'(?m)^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*({_IDENTIFIER})\s*(?:<[^(]*?>)?\s*\(')


def _declarations(source):
    text = source.text
    depths = _depths(text)
    found = {}

    def add(item):
        found.setdefault(item.name, []).append(item)

    for match in _ALIAS.finditer(text):
        if depths[match.start(1)] != 0:
            continue
        end = _annotation_end(text, match.end())
        add(_Declaration('alias', match.group(1), source, match.start(1),
                         text[match.end():end].strip()))
    for match in _INTERFACE.finditer(text):
        if depths[match.start(1)] != 0:
            continue
        opening = match.end() - 1
        closing = _close(text, opening)
        add(_Declaration('interface', match.group(1), source, match.start(1),
                         text[opening + 1:closing],
                         extends=tuple(_split(match.group(2) or '', ',', angles=True))))
    for match in _CLASS.finditer(text):
        if depths[match.start(1)] != 0:
            continue
        opening = match.end() - 1
        add(_Declaration('class', match.group(1), source, match.start(1),
                         text[opening + 1:_close(text, opening)], end=_close(text, opening)))
    for match in _VALUE_DECLARATION.finditer(text):
        if depths[match.start(1)] != 0:
            continue
        cursor = match.end()
        annotation = ''
        if match.group(2):
            end = _annotation_end(text, cursor)
            annotation, cursor = text[cursor:end].strip(), end
        assign = re.match(r'\s*=(?!=)\s*', text[cursor:])
        if not assign:
            continue
        start = cursor + assign.end()
        add(_Declaration('value', match.group(1), source, start,
                         text[start:_statement_end(text, start)].strip(), annotation))
    for match in _FUNCTION.finditer(text):
        if depths[match.start(1)] != 0:
            continue
        opening = match.end() - 1
        add(_Declaration('function', match.group(1), source, match.start(1),
                         annotation=_return_annotation(text, opening)))
    return found


def _return_annotation(text, opening):
    """Return the return type written after the parameter list at opening."""
    closing = _close(text, opening)
    after = re.match(r'\s*:\s*', text[closing + 1:])
    if not after:
        return ''
    start = closing + 1 + after.end()
    end = start
    for index, character, depth in _scan(text, start, angles=True):
        if depth < 0:
            end = index
            break
        if depth == 0 and (character == '{' and text[start:index].strip()
                           and not re.search(r'(?:[&|:<,(]|=>)\s*$', text[start:index])
                           or text.startswith('=>', index) or character in ';='):
            end = index
            break
    else:
        end = len(text)
    annotation = text[start:end].strip()
    return '' if annotation.startswith(('asserts ', 'this is')) or ' is ' in annotation \
        else annotation


def _parameters(text, opening):
    """Return (name, annotation, default) for each simple parameter."""
    closing = _close(text, opening)
    result = []
    for piece in _split(text[opening + 1:closing], ','):
        piece = re.sub(r'^(?:(?:public|private|protected|readonly|override)\s+)+', '', piece)
        match = re.match(rf'({_IDENTIFIER})\s*\??\s*(?::\s*)?', piece)
        if not match or piece.startswith(('{', '[', '...')):
            continue
        rest = piece[match.end():]
        annotation, default = '', ''
        if re.match(rf'{_IDENTIFIER}\s*\??\s*:', piece):
            end = _annotation_end(rest, 0)
            annotation, rest = rest[:end].strip(), rest[end:]
        equals = re.match(r'\s*=(?!=)\s*', rest)
        if equals:
            default = rest[equals.end():].strip()
        result.append((match.group(1), annotation, default))
    return result


# Evaluation

class _Evaluator:
    def __init__(self, index, unit):
        self.index = index
        self.unit = unit
        self.source = unit.source
        self.ambient = registry.ambient_globals(unit.source.language)
        self.depth = 0

    # Types

    def parse(self, text, path, note=''):
        """Parse a type annotation written in path."""
        self.depth += 1
        try:
            if self.depth > _MAX_DEPTH:
                return None
            result = self._parse(text.strip(), path)
            return result.note(note, first=True) if result is not None else None
        finally:
            self.depth -= 1

    def _parse(self, text, path):
        text = re.sub(r'^(?:readonly|keyof\s+typeof)\s+', '', text).strip()
        if text.startswith('|') or text.startswith('&'):
            text = text[1:].strip()
        if not text or text in _UNTYPED:
            return None
        alternatives = [item for item in _split(text, '|', angles=True)
                        if item not in _NULLISH]
        if len(alternatives) > 1:
            types = [self.parse(item, path) for item in alternatives]
            return _agree(types)
        if len(alternatives) == 1 and alternatives[0] != text:
            return self.parse(alternatives[0], path)
        parts = _split(text, '&', angles=True)
        if len(parts) > 1:
            types = [self.parse(item, path) for item in parts]
            primitive = [item for item in types if item is not None and item.name in
                         {'String', 'Number', 'Boolean', 'BigInt'}]
            if primitive:
                return primitive[0]
            known = tuple(item for item in types if item is not None)
            return Type('&', parts=known, path=path) if known else None
        if text.endswith('[]'):
            element = self.parse(text[:-2], path)
            return Type('Array', (element,), path=path)
        if text.startswith('(') and _close(text, 0, angles=True) == len(text) - 1:
            return self.parse(text[1:-1], path)
        if text.startswith('{'):
            return Type('{}', body=text[1:_close(text, 0)], path=path)
        if re.fullmatch(r'([\'"]).*\1', text) or text.startswith('`'):
            return Type('String')
        if re.fullmatch(r'-?\d[\d_]*(?:\.\d+)?', text):
            return Type('Number')
        if text in {'true', 'false'}:
            return Type('Boolean')
        match = re.fullmatch(rf'({_IDENTIFIER})\s*(?:<(.*)>)?', text, re.DOTALL)
        if not match:
            return None
        name, generics = match.group(1), match.group(2)
        if name in _PRIMITIVES:
            return Type(_PRIMITIVES[name])
        args = tuple(self.parse(item, path) for item in _split(generics or '', ',', angles=True))
        if name in {'Array', 'ReadonlyArray'}:
            return Type('Array', args[:1] or (None,), path=path)
        if name in {'Set', 'ReadonlySet'}:
            return Type('Set', args[:1] or (None,), path=path)
        if name in {'Map', 'ReadonlyMap'}:
            return Type('Map', (args + (None, None))[:2], path=path)
        declaration = self.index.lookup(name, path, {'alias', 'interface', 'class'})
        if declaration is None:
            return Type(name, args, path=path) if name in self.ambient else None
        where = f'{declaration.source.path}:{_line(declaration.source, declaration.offset)}'
        if declaration.kind == 'alias':
            found = self.parse(declaration.text, declaration.source.path,
                               f'{name} = {_short(declaration.text)} ({where})')
            if found is not None and found.name == '{}' and not found.offset:
                body = declaration.source.text.find('{', declaration.offset) + 1
                found = replace(found, offset=body)
            if found is not None and found.name in {'{}', '&'}:
                found = replace(found, declared=name)
            return found
        if declaration.kind == 'interface':
            extended = tuple(item for item in (self.parse(base, declaration.source.path)
                                               for base in declaration.extends)
                             if item is not None)
            own = Type('{}', body=declaration.text, path=declaration.source.path,
                       offset=declaration.source.text.find('{', declaration.offset) + 1,
                       declared=name)
            return Type('&', parts=(own, *extended), path=declaration.source.path,
                        declared=name) if extended else own
        return Type(name, args, path=declaration.source.path, offset=declaration.offset)

    # Members

    def member(self, owner, name):
        """Return the declared type of a member of owner."""
        if owner is None:
            return None
        if owner.name == '&':
            return next((found for part in owner.parts
                         if (found := self.member(part, name)) is not None), None)
        if name == 'length' and owner.name in _LENGTH:
            return Type('Number')
        if owner.name == '{}':
            return self._object_type_member(owner, name)
        if owner.name == '{=}':
            return self._object_literal_member(owner, name)
        declaration = self.index.lookup(owner.name, owner.path, {'class'})
        if declaration is not None:
            found = self._class_member(declaration, name)
            return found[0] if found else None
        return None

    def method(self, owner, name, arguments):
        """Return the declared return type of calling a method on owner."""
        if owner is None:
            return None
        if owner.name == '&':
            return next((found for part in owner.parts
                         if (found := self.method(part, name, arguments)) is not None), None)
        table = _RETURNS.get(owner.name)
        if table is not None:
            result = table.get(name)
            if name == 'reduce' and len(arguments) == 2:
                return self.expression(arguments[1], self.source, self.position)
            return self._platform_result(owner, result)
        if owner.name == '{}':
            found = self._object_type_member(owner, name, called=True)
            return found
        if owner.name == '{=}':
            return self._object_literal_member(owner, name, called=True)
        declaration = self.index.lookup(owner.name, owner.path, {'class'})
        if declaration is not None:
            found = self._class_member(declaration, name, called=True)
            return found[0] if found else None
        return None

    def _platform_result(self, owner, result):
        if result is None:
            return None
        if result == _SAME:
            return owner
        if result == _ELEMENT:
            return owner.args[0] if owner.args else None
        if result == _VALUE:
            return owner.args[1] if len(owner.args) > 1 else None
        if result == _KEY:
            return owner.args[0] if owner.args else None
        if isinstance(result, tuple):
            container, inner = result
            if inner is None:
                return Type(container, (None,))
            if inner in _RETURNS:
                return Type(container, (Type(inner),))
            return Type(container, (self._platform_result(owner, inner),))
        return Type(result)

    def _object_type_member(self, owner, name, called=False):
        for piece in _split(owner.body, ';,\n', angles=True):
            piece = re.sub(r'^(?:readonly\s+)', '', piece.strip())
            piece = re.sub(r'^/\*.*?\*/\s*', '', piece, flags=re.DOTALL)
            method = re.match(rf'([\'"]?)({_IDENTIFIER})\1\s*\??\s*(?:<[^(]*>)?\s*\(', piece)
            if method and method.group(2) == name:
                opening = method.end() - 1
                if called:
                    return self.parse(_return_annotation(piece, opening), owner.path)
                return None
            prop = re.match(rf'([\'"]?)({_IDENTIFIER})\1\s*\??\s*:\s*', piece)
            if prop and prop.group(2) == name:
                annotation = piece[prop.end():].strip()
                source = self.index.sources.get(owner.path)
                where = f'{owner.path}:{_line(source, owner.offset + owner.body.find(piece))}' \
                    if source is not None and owner.offset else owner.path
                if called:
                    arrow = re.match(r'\(.*?\)\s*=>\s*(.+)$', annotation, re.DOTALL)
                    return self.parse(arrow.group(1), owner.path) if arrow else None
                return self.parse(annotation, owner.path,
                                  f'{name}: {_short(annotation)} ({where})')
        return None

    def _object_literal_member(self, owner, name, called=False):
        source = self.index.sources.get(owner.path, self.source)
        cursor = 0
        for piece in _split(owner.body, ','):
            offset = owner.offset + owner.body.find(piece, cursor)
            cursor = owner.body.find(piece, cursor) + len(piece)
            method = re.match(rf'(?:async\s+)?({_IDENTIFIER})\s*\(', piece)
            if method and method.group(1) == name:
                return self.parse(_return_annotation(piece, method.end() - 1), owner.path) \
                    if called else None
            prop = re.match(rf'([\'"]?)({_IDENTIFIER})\1\s*:\s*', piece)
            if prop and prop.group(2) == name:
                value = piece[prop.end():]
                if called:
                    arrow = re.match(r'\s*(?:async\s+)?\(', value)
                    return self.parse(_return_annotation(value, arrow.end() - 1), owner.path) \
                        if arrow else None
                found = self.expression(value, source, offset + prop.end())
                return found.note(f'{name}: {_short(value)} ({owner.path}:'
                                  f'{_line(source, offset)})', first=True) if found else None
            if piece == name:
                return self.expression(name, source, offset)
        return None

    def _class_member(self, declaration, name, called=False):
        """Return (type,) for a member of a class declaration, or ()."""
        text = declaration.source.text
        body_start = declaration.end - len(declaration.text)
        body = declaration.text
        depths = _depths(body)
        modifiers = r'(?:(?:public|private|protected|readonly|static|declare|override|abstract|async|get)\s+)*'
        where = lambda offset: f'{declaration.source.path}:{_line(declaration.source, offset)}'
        for match in re.finditer(rf'(?m)^[ \t]*{modifiers}#?({re.escape(name)})\s*([?!])?\s*(\(|<|:|=|;)', body):
            if depths[match.start(1)] != 0:
                continue
            marker = match.group(3)
            offset = body_start + match.start(1)
            if marker in '(<':
                if not called:
                    return ()
                opening = body.find('(', match.start(3))
                annotation = _return_annotation(body, opening)
                found = self.parse(annotation, declaration.source.path,
                                   f'{declaration.name}.{name}(): {_short(annotation)} ({where(offset)})')
                return (found,) if found else ()
            if called:
                return ()
            cursor = match.end()
            if marker == ':':
                end = _annotation_end(body, cursor)
                annotation = body[cursor:end].strip()
                found = self.parse(annotation, declaration.source.path,
                                   f'{declaration.name}.{name}: {_short(annotation)} ({where(offset)})')
                if found is not None:
                    return (found,)
                cursor = end
                if not re.match(r'\s*=(?!=)', body[cursor:]):
                    return ()
                cursor += re.match(r'\s*=', body[cursor:]).end()
            elif marker == '=':
                pass
            else:
                return ()
            start = body_start + cursor
            value = text[start:_statement_end(text, start)]
            found = self.expression(value, declaration.source, start)
            return (found.note(f'{declaration.name}.{name} = {_short(value)} ({where(offset)})',
                               first=True),) if found else ()
        constructor = re.search(r'\bconstructor\s*\(', body)
        if constructor and not called and depths[constructor.start()] == 0:
            opening = constructor.end() - 1
            for parameter in re.finditer(
                    rf'(?:public|private|protected|readonly)\s+(?:readonly\s+)?{re.escape(name)}\s*\??\s*:\s*',
                    body[opening:_close(body, opening)]):
                start = opening + parameter.end()
                annotation = body[start:_annotation_end(body, start)].strip()
                found = self.parse(annotation, declaration.source.path,
                                   f'{declaration.name}.{name}: {_short(annotation)} '
                                   f'({where(body_start + opening)})')
                return (found,) if found else ()
        return ()

    # Expressions

    def expression(self, text, source, position):
        """Return the declared type of an expression written at position."""
        saved = (self.source, getattr(self, 'position', None))
        self.source, self.position = source, position
        self.depth += 1
        try:
            if self.depth > _MAX_DEPTH:
                return None
            return self._expression(_normalize(text))
        finally:
            self.depth -= 1
            self.source, self.position = saved

    def _expression(self, text):
        if not text:
            return None
        cast = _top_level_find(text, ' as ', last=True)
        if cast > 0:
            target = text[cast + 4:].strip()
            if target == 'const':
                return self._expression(text[:cast])
            return self.parse(target, self.source.path)
        if _top_level_find(text, '?', last=False) > 0:
            coalesce = _top_level_find(text, '??')
            if coalesce > 0:
                left = self._expression(text[:coalesce].strip())
                right = self._expression(text[coalesce + 2:].strip())
                return _agree([left, right])
            if _ternary(text):
                return None
        if re.match(r'^(\+\+|--)', text) or re.search(r'(\+\+|--)$', text):
            return Type('Number')
        if re.match(r'^(?:typeof\s)', text):
            return Type('String')
        if text.startswith('!') and not text.startswith('!='):
            return Type('Boolean')
        if text.startswith('/') and not text.startswith(('//', '/*')):
            return Type('RegExp')
        if _arithmetic(text):
            return Type('Number')
        if text[0] in '\'"`':
            end = _skip(text, 0)
            if end == len(text):
                return Type('String')
        if re.fullmatch(r'-?(?:0[xob][\da-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:e-?\d+)?)', text):
            return Type('Number')
        if text in {'true', 'false'}:
            return Type('Boolean')
        if text.startswith('[') and _close(text, 0) == len(text) - 1:
            return Type('Array', (None,))
        if text.startswith('{') and _close(text, 0) == len(text) - 1:
            return Type('{=}', body=text[1:-1], path=self.source.path,
                        offset=self.position + 1)
        return self._chain(text)

    def _chain(self, text):
        """Resolve a primary followed by member access, calls, indexing and `!`."""
        construct = re.match(rf'new\s+({_IDENTIFIER})\s*(<)?', text)
        if construct:
            cursor = construct.end(1)
            generics = ''
            if construct.group(2):
                closing = _close(text, construct.start(2), angles=True)
                generics = text[construct.start(2):closing + 1]
                cursor = closing + 1
            opening = re.match(r'\s*\(', text[cursor:])
            if not opening:
                return None
            cursor += opening.end() - 1
            cursor = _close(text, cursor) + 1
            current = self.parse(construct.group(1) + generics, self.source.path)
            pending = None
        elif text.startswith('('):
            closing = _close(text, 0)
            current = self._expression(text[1:closing].strip())
            cursor, pending = closing + 1, None
        else:
            head = re.match(rf'this\b|{_IDENTIFIER}', text)
            if not head:
                return None
            cursor = head.end()
            if head.group() == 'this':
                current, pending = Type('this'), None
            else:
                current, pending = None, ('name', head.group())
        while cursor < len(text):
            rest = text[cursor:]
            if rest.startswith('!') and not rest.startswith('!='):
                cursor += 1
                continue
            access = re.match(rf'\??\.\s*(#?{_IDENTIFIER})', rest)
            if access:
                current = self._resolve(current, pending)
                if current is None:
                    return None
                pending = ('member', current, access.group(1))
                current = None
                cursor += access.end()
                continue
            if rest.startswith('?.('):
                cursor += 2
                rest = text[cursor:]
            if rest.startswith('('):
                closing = _close(text, cursor)
                arguments = _split(text[cursor + 1:closing], ',')
                current = self._call(current, pending, arguments)
                if current is None:
                    return None
                pending = None
                cursor = closing + 1
                continue
            if rest.startswith('['):
                closing = _close(text, cursor)
                current = self._resolve(current, pending)
                pending = None
                index = text[cursor + 1:closing].strip()
                if current is None:
                    return None
                if current.name in _ITERABLE and re.fullmatch(r'-?\d+', index):
                    current = current.args[0] if current.args else None
                elif current.name == 'String':
                    current = Type('String')
                else:
                    current = self._object_type_member(current, index.strip('\'"')) \
                        if current.name == '{}' and re.fullmatch(r'([\'"])\w+\1', index) else None
                if current is None:
                    return None
                cursor = closing + 1
                continue
            return None
        return self._resolve(current, pending)

    def _resolve(self, current, pending):
        if pending is None:
            return current
        if pending[0] == 'name':
            return self.name(pending[1])
        _kind, owner, member = pending
        if owner.name == 'this':
            return self._this_member(member)
        if owner.name in self.ambient and not owner.args and owner.name not in _RETURNS:
            return None
        found = self.member(owner, member)
        if found is None:
            return None
        owner_name = owner.declared or (owner.name if owner.name not in {'{}', '{=}', '&'} else '')
        origin = (owner_name, member, owner.path) if owner_name else ()
        return replace(found.after(owner), origin=origin)

    def _call(self, current, pending, arguments):
        if pending is None:
            return None
        if pending[0] == 'name':
            return self.function(pending[1])
        _kind, owner, member = pending
        if owner.name == 'this':
            declaration = self._enclosing_class()
            found = self._class_member(declaration, member, called=True) if declaration else ()
            return found[0] if found else None
        static = _STATIC_RETURNS.get((owner.name, member)) if owner.steps == ('ambient',) else None
        if static is not None:
            return self._platform_result(owner, static)
        found = self.method(owner, member, arguments)
        # A call result is a new value, so it has no origin.
        return replace(found.after(owner), origin=()) if found is not None else None

    # Names

    def _enclosing_class(self):
        position = self.position
        classes = [item for items in self.index.declarations.get(self.source.path, {}).values()
                   for item in items if item.kind == 'class'
                   and item.end - len(item.text) <= position <= item.end]
        return min(classes, key=lambda item: len(item.text)) if classes else None

    def _this_member(self, name):
        declaration = self._enclosing_class()
        found = self._class_member(declaration, name) if declaration else ()
        if not found:
            return None
        return replace(found[0], origin=(declaration.name, name, declaration.source.path))

    def _scopes(self):
        """Return the function and method units around the position, innermost first."""
        units = [unit for unit in self.source.units
                 if unit.start <= self.position < unit.end
                 and unit.kind in {'function', 'method'}]
        return sorted(units, key=lambda unit: unit.end - unit.start)

    def name(self, name):
        """Return the declared type of an identifier at the current position."""
        source, position = self.source, self.position
        for scope in self._scopes():
            text = source.text
            local_text = text[scope.start:position]
            opening = _parameter_list(scope)
            if _shadowed_by_callback(local_text, name,
                                     None if opening is None else opening - scope.start):
                return None
            narrowed = _narrowed(source, scope, name, position)
            if narrowed is not None:
                return narrowed
            declared = None
            pattern = rf'\b(?:const|let|var)\s+{re.escape(name)}\b(?!\s+(?:of|in)\b)\s*(:)?'
            for match in re.finditer(pattern, local_text):
                declared = match
            loop = None
            for match in re.finditer(rf'\bfor\s*\(\s*(?:const|let|var)\s+{re.escape(name)}\s+of\s+',
                                     local_text):
                loop = match
            if loop is not None and (declared is None or loop.start() > declared.start()):
                start = scope.start + loop.end()
                closing = _close(text, text.rfind('(', 0, start))
                iterable = self.expression(text[start:closing], source, start)
                return _element(iterable, f'{name} of {_short(text[start:closing])}')
            if declared is not None:
                cursor = scope.start + declared.end()
                line = f'{source.path}:{_line(source, cursor)}'
                if declared.group(1):
                    end = _annotation_end(text, cursor)
                    annotation = text[cursor:end].strip()
                    found = self.parse(annotation, source.path, f'{name}: {_short(annotation)} ({line})')
                    if found is not None:
                        return replace(found, origin=())
                    cursor = end
                assign = re.match(r'\s*=(?!=)\s*', text[cursor:])
                if not assign:
                    return None
                start = cursor + assign.end()
                value = text[start:_statement_end(text, start)]
                found = self.expression(value, source, start)
                # Keep the origin so `const entries = this.entries` still refers to shared state.
                return found.note(f'{name} = {_short(value)} ({line})', first=True) if found else None
            if opening is not None:
                for parameter, annotation, default in _parameters(text, opening):
                    if parameter != name:
                        continue
                    line = f'{source.path}:{_line(source, opening)}'
                    if annotation:
                        found = self.parse(annotation, source.path,
                                           f'{name}: {_short(annotation)} ({line})')
                        return replace(found, origin=()) if found else None
                    if default:
                        found = self.expression(default, source, opening)
                        return replace(found.note(f'{name} = {_short(default)} ({line})', first=True),
                                       origin=()) if found else None
                    return None
        declaration = self.index.lookup(name, source.path, {'value', 'function', 'class'})
        if declaration is None:
            if name in self.ambient:
                return Type(name, steps=('ambient',))
            return None
        if declaration.kind != 'value':
            return None
        line = f'{declaration.source.path}:{_line(declaration.source, declaration.offset)}'
        # Module-level bindings are shared state.
        origin = (None, name, declaration.source.path)
        if declaration.annotation:
            found = self.parse(declaration.annotation, declaration.source.path,
                               f'{name}: {_short(declaration.annotation)} ({line})')
        else:
            found = self.expression(declaration.text, declaration.source, declaration.offset)
            found = found.note(f'{name} = {_short(declaration.text)} ({line})', first=True) \
                if found else None
        if found is None:
            return None
        return replace(found, origin=origin,
                       declared=name if found.name == '{=}' else found.declared)

    def function(self, name):
        """Return the declared return type of calling a function."""
        for scope in self._scopes():
            if re.search(rf'\b(?:const|let|var|function)\s+{re.escape(name)}\b',
                         self.source.text[scope.start:self.position]):
                return None
        declaration = self.index.lookup(name, self.source.path, {'value', 'function'})
        if declaration is None:
            result = _GLOBAL_RETURNS.get(name) if name in self.ambient else None
            return Type(result) if result else None
        line = f'{declaration.source.path}:{_line(declaration.source, declaration.offset)}'
        annotation = declaration.annotation
        if declaration.kind == 'value':
            arrow = re.match(r'(?:async\s+)?(?:<[^>]*>\s*)?\(', declaration.text)
            if declaration.annotation or not arrow:
                return None
            annotation = _return_annotation(declaration.text, arrow.end() - 1)
        return self.parse(annotation, declaration.source.path,
                          f'{name}(): {_short(annotation)} ({line})') if annotation else None


def _agree(types):
    """Return the type if all alternatives agree, else None."""
    if not types or any(item is None for item in types):
        return None
    if len({(item.name, item.body, item.path if item.name in {'{}', '{=}'} else '')
            for item in types}) != 1:
        return None
    first = types[0]
    for item in types[1:]:
        for step in item.steps:
            first = first.note(step)
    return first


def _element(iterable, note):
    if iterable is None or iterable.name not in _ITERABLE or not iterable.args:
        return None
    element = iterable.args[0]
    return element.after(iterable).note(note, first=True) if element is not None else None


def _arithmetic(text):
    """Return True for a top-level -, *, / or % expression, which is always a number."""
    for index, character, depth in _scan(text):
        if depth != 0 or index == 0 or character not in '-*/%':
            continue
        before, after = text[index - 1], text[index + 1:index + 2]
        if character == '-' and (before in '-=(' or after in '-='):
            continue
        if character in '*/' and (before in '*/' or after in '*/='):
            continue
        if character == '/' and before == '(':
            continue
        return True
    return False


_GUARDS = (
    (r'Array\.isArray\(\s*{name}\s*\)', lambda match: Type('Array', (None,))),
    (r'typeof\s+{name}\s*===?\s*([\'"])(string|number|boolean|bigint)\1',
     lambda match: Type(_PRIMITIVES[match.group(2)])),
)


def _narrowed(source, scope, name, position):
    """Return the type a guard narrows name to at position, or None.

    Handles Array.isArray and typeof checks in an if condition or ?: test,
    alone or joined with &&. Conditions using || or negation are ignored.
    """
    text = source.text
    escaped = re.escape(name)
    for pattern, typed in _GUARDS:
        guard = re.compile(pattern.format(name=escaped))
        for match in guard.finditer(text, scope.start, position):
            condition = _guard_condition(text, match)
            if condition is None:
                continue
            kind, start, end = condition
            if not all(guard.fullmatch(part.strip()) or name not in part
                       for part in re.split(r'&&', text[start:end])) \
                    or '||' in text[start:end] or re.search(rf'!\s*{escaped}\b|!\s*\(?\s*Array', text[start:end]):
                continue
            body = _guarded_body(text, kind, end)
            if body and body[0] <= position < body[1]:
                line = _line(source, match.start())
                return typed(match).note(
                    f'{name} narrowed by {_short(match.group())} ({source.path}:{line})')
    return None


def _guard_condition(text, match):
    """Return ('if' or '?', start, end) for the condition containing match, or None."""
    opening = text.rfind('(', 0, match.start())
    while opening >= 0:
        closing = _close(text, opening)
        if closing >= match.end():
            if re.search(r'\bif\s*$', text[:opening]):
                return 'if', opening + 1, closing
            break
        opening = text.rfind('(', 0, opening)
    line_start = max(text.rfind('\n', 0, match.start()), text.rfind('return', 0, match.start()),
                     text.rfind('=', 0, match.start()) if text[match.start() - 1:match.start()] != '=' else -1)
    after = re.match(r'\s*\?(?![.?])', text[match.end():])
    if after:
        return '?', line_start + 1, match.end()
    return None


def _guarded_body(text, kind, end):
    """(start, end) of the branch a guard protects."""
    if kind == '?':
        start = text.find('?', end) + 1
        for index, character, depth in _scan(text, start):
            if depth < 0 or (depth == 0 and character in ':;,'):
                return start, index
        return start, len(text)
    cursor = end + 1
    blank = len(text[cursor:]) - len(text[cursor:].lstrip())
    cursor += blank
    if text[cursor:cursor + 1] == '{':
        return cursor, _close(text, cursor)
    return cursor, _statement_end(text, cursor)


def _ternary(text):
    """Return True if text is a top-level conditional expression."""
    for index, character, depth in _scan(text):
        if depth == 0 and character == '?' and text[index + 1:index + 2] not in {'.', '?'} \
                and text[index - 1:index] != '?':
            return True
    return False


def _shadowed_by_callback(text, name, own=None):
    """Return True if an inline callback parameter shadows name at the end of text.

    own is the offset of the unit's own parameter list, which is skipped.
    """
    escaped = re.escape(name)
    for match in re.finditer(rf'(?:\(([^()]*)\)|\b({escaped}))\s*(?::[^=()]*)?=>', text):
        if own is not None and match.start() == own:
            continue
        if match.group(1) is not None and not re.search(rf'(?:^|[\s,(]){escaped}\s*[,:?)=]|(?:^|[\s,]){escaped}\s*$',
                                                         match.group(1)):
            continue
        body = match.end()
        stripped = len(text[body:]) - len(text[body:].lstrip())
        if text[body + stripped:body + stripped + 1] == '{':
            closing = _close(text, body + stripped)
            if closing >= len(text):
                return True
            continue
        for _index, character, depth in _scan(text, body):
            if depth < 0 or (depth == 0 and character in ',;'):
                break
        else:
            return True
    return False


def _parameter_list(unit):
    """Return the offset of the ( that opens the unit's parameter list."""
    text = unit.text
    match = re.match(rf'\s*(?:(?:export|default|async|static|public|private|protected|'
                     rf'readonly|override|get|set)\s+)*(?:function\s*\*?\s*)?'
                     rf'(?:(?:const|let|var)\s+)?#?(?:{_IDENTIFIER})?\s*(?::[^=]*)?'
                     rf'(?:=\s*(?:async\s+)?)?(?:<[^(]*>)?\s*\(', text)
    if match:
        return unit.start + match.end() - 1
    return None


def _short(text, limit=48):
    text = re.sub(r'\s+', ' ', text.strip())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


# Entry points

def prepare(sources):
    """Build one declaration index shared by all TypeScript sources."""
    # JavaScript initializers aren't type declarations, so only index TypeScript.
    typed = [source for source in sources if source.language in TYPED_LANGUAGES]
    index = _Index(typed)
    for source in typed:
        source.ts_type_index = index


def receiver_type(unit, receiver, position):
    """Return the declared Type of receiver at absolute offset position, or None."""
    index = getattr(unit.source, 'ts_type_index', None)
    if index is None or not receiver:
        return None
    try:
        return _Evaluator(index, unit).expression(receiver, unit.source, position)
    except RecursionError:
        return None


# Collection methods that modify contents, and those that only read them.
_COLLECTION_WRITES = {
    'Map': {'set', 'delete', 'clear'}, 'WeakMap': {'set', 'delete'},
    'Set': {'add', 'delete', 'clear'}, 'WeakSet': {'add', 'delete'},
    'Array': {'push', 'pop', 'shift', 'unshift', 'splice', 'sort', 'reverse', 'fill',
              'copyWithin'},
}
_COLLECTION_READS = {
    'Map': {'get', 'has', 'keys', 'values', 'entries', 'forEach'}, 'WeakMap': {'get', 'has'},
    'Set': {'has', 'keys', 'values', 'entries', 'forEach'}, 'WeakSet': {'has'},
    'Array': {'at', 'concat', 'entries', 'every', 'filter', 'find', 'findIndex', 'findLast',
              'findLastIndex', 'flat', 'flatMap', 'forEach', 'includes', 'indexOf', 'join',
              'keys', 'lastIndexOf', 'map', 'reduce', 'reduceRight', 'slice', 'some',
              'toReversed', 'toSorted', 'toSpliced', 'values', 'with'},
}


@dataclass(frozen=True)
class StoreAccess:
    """A read or write of in-process state held in a platform collection."""
    kind: str          # data_read | data_write
    store: str         # path::Owner.member or path::name
    collection: str    # Map, Set, Array...
    steps: tuple


def store_access(unit, receiver, name, position):
    """Return the StoreAccess a call performs, or None.

    The receiver must be a platform collection held in shared state (class
    member, module binding, or member of a module-level object) that some code
    in the repo writes. Collections nothing writes are treated as constants.
    """
    access = _cached_access(unit, receiver, name, position)
    index = getattr(unit.source, 'ts_type_index', None)
    if access is None or index is None:
        return None
    return access if access.store in _written_stores(index) else None


def store_written(unit, store):
    """Return True if any code in the repo writes store."""
    index = getattr(unit.source, 'ts_type_index', None)
    return index is not None and store in _written_stores(index)


def _cached_access(unit, receiver, name, position):
    cache = getattr(unit.source, 'ts_store_accesses', None)
    if cache is None:
        cache = unit.source.ts_store_accesses = {}
    key = (position, name, receiver)
    if key not in cache:
        cache[key] = _store_access(unit, receiver, name, position)
    return cache[key]


_TRUNCATION = re.compile(rf'((?:this\.)?{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})*)\s*\.\s*length\s*=(?!=)')


def truncations(unit):
    """Return unit-relative (start, end, StoreAccess) for each `store.length = n`.

    Assigning an array's length removes elements, so it counts as a write.
    """
    found = []
    text = unit.text
    depths = _depths(text)
    for match in _TRUNCATION.finditer(text):
        if depths[match.start()] is None or not rules.owns(
                unit, unit.start + match.start(), unit.start + match.end()):
            continue
        receiver_type_ = receiver_type(unit, match.group(1), unit.start + match.start())
        if platform(unit, receiver_type_) != 'Array' or not receiver_type_.origin:
            continue
        owner, member, path = receiver_type_.origin
        store = f'{path}::{owner}.{member}' if owner else f'{path}::{member}'
        end = _statement_end(text, match.end())
        found.append((match.start(), end, StoreAccess('data_write', store, 'Array',
                                                      receiver_type_.steps)))
    return found


def _written_stores(index):
    """Return every store written anywhere in the repo, cached on the index."""
    if index.written is None:
        written = set()
        for source in index.sources.values():
            for unit in source.units:
                if unit.kind not in {'function', 'method'}:
                    continue
                written.update(access.store for _start, _end, access in truncations(unit))
                for call in rules.calls(unit):
                    if not call['receiver']:
                        continue
                    access = _cached_access(unit, call['receiver'], call['name'],
                                            unit.start + call['position'])
                    if access is not None and access.kind == 'data_write':
                        written.add(access.store)
        index.written = frozenset(written)
    return index.written


def _store_access(unit, receiver, name, position):
    found = receiver_type(unit, receiver, position)
    provided = platform(unit, found)
    if provided not in _COLLECTION_WRITES or not found.origin:
        return None
    kind = ('data_write' if name in _COLLECTION_WRITES[provided] else
            'data_read' if name in _COLLECTION_READS[provided] else None)
    if kind is None:
        return None
    owner, member, path = found.origin
    store = f'{path}::{owner}.{member}' if owner else f'{path}::{member}'
    return StoreAccess(kind, store, provided, found.steps)


def platform(unit, found):
    """Return the platform type name of found, or None for a repo type."""
    if found is None:
        return None
    ambient = registry.ambient_globals(unit.source.language)
    return found.name if found.name in ambient and found.steps != ('ambient',) else None
