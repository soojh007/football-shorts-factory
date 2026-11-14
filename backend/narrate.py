"""Generate reusable WAV narration: python -m backend.narrate --fixture ID."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from dotenv import load_dotenv

from backend.main import ROOT, positive_int, save_json
from backend.speech import DISCLOSURE, MODELS, VOICES, SpeechClient, SpeechError, sha256, validate_analysis, wav_metadata


def speed_value(value):
    try:
        speed = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("speed must be between 0.25 and 4.0") from None
    if not math.isfinite(speed) or not 0.25 <= speed <= 4:
        raise argparse.ArgumentTypeError("speed must be between 0.25 and 4.0")
    return speed


def save_audio(path, audio):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(audio)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def cached_audio(audio_path, metadata_path, settings):
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        audio = audio_path.read_bytes()
        if any(metadata.get(key) != value for key, value in settings.items()):
            return None
        if metadata.get("audio_sha256") != sha256(audio):
            return None
        measured = wav_metadata(audio)
        if any(metadata.get(key) != value for key, value in measured.items()):
            return None
        return metadata
    except (OSError, ValueError, AttributeError):
        return None


def main(argv=None):
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Generate AI voice narration from saved match analysis.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=positive_int)
    source.add_argument("--input", type=Path, help="Path to AI analysis JSON, not the plain text script")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "generated")
    parser.add_argument("--voice", choices=VOICES, default=os.getenv("OPENAI_TTS_VOICE", "coral"))
    parser.add_argument("--model", choices=MODELS, default=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"))
    parser.add_argument("--speed", type=speed_value, default=os.getenv("OPENAI_TTS_SPEED", "1.1"))
    parser.add_argument("--force", action="store_true", help="Regenerate even when matching audio exists (paid API call)")
    args = parser.parse_args(argv)
    if args.voice not in VOICES or args.model not in MODELS:
        parser.error("Unsupported speech voice or model in environment configuration.")
    input_path = args.input or ROOT / "generated" / f"{args.fixture}_analysis.json"
    try:
        analysis = validate_analysis(json.loads(input_path.read_text(encoding="utf-8")), args.fixture)
        settings = {
            "schema_version": 1, "fixture_id": analysis.fixture_id,
            "script_sha256": sha256(analysis.script.encode()), "source_sha256": analysis.source_sha256,
            "model": args.model, "voice": args.voice, "speed": args.speed, "format": "wav",
            "disclosure": DISCLOSURE, "requires_editorial_review": True,
        }
        audio_path = args.output_dir / f"{analysis.fixture_id}_narration.wav"
        metadata_path = args.output_dir / f"{analysis.fixture_id}_narration.json"
        metadata = None if args.force else cached_audio(audio_path, metadata_path, settings)
        reused = metadata is not None
        if not reused:
            client = SpeechClient(model=args.model, voice=args.voice, speed=args.speed)
            with client.session:
                audio = client.generate(analysis.script)
            metadata = {**settings, **wav_metadata(audio), "audio_sha256": sha256(audio),
                        "word_count": analysis.word_count,
                        "generated_at": datetime.now(timezone.utc).isoformat()}
            args.output_dir.mkdir(parents=True, exist_ok=True)
            save_audio(audio_path, audio)
            save_json(metadata_path, metadata)
    except SpeechError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Error: Unable to read analysis JSON or save narration output.", file=sys.stderr)
        return 1
    print(f"{'Reused' if reused else 'Saved'} {audio_path}")
    print(f"Measured duration: {metadata['duration_seconds']} seconds; voice: {args.voice}.")
    if not metadata["within_target_duration"]:
        print("Timing review required: audio is outside the 30–60 second target; adjust script or speed explicitly.")
    print(DISCLOSURE + " Listen and review before production.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
