"""Repository-digest refresh progress contract tests."""
from contextlib import contextmanager

from lib.context import repository_digest_build
from lib.context.business_domain_schema import limits, record, settings


def test_failed_discovery_labels_the_written_fallback_digest(
        tmp_path, monkeypatch):
    context = tmp_path/'.speed/context'
    context.mkdir(parents=True)
    (context/'project-map.json').write_text('{}')

    status = record(
        'StatusArtifact', phase='failed',
        coverage=record(
            'Coverage', anchors_total=52, anchors_processed=0,
            anchors_pending=52),
        limits=limits(settings(None)),
        error=record(
            'Error', code='SEMANTIC_VERIFICATION_FAILED',
            message='Candidate did not pass verification'))
    digest = {
        'status': 'partial',
        'domains': [],
        'entrypoints': [],
        'warnings': [],
    }

    @contextmanager
    def lease(_root):
        yield

    monkeypatch.setattr(
        repository_digest_build, 'reserve_digest_build', lease)
    monkeypatch.setattr(
        repository_digest_build, 'discover',
        lambda *_args, **_kwargs: (None, status))
    monkeypatch.setattr(
        repository_digest_build, 'build_repository_digest',
        lambda *_args, **_kwargs: digest)

    progress = []
    result = repository_digest_build.refresh_digest(
        tmp_path, config={}, progress=progress.append)

    written = next(
        event for event in progress
        if event['message'].startswith('Repository digest written:'))
    assert result['outcome'] == 'failed'
    assert written == {
        'stage': 'digest',
        'message': (
            'Repository digest written: 0 domains, 0 entrypoints; '
            'digest status=partial, discovery phase=failed'),
        'level': 'warning',
        'details': {
            'domain_count': 0,
            'entrypoint_count': 0,
            'digest_status': 'partial',
            'discovery_phase': 'failed',
        },
    }
