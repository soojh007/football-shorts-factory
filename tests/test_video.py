import io
import json
from pathlib import Path
import shutil
import wave

import pytest

from backend.analysis import canonical_source, generate_analysis
from backend.normalize import normalize_fixture
from backend.render import load_words, validated_inputs
from backend.speech import sha256, wav_metadata
from backend.video import VideoError, active_metric, draw_frame, encode_video, font_path, probe_video


@pytest.fixture
def inputs(payload):
    fixture = normalize_fixture(payload)
    analysis = generate_analysis(fixture, offline_preview=True)
    analysis.update(mode='ai', model='mock-model')
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\0\0' * 8000 * 40)
    audio = buffer.getvalue()
    narration = {**wav_metadata(audio), 'fixture_id': fixture['fixture_id'],
        'audio_sha256': sha256(audio), 'script_sha256': sha256(analysis['script'].encode()),
        'source_sha256': sha256(canonical_source(fixture).encode())}
    return fixture, analysis, narration, audio


def test_sources_verified(inputs):
    fixture, analysis, narration, audio = inputs
    assert validated_inputs(fixture, analysis, narration, audio, 19427552)[2]['duration_seconds'] == 40


@pytest.mark.parametrize('field', ['audio_sha256', 'script_sha256', 'source_sha256', 'fixture_id', 'duration_seconds'])
def test_stale_narration_rejected(inputs, field):
    fixture, analysis, narration, audio = inputs
    narration[field] = 'bad'
    with pytest.raises(VideoError):
        validated_inputs(fixture, analysis, narration, audio, 19427552)


def test_invented_fact_rejected(inputs):
    fixture, analysis, narration, audio = inputs
    analysis['key_points'][0]['evidence'][0]['value'] = 'Invented team'
    with pytest.raises(VideoError, match='disagree'):
        validated_inputs(fixture, analysis, narration, audio, 19427552)


def test_active_statistic(inputs):
    _, analysis, _, _ = inputs
    point = analysis['key_points'][1]
    offset = analysis['script'].find(point['sentence'])
    word = len(analysis['script'][:offset].split())
    assert active_metric(analysis, word) == point['id']


def test_caption_cache_hash(tmp_path):
    path = tmp_path / 'cache.json'
    path.write_text(json.dumps({'audio_sha256': 'abc', 'words': [{'word': 'test'}]}))
    assert load_words(path, {'audio_sha256': 'abc'}) == [{'word': 'test'}]
    assert load_words(path, {'audio_sha256': 'changed'}) is None
    path.write_text('[]')
    assert load_words(path, {}) is None


def test_render_graphic(inputs):
    fixture, analysis, _, _ = inputs
    try:
        font_path()
    except VideoError:
        pytest.skip('No installed font')
    image = draw_frame(fixture, analysis, {'word_start': 0, 'text': 'A short match recap.'}, 0)
    assert image.size == (1080, 1920)
    assert image.mode == 'RGB'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg unavailable')
def test_real_ffmpeg_encode(tmp_path, inputs):
    fixture, analysis, _, _ = inputs
    try:
        font_path()
    except VideoError:
        pytest.skip('No installed font')
    caption = {'start': 0, 'end': 1, 'word_start': 0, 'text': 'Match recap.'}
    frame = tmp_path / 'frame.png'
    draw_frame(fixture, analysis, caption, 0).save(frame)
    audio = tmp_path / 'audio.wav'
    with wave.open(str(audio), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\0\0' * 8000)
    destination = tmp_path / 'out.mp4'
    encode_video([frame], [caption], audio, destination, 1, tmp_path)
    result = probe_video(destination, 1)
    assert result['width'] == 1080 and result['height'] == 1920
    assert result['video_codec'] == 'h264'
