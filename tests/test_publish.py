from unittest.mock import Mock

import pytest

from backend.publish import main


@pytest.fixture
def prepared(tmp_path):
    video = tmp_path/'video.mp4'
    video.write_bytes(b'fake-video')
    return video, {'fixture_id': 19427552, 'video_sha256': 'hash',
        'body': {'snippet': {'title': 'Home 2–1 Away'}, 'status': {'privacyStatus': 'private'}}}


def test_dry_run_has_no_google_access(tmp_path, prepared, monkeypatch):
    monkeypatch.setattr('backend.publish.prepare_upload', lambda *args: prepared)
    auth = Mock()
    monkeypatch.setattr('backend.publish.load_credentials', auth)
    assert main(['--fixture', '19427552', '--artifacts-dir', str(tmp_path)]) == 0
    auth.assert_not_called()
    assert (tmp_path/'19427552_youtube_plan.json').exists()
    assert not (tmp_path/'19427552_youtube_upload.json').exists()


def test_upload_requires_channel(tmp_path, prepared, monkeypatch):
    monkeypatch.setattr('backend.publish.prepare_upload', lambda *args: prepared)
    monkeypatch.setenv('YOUTUBE_CHANNEL_ID', '')
    auth = Mock()
    monkeypatch.setattr('backend.publish.load_credentials', auth)
    assert main(['--fixture', '19427552', '--artifacts-dir', str(tmp_path), '--upload']) == 1
    auth.assert_not_called()


def test_missing_pipeline_files(tmp_path):
    assert main(['--fixture', '19427552', '--artifacts-dir', str(tmp_path), '--data-dir', str(tmp_path)]) == 1
