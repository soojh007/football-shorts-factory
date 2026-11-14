import pytest

from backend.validate import FixtureValidationError, validate_fixture


@pytest.mark.parametrize("state_id", [1, 2, 3, 4, 10, 14, 15, 17, 22, 26, None])
def test_non_completed(payload, state_id):
    payload["data"]["state_id"] = state_id
    with pytest.raises(FixtureValidationError, match="not completed"):
        validate_fixture(payload["data"])


@pytest.mark.parametrize("state_id,code", [(5, "FT"), (7, "AET"), (8, "FT_PEN")])
def test_completed_states(payload, state_id, code):
    payload["data"].update(state_id=state_id, state={"id": state_id, "state": code})
    assert validate_fixture(payload["data"])[2] == code


def test_non_epl(payload):
    payload["data"]["league_id"] = 564
    with pytest.raises(FixtureValidationError, match="EPL"):
        validate_fixture(payload["data"])
    validate_fixture(payload["data"], epl_league_id=564)


@pytest.mark.parametrize("participants", [None, [], [{"id": 1, "name": "FC"}]])
def test_missing_teams(payload, participants):
    payload["data"]["participants"] = participants
    with pytest.raises(FixtureValidationError):
        validate_fixture(payload["data"])


def test_missing_scores(payload):
    payload["data"]["scores"] = payload["data"]["scores"][:1]
    with pytest.raises(FixtureValidationError, match="final scores"):
        validate_fixture(payload["data"])


def test_period_score_is_not_final(payload):
    for entry in payload["data"]["scores"]:
        entry["description"] = "2ND_HALF_ONLY"
    with pytest.raises(FixtureValidationError):
        validate_fixture(payload["data"])


def test_score_location_conflict(payload):
    payload["data"]["scores"][0]["score"]["participant"] = "home"
    with pytest.raises(FixtureValidationError, match="mapping"):
        validate_fixture(payload["data"])


@pytest.mark.parametrize("goals", [None, -1, True, "2"])
def test_invalid_score(payload, goals):
    payload["data"]["scores"][0]["score"]["goals"] = goals
    with pytest.raises(FixtureValidationError):
        validate_fixture(payload["data"])


def test_duplicate_score(payload):
    payload["data"]["scores"].append(payload["data"]["scores"][0])
    with pytest.raises(FixtureValidationError):
        validate_fixture(payload["data"])


def test_conflicting_state(payload):
    payload["data"]["state"]["id"] = 22
    with pytest.raises(FixtureValidationError):
        validate_fixture(payload["data"])


@pytest.mark.parametrize("field,value", [
    ("participants", {}), ("scores", [None]), ("state", "FT"),
    ("statistics", [42]), ("events", [{"type": "goal"}]),
    ("expected", [{"type": {"code": 5304}}]),
])
def test_malformed_relationships(payload, field, value):
    payload["data"][field] = value
    with pytest.raises(FixtureValidationError):
        validate_fixture(payload["data"])
