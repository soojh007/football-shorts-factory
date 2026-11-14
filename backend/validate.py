"""Required match checks and the stable downstream schema."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError


class FixtureValidationError(ValueError):
    """A fixture cannot safely enter the production pipeline."""


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Team(Schema):
    id: StrictInt = Field(gt=0)
    name: str = Field(min_length=1)


class Score(Schema):
    home: StrictInt = Field(ge=0)
    away: StrictInt = Field(ge=0)


class Pair(Schema):
    home: float | None = Field(default=None, ge=0)
    away: float | None = Field(default=None, ge=0)


class Statistics(Schema):
    possession: Pair
    total_shots: Pair
    shots_on_target: Pair
    expected_goals: Pair
    corners: Pair
    yellow_cards: Pair
    red_cards: Pair


class GoalEvent(Schema):
    id: int | None = None
    participant_id: int | None = None
    side: Literal["home", "away"] | None = None
    type: Literal["goal", "owngoal", "penalty"]
    minute: int | None = None
    extra_minute: int | None = None
    player_name: str | None = None
    result: str | None = None


class NormalizedFixture(Schema):
    schema_version: Literal[1] = 1
    fixture_id: StrictInt = Field(gt=0)
    league_id: StrictInt = Field(gt=0)
    season_id: StrictInt = Field(gt=0)
    match_date: datetime
    home_team: Team
    away_team: Team
    final_score: Score
    match_status: Literal["FT", "AET", "FT_PEN"]
    statistics: Statistics
    goal_events: list[GoalEvent] | None


COMPLETED_STATES = {5: "FT", 7: "AET", 8: "FT_PEN"}


def validate_fixture(fixture, epl_league_id=8):
    """Validate source semantics; return teams, final score and canonical state."""
    if not isinstance(fixture, dict):
        raise FixtureValidationError("Missing fixture data.")
    # Check relationship shapes before traversing untrusted provider JSON.
    for field in ("participants", "scores", "statistics", "expected", "events"):
        entries = fixture.get(field)
        if entries is None:
            continue
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise FixtureValidationError("Invalid fixture relationship data.")
        for entry in entries:
            for nested in ("meta", "score", "data", "type"):
                if entry.get(nested) is not None and not isinstance(entry[nested], dict):
                    raise FixtureValidationError("Invalid nested fixture data.")
            metadata = entry.get("type") or {}
            if any(metadata.get(key) is not None and not isinstance(metadata[key], str)
                   for key in ("code", "developer_name")):
                raise FixtureValidationError("Invalid type metadata.")
            if entry.get("participant_id") is not None and type(entry["participant_id"]) is not int:
                raise FixtureValidationError("Invalid participant identifier.")
    if fixture.get("state") is not None and not isinstance(fixture["state"], dict):
        raise FixtureValidationError("Invalid fixture state data.")
    if type(epl_league_id) is not int or epl_league_id <= 0:
        raise FixtureValidationError("EPL league ID must be a positive integer.")
    if fixture.get("league_id") != epl_league_id:
        raise FixtureValidationError("Fixture is not in the configured EPL league.")
    state = fixture.get("state") or {}
    state_id = fixture.get("state_id", state.get("id"))
    if type(state_id) is not int or state_id not in COMPLETED_STATES:
        raise FixtureValidationError("Fixture is not completed.")
    if state.get("id", state_id) != state_id:
        raise FixtureValidationError("Fixture state identifiers disagree.")
    if state.get("state", COMPLETED_STATES[state_id]) != COMPLETED_STATES[state_id]:
        raise FixtureValidationError("Fixture state code disagrees with state ID.")
    teams = {}
    for team in fixture.get("participants") or []:
        side = (team.get("meta") or {}).get("location")
        if side not in ("home", "away") or side in teams:
            raise FixtureValidationError("Missing or ambiguous team locations.")
        try:
            teams[side] = Team(id=team.get("id"), name=(team.get("name") or "").strip())
        except (ValidationError, AttributeError):
            raise FixtureValidationError("Missing team information.") from None
    if set(teams) != {"home", "away"} or teams["home"].id == teams["away"].id:
        raise FixtureValidationError("Missing or duplicate team information.")
    sides = {team.id: side for side, team in teams.items()}
    scores = {}
    for entry in fixture.get("scores") or []:
        if entry.get("description") != "CURRENT":
            continue
        side = sides.get(entry.get("participant_id"))
        score = entry.get("score") or {}
        goals = score.get("goals")
        if (side is None or side in scores or score.get("participant") != side
                or type(goals) is not int or goals < 0):
            raise FixtureValidationError("Invalid or conflicting final score mapping.")
        scores[side] = goals
    if set(scores) != {"home", "away"}:
        raise FixtureValidationError("Missing CURRENT final scores.")
    return teams, Score(**scores), COMPLETED_STATES[state_id]
