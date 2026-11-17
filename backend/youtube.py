"""YouTube metadata and duplicate-resistant resumable upload."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from backend.main import save_json
from backend.speech import DISCLOSURE
from backend.youtube_auth import YouTubeError

CHANNEL_PATTERN = re.compile(r'UC[A-Za-z0-9_-]{22}')
VIDEO_PATTERN = re.compile(r'[A-Za-z0-9_-]{11}')


def current_channel(service):
    try:
        response = service.channels().list(part='id,snippet', mine=True).execute(num_retries=2)
        items = response.get('items', [])
        if len(items) != 1 or not CHANNEL_PATTERN.fullmatch(items[0]['id']):
            raise YouTubeError('Select a single YouTube channel with a valid channel ID during authorization.')
        return {'id': items[0]['id'], 'title': items[0]['snippet']['title']}
    except YouTubeError:
        raise
    except Exception:
        raise YouTubeError('Unable to verify the authorized YouTube channel; check API access and authorization.') from None


def upload_body(analysis, privacy='private', made_for_kids=False):
    if privacy not in ('private', 'unlisted', 'public') or type(made_for_kids) is not bool:
        raise YouTubeError('Invalid upload privacy or audience setting.')
    # Source title/summary are already checked against pipeline artifacts by publish.py.
    title = analysis['title'].strip()
    description = (f"{analysis['summary']}\n\n{DISCLOSURE}\n"
        'This graphic recap uses recorded match statistics. Aggregate numbers do not establish tactics or causation.\n'
        'Match data: Sportmonks.\n\n#Shorts #PremierLeague #Football')
    if not title or len(title) > 100 or any(char in title for char in '<>'):
        raise YouTubeError('Upload title must contain 1–100 characters and no angle brackets.')
    if len(description.encode('utf-8')) > 5000 or any(char in description for char in '<>'):
        raise YouTubeError('Upload description exceeds YouTube limits or contains angle brackets.')
    return {'snippet': {'title': title, 'description': description,
                        'categoryId': '17', 'defaultLanguage': 'en',
                        'tags': ['football', 'Premier League', 'match analysis', 'Shorts']},
            'status': {'privacyStatus': privacy, 'selfDeclaredMadeForKids': made_for_kids,
                       'containsSyntheticMedia': True}}


def existing_upload(receipt_path, expected):
    if not receipt_path.exists():
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('state') != 'uploaded':
            raise YouTubeError('An upload is pending or uncertain. Check YouTube Studio before any retry; do not delete the upload record blindly.')
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise YouTubeError('An upload record already exists with different video, channel or metadata. Review it in YouTube Studio before creating another upload.')
        if not VIDEO_PATTERN.fullmatch(receipt.get('video_id', '')):
            raise YouTubeError('Saved upload receipt is invalid; check YouTube Studio before retrying.')
        return receipt
    except YouTubeError:
        raise
    except (OSError, ValueError, AttributeError, TypeError):
        raise YouTubeError('Unable to read the upload record; check YouTube Studio before retrying.') from None



UPLOAD_REASONS = {
    'uploadLimitExceeded': 'YouTube channel upload limit reached. Wait for the limit to reset; check channel verification and feature eligibility in YouTube Studio.',
    'quotaExceeded': 'YouTube API project quota exhausted. Check the project quota in Google Cloud Console.',
    'dailyLimitExceeded': 'YouTube API project daily limit reached. Check the project quota in Google Cloud Console.',
    'forbidden': 'YouTube denied the upload. Check channel permissions and restrictions.',
    'insufficientPermissions': 'YouTube upload permission is missing. Reconnect the intended channel.',
    'youtubeSignupRequired': 'The authorized Google account needs an active YouTube channel.',
    'invalidVideoMetadata': 'YouTube rejected the video metadata.',
    'invalidTitle': 'YouTube rejected the video title.',
    'invalidDescription': 'YouTube rejected the video description.',
}


def upload_failure_details(exc):
    """Expose only allowlisted codes, never response messages, URLs or headers."""
    details = {'category': 'transport_or_local_failure'}
    explanation = 'The upload connection or local operation failed.'
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, 'status', None)
        if type(status) is int and 100 <= status <= 599:
            details['http_status'] = status
        details['category'] = 'youtube_api_rejection'
        explanation = 'YouTube rejected the upload request.'
        try:
            errors = json.loads(exc.content).get('error', {}).get('errors', [])
            reason = next((x.get('reason') for x in errors
                           if isinstance(x, dict) and x.get('reason') in UPLOAD_REASONS), None)
        except (ValueError, TypeError, AttributeError):
            reason = None
        if reason:
            details['reason'] = reason
            explanation = UPLOAD_REASONS[reason]
    return details, explanation

def upload_video(service, video_path, body, channel_id, video_hash, receipt_path):
    if not CHANNEL_PATTERN.fullmatch(channel_id):
        raise YouTubeError('Set YOUTUBE_CHANNEL_ID to the intended UC... channel ID.')
    expected = {'channel_id': channel_id, 'video_sha256': video_hash, 'body': body}
    previous = existing_upload(receipt_path, expected)
    if previous is not None:
        return previous, True
    channel = current_channel(service)
    if channel['id'] != channel_id:
        raise YouTubeError('Authorized YouTube channel does not match YOUTUBE_CHANNEL_ID; upload stopped.')
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    initial = {'schema_version': 1, 'state': 'uploading', **expected,
               'started_at': datetime.now(timezone.utc).isoformat()}
    # Reserve once, atomically, so concurrent processes cannot upload duplicates.
    try:
        descriptor = os.open(receipt_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise YouTubeError('Another upload record appeared; check it before retrying.') from None
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(initial, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    stage = 'preparing_request'
    try:
        media = MediaFileUpload(str(video_path), mimetype='video/mp4', chunksize=8 * 1024 * 1024, resumable=True)
        request = service.videos().insert(part='snippet,status', body=body, media_body=media, notifySubscribers=False)
        response = None
        while response is None:
            stage = 'sending_upload'
            _, response = request.next_chunk(num_retries=3)
        stage = 'saving_response'
        video_id = response.get('id')
        if not isinstance(video_id, str) or not VIDEO_PATTERN.fullmatch(video_id):
            raise YouTubeError('YouTube returned no valid video ID. Check YouTube Studio before retrying.')
        returned_privacy = (response.get('status') or {}).get('privacyStatus')
        receipt = {**initial, 'state': 'uploaded', 'video_id': video_id,
                   'url': f'https://www.youtube.com/watch?v={video_id}',
                   'requested_privacy': body['status']['privacyStatus'], 'returned_privacy': returned_privacy,
                   'uploaded_at': datetime.now(timezone.utc).isoformat(),
                   'processing_verified': False}
        save_json(receipt_path, receipt)
        return receipt, False
    except Exception as exc:
        details, explanation = upload_failure_details(exc)
        details['stage'] = stage
        try:
            save_json(receipt_path, {**initial, 'failure': details})
        except Exception:
            pass  # Keep the original reservation if diagnostic persistence fails.
        codes = ', '.join(str(details[k]) for k in ('http_status', 'reason') if k in details)
        if codes:
            explanation += f' ({codes})'
        # The remote upload may have completed even if the final response was lost.
        # Keep the reservation and never silently start another videos.insert call.
        raise YouTubeError(explanation + ' Upload failed or completion is uncertain. The local record was retained; check YouTube Studio before retrying. No new upload was started automatically.') from None
