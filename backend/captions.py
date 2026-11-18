"""Match approved script words to transcription timestamps, preserving script text."""
from difflib import SequenceMatcher
import math
import os
import re
import unicodedata

import requests


class CaptionError(ValueError):
    """Safe caption/timestamp failure."""


class CaptionMismatchError(CaptionError):
    def __init__(self, coverage):
        self.coverage=coverage
        super().__init__(f'Narration differs too much from the script for reliable captions '
                         f'(word match {coverage:.1%}; required 90%); review the audio.')


CONTRACTIONS = {
    "i'm": 'i am', "i've": 'i have', "i'll": 'i will', "i'd": 'i would',
    "we're": 'we are', "we've": 'we have', "we'll": 'we will',
    "they're": 'they are', "they've": 'they have', "they'll": 'they will',
    "you're": 'you are', "you've": 'you have', "you'll": 'you will',
    "it's": 'it is', "that's": 'that is', "there's": 'there is',
    "here's": 'here is', "what's": 'what is', "let's": 'let us',
    "don't": 'do not', "doesn't": 'does not', "didn't": 'did not',
    "isn't": 'is not', "aren't": 'are not', "wasn't": 'was not',
    "weren't": 'were not', "can't": 'cannot', "won't": 'will not',
    "hasn't": 'has not', "haven't": 'have not', "wouldn't": 'would not',
    "couldn't": 'could not', "shouldn't": 'should not',
}


ONES = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
TENS = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()


def tokens(text):
    result = []
    text=''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))
    text=text.replace('đ','d')
    for token in re.findall(r"[\w]+(?:['’][\w]+)?", text.lower()):
        token = token.replace('’', "'")
        if token in CONTRACTIONS:
            result.extend(CONTRACTIONS[token].split())
        elif token.isascii() and token.isdigit() and int(token) < 100:
            value = int(token)
            result.extend([ONES[value]] if value < 20 else [TENS[value // 10]] + ([ONES[value % 10]] if value % 10 else []))
        else:
            result.append(token)
    return result


def align_captions(script, words, duration):
    if not isinstance(words, list) or not words or not math.isfinite(duration) or duration <= 0:
        raise CaptionError('Missing or invalid word timestamps.')
    raw = script.split()
    source, owners = [], []
    for index, word in enumerate(raw):
        expanded = tokens(word)
        source.extend(expanded)
        owners.extend([index] * len(expanded))
    spoken, starts = [], []
    previous = 0.0
    for entry in words:
        if not isinstance(entry, dict) or not isinstance(entry.get('word'), str):
            raise CaptionError('Invalid transcription word data.')
        start, end = entry.get('start'), entry.get('end')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < previous or start < 0 or end < start or end > duration + 0.25):
            raise CaptionError('Invalid or non-monotonic word timestamps.')
        expanded = tokens(entry['word'])
        spoken.extend(expanded)
        starts.extend([min(start, duration)] * len(expanded))
        previous = start
    matcher = SequenceMatcher(None, source, spoken, autojunk=False)
    blocks = matcher.get_matching_blocks()
    matches = sum(block.size for block in blocks)
    coverage = matches / max(len(source), len(spoken), 1)
    if coverage < 0.90:
        raise CaptionMismatchError(coverage)
    anchors = {}
    for block in blocks:
        for offset in range(block.size):
            index = owners[block.a + offset]
            anchors.setdefault(index, starts[block.b + offset])
    if not anchors:
        raise CaptionError('Unable to align narration to script.')
    # Interpolate unmatched script words between neighboring matched words.
    times = []
    ordered = sorted(anchors)
    for index in range(len(raw)):
        if index in anchors:
            time = anchors[index]
        else:
            left = max((i for i in ordered if i < index), default=-1)
            right = min((i for i in ordered if i > index), default=len(raw))
            low = anchors[left] if left >= 0 else 0.0
            high = anchors[right] if right < len(raw) else duration
            time = low + (high - low) * (index - left) / (right - left)
        times.append(max(times[-1] if times else 0.0, time))
    # Short phrases, retaining the exact spelling/punctuation of the source script.
    groups, first = [], 0
    for index in range(len(raw)):
        text = ' '.join(raw[first:index + 1])
        next_text = text + (' ' + raw[index + 1] if index + 1 < len(raw) else '')
        if index == len(raw) - 1 or index - first >= 5 or len(next_text) > 42 or raw[index].endswith(('.', '?', '!')):
            groups.append((first, index + 1, text))
            first = index + 1
    captions = []
    for number, (first, last, text) in enumerate(groups):
        start = 0.0 if number == 0 else times[first]
        end = times[groups[number + 1][0]] if number + 1 < len(groups) else duration
        if end - start < 0.04:
            raise CaptionError('Caption timing is too compressed; review the audio alignment.')
        captions.append({'start': round(start, 4), 'end': round(end, 4), 'text': text,
                         'word_start': first, 'word_end': last})
    return {'alignment_coverage': round(coverage, 4), 'captions': captions}



def align_with_recovery(script, words, duration, *, retry_transcription=None):
    """One glossary-assisted ASR retry; never bypass mismatches or invalid timing."""
    try:
        return words, align_captions(script,words,duration), False
    except CaptionMismatchError:
        if retry_transcription is None:
            raise
    retried=retry_transcription()
    return retried, align_captions(script,retried,duration), True


def prediction_glossary(prediction):
    names=[team['name'] for team in prediction['teams'].values()]
    for side in ('home','away'):
        names.extend(p['name'] for p in prediction.get('featured_players',{}).get(side,[]))
    # Spelling hints only, rather than feeding the expected transcript to ASR.
    return ', '.join(dict.fromkeys(names))[:300]

def srt_text(captions):
    def timestamp(seconds):
        milliseconds = round(seconds * 1000)
        hours, remainder = divmod(milliseconds, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'
    return '\n\n'.join(f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}"
                       for i, c in enumerate(captions, 1)) + '\n'


class TranscriptionClient:
    URL = 'https://api.openai.com/v1/audio/transcriptions'

    def __init__(self, api_key=None, session=None):
        self._key = api_key if api_key is not None else os.getenv('OPENAI_API_KEY', '')
        if not self._key.strip():
            raise CaptionError('Set OPENAI_API_KEY to create audio-aligned captions.')
        self.session = session or requests.Session()

    def transcribe(self, audio_path, *, glossary=None):
        if audio_path.stat().st_size > 25 * 1024 * 1024:
            raise CaptionError('Narration exceeds the 25 MB transcription upload limit.')
        data={'model': 'whisper-1', 'response_format': 'verbose_json',
              'timestamp_granularities[]': 'word', 'language': 'en'}
        if glossary:
            data['prompt']=glossary[:300]
        try:
            with audio_path.open('rb') as audio:
                response = self.session.post(self.URL,
                    headers={'Authorization': f'Bearer {self._key}'},
                    files={'file': ('narration.wav', audio, 'audio/wav')},
                    data=data, timeout=60)
        except requests.Timeout:
            raise CaptionError('Caption transcription timed out; retry when ready.') from None
        except requests.RequestException:
            raise CaptionError('Unable to connect to caption transcription API.') from None
        if response.status_code in (401, 403):
            raise CaptionError('Caption transcription authentication/access denied.')
        if response.status_code == 429:
            raise CaptionError('Caption transcription rate limit or quota reached.')
        if not 200 <= response.status_code < 300:
            raise CaptionError(f'Caption transcription failed (HTTP {response.status_code}).')
        try:
            payload = response.json()
            words = payload.get('words')
            if not isinstance(words, list) or not words:
                raise CaptionError('Transcription returned no word timestamps.')
            return words
        except (ValueError, AttributeError):
            raise CaptionError('Transcription returned invalid word timestamp data.') from None
