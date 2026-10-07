"""Normalize installed package.json supporting inputs without I/O."""
import json
from dataclasses import dataclass
from pathlib import PurePosixPath

from .base import SupportingConsumerResult


class PackageJsonError(ValueError):
    def __init__(self, cause: str, start: int, end: int):
        super().__init__(cause)
        self.cause, self.start, self.end = cause, start, end


@dataclass(frozen=True)
class PackageManifest:
    engines: tuple[dict, ...]
    dependencies: tuple[dict, ...]


def _object_section(data, name, text, strict):
    value = data.get(name, {})
    if not isinstance(value, dict):
        if strict:
            raise PackageJsonError(f'{name}_must_be_object', 0, len(text))
        return {}
    if strict and not all(isinstance(item, str) for item in value.values()):
        raise PackageJsonError(f'{name}_values_must_be_strings', 0, len(text))
    return {key: item if isinstance(item, str) else None
            for key, item in value.items()}


def parse_package_json(text: str, sections=('engines', 'dependencies',
        'devDependencies'), strict=True) -> PackageManifest:
    """Read engines and dependency constraints; scripts are never read.

    Strict parsing rejects a malformed selected section. Tolerant parsing keeps
    the other sections and represents a nonstring constraint as null.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        start = min(error.pos, len(text))
        raise PackageJsonError('json_syntax_invalid', start,
            min(start + 1, len(text))) from None
    if not isinstance(data, dict):
        raise PackageJsonError('top_level_must_be_object', 0, len(text))
    allowed = {'engines', 'dependencies', 'devDependencies'}
    if (not isinstance(sections, (tuple, list)) or not sections
            or set(sections) - allowed):
        raise ValueError('package_sections_invalid')
    engines = (_object_section(data, 'engines', text, strict)
        if 'engines' in sections else {})
    runtime = (_object_section(data, 'dependencies', text, strict)
        if 'dependencies' in sections else {})
    development = (_object_section(data, 'devDependencies', text, strict)
        if 'devDependencies' in sections else {})
    return PackageManifest(
        tuple({'name': name, 'constraint': constraint}
            for name, constraint in sorted(engines.items())),
        tuple(sorted((
            *({'name': name, 'constraint': constraint,
               'dependency_kind': 'runtime'}
              for name, constraint in runtime.items()),
            *({'name': name, 'constraint': constraint,
               'dependency_kind': 'development'}
              for name, constraint in development.items()),
        ), key=lambda item: (item['name'],
            0 if item['dependency_kind'] == 'runtime' else 1,
            item['constraint'] or ''))),
    )


def _scope(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return '.' if parent in {'', '.'} else parent


def consume(supporting_sources, primary_sources) -> SupportingConsumerResult:
    del primary_sources
    consumed, inputs, diagnostics = [], [], []
    for source in sorted(supporting_sources, key=lambda item: item.resource_id):
        try:
            manifest = parse_package_json(source.text)
        except PackageJsonError as error:
            diagnostics.append({'source_id': source.resource_id,
                'code': 'PACKAGE_JSON_INVALID', 'reason': error.cause,
                'span': (error.start, error.end)})
            continue
        consumed.append(source.resource_id)
        inputs.append({
            'source_id': source.resource_id,
            'scope_dir': _scope(source.path),
            'document_kind': 'package',
            'engines': list(manifest.engines),
            'dependencies': list(manifest.dependencies),
        })
    return SupportingConsumerResult(tuple(consumed), tuple(inputs),
        tuple(diagnostics))
