"""Generate analysis from saved JSON: python -m backend.analyze --fixture ID."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from dotenv import load_dotenv

from backend.analysis import AnalysisError, generate_analysis
from backend.main import ROOT, positive_int, save_json
from backend.openai_client import OpenAIClient


def save_text(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Generate evidence-constrained EPL match analysis and narration.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=positive_int)
    source.add_argument("--input", type=Path, help="Path to a normalized fixture JSON file")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "generated")
    parser.add_argument("--epl-league-id", type=positive_int, default=os.getenv("EPL_LEAGUE_ID", "8"))
    parser.add_argument("--model", help="Override OPENAI_MODEL")
    parser.add_argument("--offline-preview", action="store_true", help="Use deterministic ordering; makes no AI request")
    args = parser.parse_args(argv)
    input_path = args.input or ROOT / "data" / "fixtures" / f"{args.fixture}_normalized.json"
    try:
        source_data = json.loads(input_path.read_text(encoding="utf-8"))
        if args.fixture and (not isinstance(source_data, dict) or source_data.get("fixture_id") != args.fixture):
            raise AnalysisError("Input fixture ID does not match the requested fixture.")
        if args.offline_preview:
            result = generate_analysis(source_data, offline_preview=True, league_id=args.epl_league_id)
        else:
            client = OpenAIClient(model=args.model)
            with client.session:
                result = generate_analysis(source_data, client, league_id=args.epl_league_id)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{result['fixture_id']}_" + ("preview" if args.offline_preview else "analysis")
        save_json(args.output_dir / f"{prefix}.json", result)
        save_text(args.output_dir / f"{prefix}_script.txt", result["script"])
    except AnalysisError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Error: Unable to read normalized JSON or save analysis output.", file=sys.stderr)
        return 1
    print(result["title"])
    print(f"Mode: {result['mode']}; {result['word_count']} words; estimated {result['estimated_duration_seconds']} seconds at 150 words/minute.")
    print(f"Saved {prefix}.json and {prefix}_script.txt to {args.output_dir}")
    print("Editorial review required before production.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
