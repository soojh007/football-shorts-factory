from unittest.mock import Mock

import pytest
import requests

from backend.captions import CaptionError, TranscriptionClient, align_captions, srt_text, tokens


def timed_words(script):
    return [{'word': word, 'start': i * 0.5, 'end': (i + 1) * 0.5} for i, word in enumerate(script.split())]


def test_alignment_preserves_script():
    script = 'Home scored two goals. Away scored one goal.'
    result = align_captions(script, timed_words(script), 5)
    assert result['alignment_coverage'] == 1
    captions = result['captions']
    assert ' '.join(c['text'] for c in captions) == script
    assert captions[0]['start'] == 0
    assert captions[-1]['end'] == 5
    assert all(left['end'] == right['start'] for left, right in zip(captions, captions[1:]))
    assert all(c['end'] > c['start'] for c in captions)


def test_spoken_numbers_match_digits():
    result = align_captions('Forest recorded 41 percent possession.', timed_words('Forest recorded forty one percent possession.'), 4)
    assert result['alignment_coverage'] == 1
    assert '41' in ' '.join(c['text'] for c in result['captions'])
    assert tokens('2–2') == ['two', 'two']


def test_small_omission_interpolates():
    script = 'one two three four five six seven eight nine ten eleven twelve'
    words = timed_words(script.replace('five ', ''))
    result = align_captions(script, words, 7)
    assert result['alignment_coverage'] >= 0.9
    assert ' '.join(c['text'] for c in result['captions']) == script


def test_large_mismatch_fails():
    with pytest.raises(CaptionError, match='differs'):
        align_captions('Home scored two goals.', timed_words('Unrelated audio has different content.'), 4)


@pytest.mark.parametrize('words', [[], None, [None], [{'word': 'test', 'start': -1, 'end': 1}],
    [{'word': 'test', 'start': 0, 'end': float('nan')}], [{'word': 'test', 'start': True, 'end': 1}],
    [{'word': 'test', 'start': 0, 'end': 30}],
    [{'word': 'test', 'start': 1, 'end': 2}, {'word': 'test', 'start': 0, 'end': 1}]])
def test_invalid_timestamps(words):
    with pytest.raises(CaptionError):
        align_captions('test', words, 3)


def test_srt_milliseconds():
    assert srt_text([{'start': 1.234, 'end': 2.567, 'text': 'Test.'}]) == '1\n00:00:01,234 --> 00:00:02,567\nTest.\n'


def test_transcription_request(tmp_path):
    audio = tmp_path / 'test.wav'
    audio.write_bytes(b'synthetic-audio')
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {'words': timed_words('Test audio')}
    words = TranscriptionClient(api_key='synthetic-key', session=session).transcribe(audio)
    assert len(words) == 2
    kwargs = session.post.call_args.kwargs
    assert kwargs['data']['model'] == 'whisper-1'
    assert kwargs['data']['timestamp_granularities[]'] == 'word'
    assert kwargs['data']['response_format'] == 'verbose_json'
    assert kwargs['headers']['Authorization'] == 'Bearer synthetic-key'
    assert kwargs['timeout'] == 60


@pytest.mark.parametrize('status', [401, 403, 429, 500])
def test_transcription_http_error(tmp_path, status):
    audio = tmp_path / 'test.wav'
    audio.write_bytes(b'synthetic-audio')
    session = Mock()
    session.post.return_value.status_code = status
    with pytest.raises(CaptionError) as exc:
        TranscriptionClient(api_key='synthetic-key', session=session).transcribe(audio)
    assert 'synthetic-key' not in str(exc.value)


def test_transcription_timeout(tmp_path):
    audio = tmp_path / 'test.wav'
    audio.write_bytes(b'synthetic-audio')
    session = Mock()
    session.post.side_effect = requests.Timeout('synthetic-key')
    with pytest.raises(CaptionError) as exc:
        TranscriptionClient(api_key='synthetic-key', session=session).transcribe(audio)
    assert 'synthetic-key' not in str(exc.value)


def test_accented_names_and_expanded_contractions_preserve_original_captions():
    script="I'm backing Công An Hồ Chí Minh. I've watched José and Đặng. They don't need a different spelling."
    transcript="I am backing Cong An Ho Chi Minh. I have watched Jose and Dang. They do not need a different spelling."
    result=align_captions(script,timed_words(transcript),14)
    assert result['alignment_coverage']==1
    assert ' '.join(c['text'] for c in result['captions'])==script


def test_negation_and_scores_are_not_normalized_away():
    assert tokens("don't")==tokens('do not')
    assert tokens("don't")!=tokens('do')
    assert tokens('2–1')!=tokens('1–2')


def test_one_recovery_transcription_still_requires_matching_audio():
    from backend.captions import align_with_recovery,CaptionMismatchError
    script='This is my football prediction for the match tonight.'
    retry=Mock(return_value=timed_words(script))
    words,result,recovered=align_with_recovery(script,timed_words('Totally unrelated narration content'),7,retry_transcription=retry)
    assert recovered and result['alignment_coverage']==1
    retry.assert_called_once_with()
    retry.reset_mock()
    retry.return_value=timed_words('Still unrelated narration content')
    with pytest.raises(CaptionMismatchError,match='word match'):
        align_with_recovery(script,words=timed_words('Unrelated audio content'),duration=7,retry_transcription=retry)
    retry.assert_called_once_with()


def test_invalid_timing_never_gets_a_transcription_retry():
    from backend.captions import align_with_recovery
    retry=Mock()
    with pytest.raises(CaptionError):
        align_with_recovery('test',[{'word':'test','start':-1,'end':1}],3,retry_transcription=retry)
    retry.assert_not_called()


def test_good_alignment_never_gets_a_transcription_retry():
    from backend.captions import align_with_recovery
    retry=Mock()
    _,_,recovered=align_with_recovery('This is a test.',timed_words('This is a test.'),3,retry_transcription=retry)
    assert not recovered
    retry.assert_not_called()


def test_glossary_request_is_spelling_hints_only(tmp_path):
    from backend.captions import prediction_glossary
    p={'teams':{'home':{'name':'Công An Hồ Chí Minh'},'away':{'name':'Buriram United'}},
       'featured_players':{'home':[{'name':'José'}]},'script':'Do not supply this entire script.'}
    glossary=prediction_glossary(p)
    assert glossary=='Công An Hồ Chí Minh, Buriram United, José'
    audio=tmp_path/'test.wav';audio.write_bytes(b'fake-audio')
    session=Mock();session.post.return_value.status_code=200
    session.post.return_value.json.return_value={'words':timed_words('Test audio')}
    TranscriptionClient(api_key='synthetic-key',session=session).transcribe(audio,glossary=glossary)
    assert session.post.call_args.kwargs['data']['prompt']==glossary
