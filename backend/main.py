"""Run with python -m backend.main --fixture ID."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from dotenv import load_dotenv

from backend.normalize import normalize_fixture
from backend.sportmonks import SportmonksClient, SportmonksError
from backend.validate import FixtureValidationError

ROOT = Path(__file__).resolve().parents[1]


def positive_int(value):
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def save_json(path, value):
    """Replace each output atomically so interrupted writes do not corrupt JSON."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Retrieve and validate a completed EPL fixture.")
    parser.add_argument("--fixture", required=True, type=positive_int)
    parser.add_argument("--epl-league-id", type=positive_int,
                        default=os.getenv("EPL_LEAGUE_ID", "8"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "fixtures")
    parser.add_argument("--include-xg", action="store_true",
                        default=os.getenv("SPORTMONKS_INCLUDE_XG", "false").lower() == "true")
    args = parser.parse_args(argv)
    try:
        client = SportmonksClient(include_xg=args.include_xg)
        with client.session:
            payload = client.get_fixture(args.fixture)
        normalized = normalize_fixture(payload, args.epl_league_id)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        save_json(args.output_dir / f"{args.fixture}_raw.json", payload)
        save_json(args.output_dir / f"{args.fixture}_normalized.json", normalized)
    except (SportmonksError, FixtureValidationError, OSError, ValueError) as exc:
        # Never emit arbitrary exception text, which may include credentials or API content.
        message = str(exc) if isinstance(exc, (SportmonksError, FixtureValidationError)) else "Unable to save fixture JSON."
        print(f"Error: {message}", file=sys.stderr)
        return 1
    home, away, score = normalized["home_team"], normalized["away_team"], normalized["final_score"]
    print(f"{args.fixture}: {home['name']} {score['home']}–{score['away']} {away['name']} ({normalized['match_status']})")
    available = [name for name, pair in normalized["statistics"].items() if any(v is not None for v in pair.values())]
    print("Available statistics: " + (", ".join(available) or "none"))
    print(f"Saved raw and normalized JSON to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
