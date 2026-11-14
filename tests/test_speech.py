import io
import json
from unittest.mock import MagicMock, Mock
import wave

import pytest
import requests

from backend.analysis import generate_analysis
from backend.narrate import main
from backend.normalize import normalize_fixture
from backend.speech import SpeechClient, SpeechError, validate_analysis, wav_metadata


@pytest.fixture
def wav_audio():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\0\0' * 8000 * 40)
    return buffer.getvalue()


@pytest.fixture
def analysis(payload):
    result = generate_analysis(normalize_fixture(payload), offline_preview=True)
    result.update(mode='ai', model='mock-model')
    return result


@pytest.fixture
def session(wav_audio):
    session = MagicMock()
    session.post.return_value.status_code = 200
    session.post.return_value.content = wav_audio
    return session


def test_speech_request(session, wav_audio):
    client = SpeechClient(api_key='synthetic-key', session=session)
    assert client.generate('Test narration.') == wav_audio
    args, kwargs = session.post.call_args
    assert args == ('https://api.openai.com/v1/audio/speech',)
    assert kwargs['headers']['Authorization'] == 'Bearer synthetic-key'
    assert kwargs['json']['response_format'] == 'wav'
    assert kwargs['json']['input'] == 'Test narration.'
    assert kwargs['json']['voice'] == 'coral'
    assert kwargs['json']['speed'] == 1.0
    assert 'instructions' in kwargs['json']


def test_wav_actual_duration(wav_audio):
    result = wav_metadata(wav_audio)
    assert result['duration_seconds'] == 40
    assert result['within_target_duration'] is True
    assert result['frames'] == 320000
    assert result['sample_rate_hz'] == 8000


@pytest.mark.parametrize('audio', [b'', b'not audio', b'{"error":"synthetic-key"}'])
def test_invalid_audio(audio):
    with pytest.raises(SpeechError):
        wav_metadata(audio)


def test_truncated_audio(wav_audio):
    with pytest.raises(SpeechError):
        wav_metadata(wav_audio[:-100])


def test_outside_target_is_measured(wav_audio):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\0\0' * 8000)
    result = wav_metadata(buffer.getvalue())
    assert result['duration_seconds'] == 1
    assert result['within_target_duration'] is False


@pytest.mark.parametrize('status', [400, 401, 403, 429, 500])
def test_http_errors(session, status):
    session.post.return_value.status_code = status
    with pytest.raises(SpeechError) as exc:
        SpeechClient(api_key='synthetic-key', session=session).generate('Test.')
    assert 'synthetic-key' not in str(exc.value)


@pytest.mark.parametrize('error', [requests.Timeout('synthetic-key'), requests.ConnectionError('synthetic-key')])
def test_network_errors(session, error):
    session.post.side_effect = error
    with pytest.raises(SpeechError) as exc:
        SpeechClient(api_key='synthetic-key', session=session).generate('Test.')
    assert 'synthetic-key' not in str(exc.value)


@pytest.mark.parametrize('speed', [0, 5, float('nan'), float('inf'), True])
def test_bad_speed(speed):
    with pytest.raises(SpeechError):
        SpeechClient(api_key='synthetic-key', speed=speed)


def test_missing_key(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', '')
    with pytest.raises(SpeechError, match='OPENAI_API_KEY'):
        SpeechClient()


@pytest.mark.parametrize('script', ['', ' ' , 'x'*4097, None])
def test_bad_script(script, session):
    with pytest.raises(SpeechError):
        SpeechClient(api_key='synthetic-key', session=session).generate(script)
    session.post.assert_not_called()


def test_preview_rejected(analysis):
    analysis['mode'] = 'offline_preview'
    with pytest.raises(SpeechError, match='offline preview'):
        validate_analysis(analysis)


def test_fixture_mismatch(analysis):
    with pytest.raises(SpeechError, match='fixture ID'):
        validate_analysis(analysis, fixture_id=1)


def test_changed_script_rejected(analysis):
    analysis['script'] += ' Extra text.'
    with pytest.raises(SpeechError, match='word count'):
        validate_analysis(analysis)


def test_cli_save_reuse_and_force(tmp_path, monkeypatch, session, analysis):
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key')
    monkeypatch.setenv('OPENAI_TTS_MODEL', 'gpt-4o-mini-tts')
    monkeypatch.setenv('OPENAI_TTS_VOICE', 'coral')
    monkeypatch.setenv('OPENAI_TTS_SPEED', '1.0')
    monkeypatch.setattr('backend.speech.requests.Session', lambda: session)
    path = tmp_path / 'analysis.json'
    path.write_text(json.dumps(analysis))
    output = tmp_path / 'out'
    args = ['--input', str(path), '--output-dir', str(output)]
    assert main(args) == 0
    assert (output / '19427552_narration.wav').exists()
    data = json.loads((output / '19427552_narration.json').read_text())
    assert data['duration_seconds'] == 40
    assert data['disclosure'] == 'This narration uses an AI-generated voice.'
    assert data['requires_editorial_review'] is True
    assert main(args) == 0
    assert session.post.call_count == 1
    assert main(args + ['--force']) == 0
    assert session.post.call_count == 2
    (output / '19427552_narration.wav').write_bytes(b'corrupt')
    assert main(args) == 0
    assert session.post.call_count == 3


def test_missing_analysis_no_api_call(tmp_path, monkeypatch):
    factory = Mock()
    monkeypatch.setattr('backend.speech.requests.Session', factory)
    assert main(['--input', str(tmp_path / 'missing.json')]) == 1
    factory.assert_not_called()


@pytest.mark.parametrize('speed', ['nan', 'inf', 'zero', '0', '5'])
def test_cli_bad_speed(speed):
    with pytest.raises(SystemExit) as exc:
        main(['--fixture', '19427552', '--speed', speed])
    assert exc.value.code == 2


def test_personal_delivery_instructions_reach_api(session):
    instructions='Speak like a football fan sharing my own take with a friend.'
    SpeechClient(api_key='synthetic-key',session=session,instructions=instructions).generate('My pick is a draw.')
    assert session.post.call_args.kwargs['json']['instructions']==instructions
