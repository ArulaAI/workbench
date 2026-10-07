"""Normalize TypeScript module-resolution supporting inputs without I/O."""
from pathlib import PurePosixPath

from .base import SupportingConsumerResult
from ..layer1_domain_clustering import (TypeScriptModuleResolutionError,
    normalize_typescript_path_target, parse_typescript_module_resolution)


def _scope(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return '.' if parent in {'', '.'} else parent


def _kind(path: str) -> str:
    name = PurePosixPath(path).name
    if name == 'tsconfig.json':
        return 'tsconfig'
    if name == 'typings.json':
        return 'typings'
    raise ValueError('invalid_typescript_module_resolution_path')


def consume(supporting_sources, primary_sources) -> SupportingConsumerResult:
    del primary_sources
    consumed, inputs, diagnostics = [], [], []
    for source in sorted(supporting_sources, key=lambda item: item.resource_id):
        try:
            kind, scope = _kind(source.path), _scope(source.path)
            normalized = parse_typescript_module_resolution(source.text, kind)
            for alias in normalized['aliases']:
                for target in alias['targets']:
                    normalize_typescript_path_target(
                        scope, target['pattern'], 'probe')
        except TypeScriptModuleResolutionError as error:
            start, end = ((0, len(source.text))
                if error.cause == 'target_escapes_repository'
                else (error.start, error.end))
            diagnostics.append({'source_id': source.resource_id,
                'code': 'TYPESCRIPT_MODULE_RESOLUTION_INVALID',
                'reason': error.cause, 'span': (start, end)})
            continue
        except ValueError as error:
            diagnostics.append({'source_id': source.resource_id,
                'code': 'TYPESCRIPT_MODULE_RESOLUTION_INVALID',
                'reason': str(error), 'span': (0, len(source.text))})
            continue
        consumed.append(source.resource_id)
        inputs.append({'source_id': source.resource_id, 'scope_dir': scope,
            'document_kind': kind, **normalized})
    return SupportingConsumerResult(tuple(consumed), tuple(inputs),
        tuple(diagnostics))
