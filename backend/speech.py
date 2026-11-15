"""OpenAI speech generation and measured WAV metadata; no audio playback."""
import hashlib
import io
import math
import os
import wave

import requests
from pydantic import ValidationError

from backend.analysis import AnalysisResult

VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse", "marin", "cedar")
MODELS = ("gpt-4o-mini-tts", "tts-1", "tts-1-hd")
MAX_AUDIO_BYTES = 32 * 1024 * 1024
PERSONAL_VOICE = "cedar"
PERSONAL_VOICE_INSTRUCTIONS = (
    "Read the supplied script exactly in English. Use an adult male voice with a light, natural "
    "Singaporean English accent. Keep pronunciation clear for an international audience, with a warm "
    "mid-low register and relaxed, confident delivery, like a football fan sharing my own take with one friend. "
    "Use natural pauses and emphasis. Keep the accent consistent without exaggeration or caricature. "
    "Do not add Singlish particles or change any words. Do not use a newsreader or broadcast-announcer tone."
)
DISCLOSURE = "This narration uses an AI-generated voice."


class SpeechError(ValueError):
    """Safe-to-display narration failure."""


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def validate_analysis(value, fixture_id=None):
    try:
        result = AnalysisResult.model_validate(value)
    except ValidationError:
        raise SpeechError("Invalid analysis JSON; regenerate analysis first.") from None
    if fixture_id is not None and result.fixture_id != fixture_id:
        raise SpeechError("Analysis fixture ID does not match the requested fixture.")
    if result.mode != "ai":
        raise SpeechError("Narration requires AI analysis, not an offline preview.")
    if not result.script.strip() or len(result.script) > 4096:
        raise SpeechError("Narration script must contain 1–4096 characters.")
    if len(result.script.split()) != result.word_count:
        raise SpeechError("Script word count disagrees with analysis metadata.")
    if any(point.sentence not in result.script for point in result.key_points):
        raise SpeechError("Analysis evidence sentences are missing from the script.")
    return result


def wav_metadata(audio):
    if not isinstance(audio, bytes) or not audio or len(audio) > MAX_AUDIO_BYTES:
        raise SpeechError("Speech response is empty or exceeds the audio size limit.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            declared_frames = wav.getnframes()
            samples = wav.readframes(declared_frames)
            frame_size = channels * width
            if not rate or not frame_size or not samples or len(samples) % frame_size:
                raise SpeechError("Speech response contains invalid WAV samples.")
            frames = len(samples) // frame_size
            # Streaming WAV responses can use a placeholder data length. Measure
            # actual PCM samples, while rejecting truncation in ordinary WAV files.
            streaming_header = declared_frames >= (0x7FFFFFFF // frame_size)
            if frames != declared_frames and not streaming_header:
                raise SpeechError("Speech response contains truncated WAV audio.")
    except (wave.Error, EOFError, OSError, ValueError):
        raise SpeechError("Speech response is not valid PCM WAV audio.") from None
    duration = frames / rate
    return {
        "duration_seconds": round(duration, 3), "sample_rate_hz": rate,
        "channels": channels, "sample_width_bytes": width, "frames": frames,
        "within_target_duration": 30 <= duration <= 60,
    }


class SpeechClient:
    URL = "https://api.openai.com/v1/audio/speech"

    def __init__(self, api_key=None, model="gpt-4o-mini-tts", voice="coral", speed=1.0,
                 session=None, timeout=60, instructions=None):
        self._key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        if not self._key.strip():
            raise SpeechError("Set OPENAI_API_KEY in .env to generate narration.")
        if model not in MODELS or voice not in VOICES:
            raise SpeechError("Unsupported speech model or voice.")
        if not isinstance(speed, (float, int)) or isinstance(speed, bool) or not math.isfinite(speed) or not 0.25 <= speed <= 4:
            raise SpeechError("Speech speed must be between 0.25 and 4.0.")
        self.model, self.voice, self.speed = model, voice, speed
        self.session = session or requests.Session()
        self.timeout = timeout
        self.instructions = instructions

    def generate(self, script):
        if not isinstance(script, str) or not script.strip() or len(script) > 4096:
            raise SpeechError("Narration script must contain 1–4096 characters.")
        body = {"model": self.model, "voice": self.voice, "input": script,
                "response_format": "wav", "speed": self.speed}
        if self.model == "gpt-4o-mini-tts":
            body["instructions"] = self.instructions or (
                "Read the supplied script exactly, in clear English with a British football presenter tone. "
                "Use a brisk, natural delivery suited to a short match recap. Do not add words or sound effects."
            )
        try:
            response = self.session.post(self.URL,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json=body, timeout=self.timeout)
        except requests.Timeout:
            raise SpeechError("OpenAI speech request timed out; retry when ready.") from None
        except requests.RequestException:
            raise SpeechError("Unable to connect to OpenAI speech API.") from None
        if response.status_code in (401, 403):
            raise SpeechError("OpenAI speech authentication/access denied; check API key and model access.")
        if response.status_code == 429:
            raise SpeechError("OpenAI speech quota or rate limit reached; check billing and retry later.")
        if not 200 <= response.status_code < 300:
            raise SpeechError(f"OpenAI speech request failed (HTTP {response.status_code}).")
        audio = response.content
        wav_metadata(audio)
        return audio
