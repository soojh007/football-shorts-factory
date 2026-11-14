"""Render a vertical MP4: python -m backend.render --fixture ID."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

from dotenv import load_dotenv

from backend.analysis import AnalysisError, build_facts, canonical_source, checked_fixture
from backend.analyze import save_text
from backend.captions import CaptionError, TranscriptionClient, align_captions, srt_text
from backend.main import ROOT, positive_int, save_json
from backend.speech import SpeechError, sha256, validate_analysis, wav_metadata
from backend.video import STYLE_VERSION, VideoError, draw_frame, encode_video, probe_video, require_tools


def validated_inputs(fixture, analysis, narration, audio, fixture_id, league_id=8):
    fixture = checked_fixture(fixture, league_id)
    analysis = validate_analysis(analysis, fixture_id).model_dump(mode='json')
    if fixture['fixture_id'] != fixture_id or fixture['match_status'] != 'FT':
        raise VideoError('Rendering requires a matching full-time EPL fixture.')
    if not isinstance(narration, dict):
        raise VideoError('Invalid narration metadata.')
    measured = wav_metadata(audio)
    source_hash = sha256(canonical_source(fixture).encode())
    if (analysis['source_sha256'] != source_hash or narration.get('source_sha256') != source_hash
            or narration.get('fixture_id') != fixture_id or narration.get('audio_sha256') != sha256(audio)
            or narration.get('script_sha256') != sha256(analysis['script'].encode())):
        raise VideoError('Fixture, analysis and narration hashes do not match; regenerate stale artifacts.')
    if any(narration.get(key) != value for key, value in measured.items()):
        raise VideoError('Narration metadata disagrees with measured WAV audio.')
    if not measured['within_target_duration']:
        raise VideoError('Narration must be 30–60 seconds; adjust speech speed or script first.')
    known = {fact.id: fact.model_dump(mode='json') for fact in build_facts(fixture)}
    ids = [point['id'] for point in analysis['key_points']]
    if not ids or ids[0] != 'score' or len(set(ids)) != len(ids):
        raise VideoError('Analysis contains invalid or duplicate fact references.')
    for point in analysis['key_points']:
        if point != known.get(point['id']):
            raise VideoError('Analysis facts disagree with current fixture data.')
    return fixture, analysis, measured


def load_words(cache_path, expected):
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        if all(cache.get(key) == value for key, value in expected.items()) and isinstance(cache.get('words'), list):
            return cache['words']
    except (OSError, ValueError, AttributeError):
        pass
    return None


def main(argv=None):
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description='Render a captioned 1080×1920 EPL match recap with narration.')
    parser.add_argument('--fixture', required=True, type=positive_int)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data' / 'fixtures')
    parser.add_argument('--artifacts-dir', type=Path, default=ROOT / 'generated')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'generated')
    parser.add_argument('--epl-league-id', type=positive_int, default=os.getenv('EPL_LEAGUE_ID', '8'))
    parser.add_argument('--refresh-captions', action='store_true', help='Request new transcription timestamps (paid API call)')
    args = parser.parse_args(argv)
    try:
        require_tools()
        fixture_id = args.fixture
        source = json.loads((args.data_dir / f'{fixture_id}_normalized.json').read_text(encoding='utf-8'))
        analysis = json.loads((args.artifacts_dir / f'{fixture_id}_analysis.json').read_text(encoding='utf-8'))
        narration = json.loads((args.artifacts_dir / f'{fixture_id}_narration.json').read_text(encoding='utf-8'))
        audio_path = args.artifacts_dir / f'{fixture_id}_narration.wav'
        audio = audio_path.read_bytes()
        fixture, analysis, measured = validated_inputs(source, analysis, narration, audio, fixture_id, args.epl_league_id)
        args.output_dir = args.output_dir.resolve()
        args.output_dir.mkdir(parents=True, exist_ok=True)
        cache_path = args.output_dir / f'{fixture_id}_captions.json'
        expected = {'schema_version': 1, 'audio_sha256': sha256(audio),
                    'script_sha256': sha256(analysis['script'].encode()), 'model': 'whisper-1'}
        words = None if args.refresh_captions else load_words(cache_path, expected)
        reused = words is not None
        if words is None:
            print('Creating audio-aligned caption timestamps...', flush=True)
            client = TranscriptionClient()
            with client.session:
                words = client.transcribe(audio_path)
        aligned = align_captions(analysis['script'], words, measured['duration_seconds'])
        save_json(cache_path, {**expected, 'words': words, **aligned})
        captions = aligned['captions']
        with tempfile.TemporaryDirectory(prefix='.render-', dir=args.output_dir) as directory:
            workdir = Path(directory)
            frames = []
            print(f"Rendering {len(captions)} caption scenes...", flush=True)
            for index, caption in enumerate(captions):
                frame = workdir / f'frame_{index:04}.png'
                draw_frame(fixture, analysis, caption, caption['start'] / measured['duration_seconds']).save(frame)
                frames.append(frame)
            staged = workdir / 'video.mp4'
            encode_video(frames, captions, audio_path, staged, measured['duration_seconds'], workdir)
            verification = probe_video(staged, measured['duration_seconds'])
            output_path = args.output_dir / f'{fixture_id}_short.mp4'
            staged.replace(output_path)
            frames[0].replace(args.output_dir / f'{fixture_id}_poster.png')
        save_text(args.output_dir / f'{fixture_id}_captions.srt', srt_text(captions))
        save_json(args.output_dir / f'{fixture_id}_render.json', {
            'schema_version': 1, 'fixture_id': fixture_id, 'style_version': STYLE_VERSION,
            'source_sha256': analysis['source_sha256'], 'script_sha256': expected['script_sha256'],
            'audio_sha256': expected['audio_sha256'], 'video_sha256': sha256(output_path.read_bytes()),
            'caption_method': 'transcribed_word_alignment', 'transcription_model': 'whisper-1',
            'caption_count': len(captions), 'alignment_coverage': aligned['alignment_coverage'],
            'caption_cache_reused': reused, 'ai_voice_disclosure_visible': True,
            'requires_editorial_review': True, 'generated_at': datetime.now(timezone.utc).isoformat(),
            **verification,
        })
    except (VideoError, CaptionError, SpeechError, AnalysisError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print('Error: Unable to read valid source artifacts or save video output.', file=sys.stderr)
        return 1
    print(f'Saved {output_path}')
    print(f"Verified: 1080×1920, H.264/AAC, {verification['duration_seconds']:.2f} seconds.")
    print(f"Caption alignment coverage: {aligned['alignment_coverage']:.1%}; review captions, audio and graphics before publishing.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
