"""Prepare upload metadata, or upload explicitly with --upload (private by default)."""
import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

from backend.analysis import AnalysisError
from backend.main import ROOT, positive_int, save_json
from backend.render import validated_inputs
from backend.speech import SpeechError, sha256
from backend.video import VideoError, probe_video
from backend.youtube import CHANNEL_PATTERN, existing_upload, upload_body, upload_video
from backend.youtube_auth import YouTubeError, load_credentials, youtube_service


def prepare_upload(fixture_id, data_dir, artifacts_dir, privacy, made_for_kids, league_id=8):
    def read(name):
        return json.loads((artifacts_dir / f'{fixture_id}_{name}.json').read_text(encoding='utf-8'))
    fixture = json.loads((data_dir / f'{fixture_id}_normalized.json').read_text(encoding='utf-8'))
    narration = read('narration')
    audio_path = artifacts_dir / f'{fixture_id}_narration.wav'
    fixture, analysis, measured = validated_inputs(fixture, read('analysis'), narration, audio_path.read_bytes(), fixture_id, league_id)
    render = read('render')
    video_path = artifacts_dir / f'{fixture_id}_short.mp4'
    video_hash = sha256(video_path.read_bytes())
    if (render.get('fixture_id') != fixture_id or render.get('video_sha256') != video_hash
            or render.get('audio_sha256') != narration['audio_sha256']
            or render.get('script_sha256') != narration['script_sha256']
            or render.get('source_sha256') != analysis['source_sha256']
            or render.get('ai_voice_disclosure_visible') is not True):
        raise YouTubeError('Rendered video provenance does not match source artifacts; render again.')
    verification = probe_video(video_path, measured['duration_seconds'])
    # Build public-facing text from verified identities, scores and fact sentences.
    score = fixture['final_score']
    analysis['title'] = (f"{fixture['home_team']['name']} {score['home']}–{score['away']} "
                         f"{fixture['away_team']['name']} | Match numbers")
    analysis['summary'] = ' '.join(point['sentence'] for point in analysis['key_points'])
    body = upload_body(analysis, privacy, made_for_kids)
    return video_path, {'schema_version': 1, 'fixture_id': fixture_id, 'video_sha256': video_hash,
                         'body': body, 'video': verification}


def main(argv=None):
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description='Prepare a YouTube upload, or upload explicitly (private by default).')
    parser.add_argument('--fixture', required=True, type=positive_int)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data' / 'fixtures')
    parser.add_argument('--artifacts-dir', type=Path, default=ROOT / 'generated')
    parser.add_argument('--privacy', choices=('private', 'unlisted', 'public'), default='private')
    parser.add_argument('--made-for-kids', action='store_true', help='Declare this video as directed to children')
    parser.add_argument('--upload', action='store_true', help='Actually upload using the authorized YouTube channel')
    parser.add_argument('--epl-league-id', type=positive_int, default=os.getenv('EPL_LEAGUE_ID', '8'))
    args = parser.parse_args(argv)
    try:
        video_path, plan = prepare_upload(args.fixture, args.data_dir, args.artifacts_dir,
                                         args.privacy, args.made_for_kids, args.epl_league_id)
        channel_id = os.getenv('YOUTUBE_CHANNEL_ID', '')
        plan['channel_id'] = channel_id or None
        save_json(args.artifacts_dir / f'{args.fixture}_youtube_plan.json', plan)
        if not args.upload:
            print(f"Prepared: {plan['body']['snippet']['title']}")
            print(f'Visibility: {args.privacy}; channel: {channel_id or "not configured"}')
            print('Local preview only. No Google sign-in, API call or upload performed.')
            return 0
        if not CHANNEL_PATTERN.fullmatch(channel_id):
            raise YouTubeError('Set YOUTUBE_CHANNEL_ID to the intended UC... channel ID before uploading.')
        receipt_path = args.artifacts_dir / f'{args.fixture}_youtube_upload.json'
        expected = {'channel_id': channel_id, 'video_sha256': plan['video_sha256'], 'body': plan['body']}
        receipt = existing_upload(receipt_path, expected)
        reused = receipt is not None
        if not reused:
            service = youtube_service(load_credentials())
            try:
                receipt, reused = upload_video(service, video_path, plan['body'], channel_id,
                                               plan['video_sha256'], receipt_path)
            finally:
                service.close()
        print(('Already uploaded: ' if reused else 'Upload accepted: ') + receipt['url'])
        print(f"Requested visibility: {receipt['requested_privacy']}; returned visibility: {receipt['returned_privacy'] or 'not returned'}.")
        print('Check processing, visibility, audience, captions and playback in YouTube Studio.')
    except (YouTubeError, VideoError, SpeechError, AnalysisError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print('Error: Unable to read valid pipeline artifacts or save YouTube metadata.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
