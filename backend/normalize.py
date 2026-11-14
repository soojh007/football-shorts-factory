"""Normalize by participant IDs and semantic type metadata, never guessed IDs."""
import math

from pydantic import ValidationError

from backend.validate import FixtureValidationError, NormalizedFixture, validate_fixture

STAT_CODES = {
    "ball-possession": "possession", "shots-total": "total_shots",
    "shots-on-target": "shots_on_target", "expected-goals": "expected_goals",
    "corners": "corners", "yellowcards": "yellow_cards", "redcards": "red_cards",
}
GOAL_CODES = {"goal", "owngoal", "penalty"}


def type_code(record):
    metadata = record.get("type") or {}
    return metadata.get("code") or (metadata.get("developer_name") or "").lower().replace("_", "-")


def normalize_fixture(payload, epl_league_id=8):
    fixture = payload.get("data") if isinstance(payload, dict) else None
    teams, score, status = validate_fixture(fixture, epl_league_id)
    sides = {team.id: side for side, team in teams.items()}
    stats = {name: {"home": None, "away": None} for name in STAT_CODES.values()}
    # xGFixture is returned under `expected`; ordinary stats may also contain xG.
    for entry in (fixture.get("statistics") or []) + (fixture.get("expected") or []):
        name = STAT_CODES.get(type_code(entry))
        side = sides.get(entry.get("participant_id"))
        if name is None or side is None:
            continue
        if entry.get("location", side) != side:
            raise FixtureValidationError("Statistic location disagrees with participant.")
        value = (entry.get("data") or {}).get("value")
        if value is None:
            continue
        if isinstance(value, bool):
            raise FixtureValidationError("Invalid statistic value.")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise FixtureValidationError("Invalid statistic value.") from None
        if not math.isfinite(value) or value < 0 or (name == "possession" and value > 100):
            raise FixtureValidationError("Statistic value outside valid range.")
        if name not in ("possession", "expected_goals") and not value.is_integer():
            raise FixtureValidationError("Count statistic must be an integer.")
        previous = stats[name][side]
        if previous is not None and previous != value:
            raise FixtureValidationError("Conflicting duplicate statistics.")
        stats[name][side] = value
    events = None if fixture.get("events") is None else []
    for event in fixture.get("events") or []:
        code = type_code(event)
        if code not in GOAL_CODES:
            continue
        # Preserve provider attribution for own goals; do not infer a beneficiary.
        events.append({
            "id": event.get("id"), "participant_id": event.get("participant_id"),
            "side": sides.get(event.get("participant_id")), "type": code,
            "minute": event.get("minute"), "extra_minute": event.get("extra_minute"),
            "player_name": event.get("player_name"), "result": event.get("result"),
        })
    try:
        normalized = NormalizedFixture(
            fixture_id=fixture.get("id"), league_id=fixture.get("league_id"),
            season_id=fixture.get("season_id"), match_date=fixture.get("starting_at"),
            home_team=teams["home"], away_team=teams["away"], final_score=score,
            match_status=status, statistics=stats, goal_events=events,
        )
    except ValidationError:
        raise FixtureValidationError("Fixture has invalid required fields or goal events.") from None
    return normalized.model_dump(mode="json")
