"""Deterministic Java Properties source adapter."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .base import ConfigurationDeclaration, DecodedSource, Source, Unit
from ..business_domain_schema import digest

_APPLICATION = re.compile(r'application(?:-([^/]+))?\.properties\Z')
_MESSAGES = re.compile(r'messages(?:_[^/]+)?\.properties\Z')
_SPACE = ' \t\f'
_ESCAPES = {'t': '\t', 'n': '\n', 'r': '\r', 'f': '\f'}


@dataclass(frozen=True)
class _LogicalLine:
    text: str
    offsets: tuple[int, ...]
    start: int
    end: int


class _PropertiesSyntaxError(ValueError):
    def __init__(self, cause: str, start: int, end: int):
        super().__init__(cause)
        self.cause, self.start, self.end = cause, start, end


def decode(raw: bytes) -> DecodedSource:
    try:
        text, encoding = raw.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        text, encoding = raw.decode('iso-8859-1'), 'iso-8859-1'
    return DecodedSource(text, encoding, len(raw))


def _physical_lines(text: str):
    cursor = 0
    while cursor < len(text):
        start = cursor
        while cursor < len(text) and text[cursor] not in '\r\n':
            cursor += 1
        end = cursor
        if cursor < len(text):
            if text[cursor] == '\r' and cursor + 1 < len(text) \
                    and text[cursor + 1] == '\n':
                cursor += 2
            else:
                cursor += 1
        yield start, end
    if not text:
        return


def _logical_lines(text: str):
    chars, offsets = [], []
    logical_start = None
    for physical_start, physical_end in _physical_lines(text):
        body_start = physical_start
        comment_cursor = physical_start
        while comment_cursor < physical_end and text[comment_cursor] in _SPACE:
            comment_cursor += 1
        is_comment = (logical_start is None and comment_cursor < physical_end
            and text[comment_cursor] in '#!')
        if logical_start is not None:
            while body_start < physical_end and text[body_start] in _SPACE:
                body_start += 1
        body = text[body_start:physical_end]
        slash_count = len(body) - len(body.rstrip('\\'))
        continued = not is_comment and slash_count % 2 == 1
        if continued:
            body = body[:-1]
        if logical_start is None:
            logical_start = physical_start
        chars.extend(body)
        offsets.extend(range(body_start, body_start + len(body)))
        if not continued:
            yield _LogicalLine(''.join(chars), tuple(offsets), logical_start,
                physical_end)
            chars, offsets, logical_start = [], [], None
    if logical_start is not None:
        yield _LogicalLine(''.join(chars), tuple(offsets), logical_start,
            len(text))


def _split_declaration(line: str):
    cursor = 0
    while cursor < len(line) and line[cursor] in _SPACE:
        cursor += 1
    if cursor == len(line) or line[cursor] in '#!':
        return None
    key_start, escaped = cursor, False
    while cursor < len(line):
        char = line[cursor]
        if not escaped and (char in '=:' or char in _SPACE):
            break
        if char == '\\':
            escaped = not escaped
        else:
            escaped = False
        cursor += 1
    key_end = cursor
    whitespace_separator = cursor < len(line) and line[cursor] in _SPACE
    while cursor < len(line) and line[cursor] in _SPACE:
        cursor += 1
    if cursor < len(line) and line[cursor] in '=:' \
            and (whitespace_separator or cursor == key_end):
        cursor += 1
    while cursor < len(line) and line[cursor] in _SPACE:
        cursor += 1
    return key_start, key_end, cursor, len(line)


def _span(offsets, start, end, fallback):
    if start < len(offsets):
        first = offsets[start]
        last = offsets[min(max(start, end - 1), len(offsets) - 1)] + 1
        return first, last
    return fallback, fallback


def _unicode_escape(text, offsets, cursor, end, fallback):
    finish = cursor + 6
    if finish > end or text[cursor + 1] != 'u' \
            or not re.fullmatch(r'[0-9a-fA-F]{4}', text[cursor + 2:finish]):
        start, stop = _span(offsets, cursor, min(end, finish), fallback)
        raise _PropertiesSyntaxError('invalid_unicode_escape', start, stop)
    return int(text[cursor + 2:finish], 16), finish


def _decode_token(text, offsets, start, end, fallback):
    value, cursor = [], start
    while cursor < end:
        if text[cursor] != '\\':
            codepoint, finish = ord(text[cursor]), cursor + 1
        elif cursor + 1 >= end:
            start_offset, stop = _span(offsets, cursor, cursor + 1, fallback)
            raise _PropertiesSyntaxError('truncated_escape', start_offset, stop)
        elif text[cursor + 1] == 'u':
            codepoint, finish = _unicode_escape(text, offsets, cursor, end, fallback)
        else:
            value.append(_ESCAPES.get(text[cursor + 1], text[cursor + 1]))
            cursor += 2
            continue
        if 0xD800 <= codepoint <= 0xDBFF:
            if finish >= end or text[finish:finish + 2] != '\\u':
                first, last = _span(offsets, cursor, finish, fallback)
                raise _PropertiesSyntaxError('lone_high_surrogate', first, last)
            low, low_finish = _unicode_escape(text, offsets, finish, end, fallback)
            if not 0xDC00 <= low <= 0xDFFF:
                first, last = _span(offsets, finish, low_finish, fallback)
                raise _PropertiesSyntaxError('invalid_surrogate_pair', first, last)
            codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00
            finish = low_finish
        elif 0xDC00 <= codepoint <= 0xDFFF:
            first, last = _span(offsets, cursor, finish, fallback)
            raise _PropertiesSyntaxError('lone_low_surrogate', first, last)
        value.append(chr(codepoint))
        cursor = finish
    return ''.join(value)


def _source_spans(offsets):
    spans = []
    for offset in offsets:
        if spans and offset == spans[-1][1]:
            spans[-1] = (spans[-1][0], offset + 1)
        else:
            spans.append((offset, offset + 1))
    return tuple(spans)


def _configuration_scope(path: str):
    parts = PurePosixPath(path).parts
    locations = [index for index in range(len(parts) - 3)
        if parts[index] == 'src' and parts[index + 1] in {'main', 'test'}
        and parts[index + 2] == 'resources']
    if len(locations) != 1:
        raise ValueError('invalid_configuration_path')
    environment = parts[locations[0] + 1]
    name = parts[-1]
    application = _APPLICATION.fullmatch(name)
    if application:
        return environment, application.group(1), 'application_configuration'
    if _MESSAGES.fullmatch(name):
        return environment, None, 'message_catalog'
    raise ValueError('invalid_configuration_path')


def extract(source: Source) -> list[Unit]:
    environment, profile, role = _configuration_scope(source.path)
    units, occurrences = [], {}
    pending_diagnostics = []
    source.java_properties_diagnostics = pending_diagnostics
    skip_bom_declaration = source.text.startswith('\ufeff')
    if skip_bom_declaration:
        pending_diagnostics.append({
            'code': 'JAVA_PROPERTIES_SYNTAX_INVALID',
            'reason': 'byte_order_mark_not_supported', 'span': (0, 1)})
    for logical in _logical_lines(source.text):
        declaration = _split_declaration(logical.text)
        if declaration is None:
            continue
        key_start, key_end, value_start, value_end = declaration
        if skip_bom_declaration and logical.start == 0:
            skip_bom_declaration = False
            continue
        try:
            key = _decode_token(logical.text, logical.offsets,
                key_start, key_end, logical.end)
            value = _decode_token(logical.text, logical.offsets,
                value_start, value_end, logical.end)
        except _PropertiesSyntaxError as error:
            pending_diagnostics.append({
                'code': 'JAVA_PROPERTIES_SYNTAX_INVALID',
                'reason': error.cause, 'span': (error.start, error.end)})
            continue
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        configuration = ConfigurationDeclaration(key, value, occurrence,
            profile, environment, role,
            _source_spans(logical.offsets[value_start:value_end]))
        units.append(Unit(source=source, name=key,
            qualified='property:' + digest([source.path, key, occurrence]),
            start=logical.start, end=logical.end, kind='field',
            configuration=configuration))
    return units


def bindings(unit: Unit):
    declaration = unit.configuration
    if declaration is None:
        return []
    return [{
        'name': declaration.key,
        'value_type': 'string',
        'direction': 'internal',
        'expression': declaration.value,
        'scope': {
            'environment': declaration.environment,
            'tenant': None,
            'actor': None,
            'profile': declaration.profile,
            'effective_from': None,
            'effective_to': None,
            'version': None,
            'entrypoint_ids': None,
        },
        'resolution': 'unresolved',
        'reason': 'Repository declaration retained; effective precedence was not evaluated.',
    }]


def diagnostics(source):
    return list(getattr(source, 'java_properties_diagnostics', ()))


def symbol_key(name):
    return name


def calls(unit):
    return []


def candidates(unit, receiver, name, available, position=None):
    return []


def resources(unit):
    return []


def observations(unit):
    return []


def operations(unit):
    return []
