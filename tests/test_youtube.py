import json
from unittest.mock import MagicMock, Mock

import pytest

from backend.youtube import current_channel, existing_upload, upload_body, upload_video
from backend.youtube_auth import SCOPES, YouTubeError, load_credentials, save_token

CHANNEL = 'UCw3H9KY5toxOuN7cSDsIKqA'


@pytest.fixture
def body():
    return upload_body({'title': 'Home 2–1 Away | Match numbers', 'summary': 'The recorded score was Home 2, Away 1.'})


@pytest.fixture
def service():
    service = MagicMock()
    service.channels.return_value.list.return_value.execute.return_value = {
        'items': [{'id': CHANNEL, 'snippet': {'title': 'Football Shorts'}}]}
    service.videos.return_value.insert.return_value.next_chunk.return_value = (
        None, {'id': 'abcdefghijk', 'status': {'privacyStatus': 'private'}})
    return service


def test_private_disclosed_metadata(body):
    assert body['status'] == {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': True}
    assert 'AI-generated voice' in body['snippet']['description']
    assert '#Shorts' in body['snippet']['description']
    assert body['snippet']['categoryId'] == '17'


@pytest.mark.parametrize('privacy', ['private', 'unlisted', 'public'])
def test_explicit_privacy(privacy):
    assert upload_body({'title': 'Match', 'summary': 'Facts.'}, privacy)['status']['privacyStatus'] == privacy


@pytest.mark.parametrize('title', ['', 'x'*101, 'a<b'])
def test_invalid_title(title):
    with pytest.raises(YouTubeError):
        upload_body({'title': title, 'summary': 'Facts.'})


def test_channel_identity(service):
    assert current_channel(service)['id'] == CHANNEL
    assert service.channels.return_value.list.call_args.kwargs['mine'] is True


def test_channel_mismatch_prevents_upload(tmp_path, service, body):
    service.channels.return_value.list.return_value.execute.return_value['items'][0]['id'] = 'UC' + 'x'*22
    with pytest.raises(YouTubeError, match='does not match'):
        upload_video(service, tmp_path/'video.mp4', body, CHANNEL, 'hash', tmp_path/'receipt.json')
    service.videos.assert_not_called()
    assert not (tmp_path/'receipt.json').exists()


def test_resumable_upload_and_duplicate_guard(tmp_path, service, body):
    video = tmp_path/'video.mp4'
    video.write_bytes(b'fake-video')
    path = tmp_path/'receipt.json'
    receipt, reused = upload_video(service, video, body, CHANNEL, 'hash', path)
    assert reused is False
    assert receipt['video_id'] == 'abcdefghijk'
    assert receipt['requested_privacy'] == 'private'
    assert receipt['processing_verified'] is False
    kwargs = service.videos.return_value.insert.call_args.kwargs
    assert kwargs['notifySubscribers'] is False
    assert kwargs['media_body'].resumable() is True
    assert kwargs['body'] == body
    assert service.videos.return_value.insert.return_value.next_chunk.call_args.kwargs['num_retries'] == 3
    receipt2, reused = upload_video(service, video, body, CHANNEL, 'hash', path)
    assert reused is True and receipt2['video_id'] == receipt['video_id']
    assert service.videos.return_value.insert.call_count == 1


def test_intermediate_chunk_does_not_start_new_insert(tmp_path, service, body):
    video = tmp_path/'video.mp4'
    video.write_bytes(b'fake-video')
    service.videos.return_value.insert.return_value.next_chunk.side_effect = [
        (Mock(), None), (None, {'id': 'abcdefghijk', 'status': {'privacyStatus': 'private'}})]
    upload_video(service, video, body, CHANNEL, 'hash', tmp_path/'receipt.json')
    assert service.videos.return_value.insert.call_count == 1
    assert service.videos.return_value.insert.return_value.next_chunk.call_count == 2


def test_uncertain_failure_keeps_reservation(tmp_path, service, body):
    video = tmp_path/'video.mp4'
    video.write_bytes(b'fake-video')
    service.videos.return_value.insert.return_value.next_chunk.side_effect = RuntimeError('sensitive-response')
    path = tmp_path/'receipt.json'
    with pytest.raises(YouTubeError) as exc:
        upload_video(service, video, body, CHANNEL, 'hash', path)
    assert 'sensitive-response' not in str(exc.value)
    assert json.loads(path.read_text())['state'] == 'uploading'
    with pytest.raises(YouTubeError, match='uncertain'):
        upload_video(service, video, body, CHANNEL, 'hash', path)
    assert service.videos.return_value.insert.call_count == 1


def test_different_file_or_metadata_is_blocked(tmp_path, service, body):
    video = tmp_path/'video.mp4'
    video.write_bytes(b'fake-video')
    path = tmp_path/'receipt.json'
    upload_video(service, video, body, CHANNEL, 'hash', path)
    with pytest.raises(YouTubeError, match='different'):
        upload_video(service, video, body, CHANNEL, 'new-hash', path)
    assert service.videos.return_value.insert.call_count == 1


def test_missing_token_does_not_start_login(tmp_path, monkeypatch):
    monkeypatch.setenv('YOUTUBE_TOKEN_FILE', str(tmp_path/'missing-token.json'))
    factory = Mock()
    monkeypatch.setattr('backend.youtube_auth.InstalledAppFlow.from_client_secrets_file', factory)
    with pytest.raises(YouTubeError, match='not connected'):
        load_credentials()
    factory.assert_not_called()


def test_missing_client_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('YOUTUBE_CLIENT_SECRETS', str(tmp_path/'missing.json'))
    with pytest.raises(YouTubeError, match='Desktop'):
        load_credentials(login=True)


def test_private_token_permissions(tmp_path):
    path = tmp_path/'secrets'/'token.json'
    save_token(path, '{"refresh_token":"synthetic"}')
    assert path.read_text() == '{"refresh_token":"synthetic"}'
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_channel(service):
    service.channels.return_value.list.return_value.execute.return_value = {'items': []}
    with pytest.raises(YouTubeError):
        current_channel(service)


@pytest.mark.parametrize('reason,explanation', [
    ('uploadLimitExceeded', 'channel upload limit'),
    ('quotaExceeded', 'project quota'),
    ('insufficientPermissions', 'permission is missing'),
])
def test_upload_api_failure_is_actionable_and_safe(tmp_path, service, body, reason, explanation):
    from googleapiclient.errors import HttpError
    import httplib2
    video = tmp_path/'video.mp4'
    video.write_bytes(b'fake-video')
    error = HttpError(httplib2.Response({'status': '403'}), json.dumps({
        'error': {'message': 'SECRET URL AND TOKEN', 'errors': [{'reason': reason}]}}).encode(),
        uri='https://secret-upload-session')
    service.videos.return_value.insert.return_value.next_chunk.side_effect = error
    path = tmp_path/'receipt.json'
    with pytest.raises(YouTubeError) as caught:
        upload_video(service, video, body, CHANNEL, 'hash', path)
    assert explanation in str(caught.value)
    assert reason in str(caught.value)
    assert 'SECRET' not in str(caught.value)
    assert 'secret-upload-session' not in str(caught.value)
    receipt = json.loads(path.read_text())
    assert receipt['state'] == 'uploading'
    assert receipt['failure'] == {'category': 'youtube_api_rejection', 'http_status': 403,
                                  'reason': reason, 'stage': 'sending_upload'}
    with pytest.raises(YouTubeError, match='uncertain'):
        upload_video(service, video, body, CHANNEL, 'hash', path)
    assert service.videos.return_value.insert.call_count == 1


def test_unknown_api_reason_does_not_leak_response():
    from backend.youtube import upload_failure_details
    from googleapiclient.errors import HttpError
    import httplib2
    error = HttpError(httplib2.Response({'status': '500'}),
        b'{"error":{"errors":[{"reason":"secret-value"}],"message":"secret"}}')
    details, message = upload_failure_details(error)
    assert 'secret' not in json.dumps(details) + message
    assert details['http_status'] == 500


def test_interrupted_known_session_resumes_without_second_insert(tmp_path,service,body):
    video=tmp_path/'video.mp4';video.write_bytes(b'fake-video')
    request=service.videos.return_value.insert.return_value
    request.resumable_uri='https://www.googleapis.com/upload/youtube/v3/videos?upload_id=secret-session'
    request._in_error_state=True
    request.next_chunk.side_effect=[OSError('sensitive transport data'),
        (None,{'id':'abcdefghijk','status':{'privacyStatus':'private'}})]
    receipt,_=upload_video(service,video,body,CHANNEL,'hash',tmp_path/'receipt.json')
    assert receipt['state']=='uploaded'
    assert service.videos.return_value.insert.call_count==1
    assert request.next_chunk.call_count==2


def test_session_recovery_is_bounded_and_capability_url_is_never_logged(tmp_path,service,body):
    video=tmp_path/'video.mp4';video.write_bytes(b'fake-video')
    request=service.videos.return_value.insert.return_value
    request.resumable_uri='https://www.googleapis.com/upload/youtube/v3/videos?upload_id=secret-session'
    request.resumable_progress=256
    request._in_error_state=True
    request.next_chunk.side_effect=OSError('secret transport detail')
    path=tmp_path/'receipt.json'
    with pytest.raises(YouTubeError) as caught:
        upload_video(service,video,body,CHANNEL,'hash',path)
    assert 'secret' not in str(caught.value)
    assert request.next_chunk.call_count==3
    assert service.videos.return_value.insert.call_count==1
    saved=json.loads(path.read_text())
    assert saved['resumable_uri']==request.resumable_uri
    assert saved['failure']['category']=='upload_connection_failure'
    assert saved['confirmed_bytes']==256
    assert saved['file_size']==len(b'fake-video')
    assert saved['state']=='uploading'


def test_unknown_session_cannot_be_blindly_retried(tmp_path,service,body):
    video=tmp_path/'video.mp4';video.write_bytes(b'fake-video')
    request=service.videos.return_value.insert.return_value
    request.resumable_uri=None
    request.next_chunk.side_effect=OSError('private detail')
    with pytest.raises(YouTubeError):upload_video(service,video,body,CHANNEL,'hash',tmp_path/'receipt.json')
    assert request.next_chunk.call_count==1
    assert service.videos.return_value.insert.call_count==1
