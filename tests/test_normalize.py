import pytest

from backend.normalize import normalize_fixture
from backend.validate import FixtureValidationError


def test_completed_match(payload):
    result = normalize_fixture(payload)
    assert result["fixture_id"] == 19427552
    assert result["match_status"] == "FT"
    assert result["statistics"]["possession"] == {"home": 60, "away": 40}
    assert result["goal_events"][0]["side"] == "home"
    assert result["match_date"] == "2025-08-16T14:00:00"


def test_home_away_scores(payload):
    result = normalize_fixture(payload)
    assert result["home_team"]["id"] == 10
    assert result["away_team"]["id"] == 20
    assert result["final_score"] == {"home": 2, "away": 1}


@pytest.mark.parametrize("missing", [None, []])
def test_missing_statistics(payload, missing):
    payload["data"]["statistics"] = missing
    result = normalize_fixture(payload)
    assert all(pair == {"home": None, "away": None} for pair in result["statistics"].values())


def test_never_guess_numeric_type_id(payload):
    payload["data"]["statistics"] = [{"participant_id": 10, "type_id": 45, "data": {"value": 99}}]
    assert normalize_fixture(payload)["statistics"]["possession"]["home"] is None


def test_xg_and_zero(payload):
    payload["data"]["expected"] = [{"participant_id": 20, "location": "away",
        "type": {"code": "expected-goals"}, "data": {"value": 0}}]
    assert normalize_fixture(payload)["statistics"]["expected_goals"] == {"home": None, "away": 0}


def test_all_statistic_metadata(payload):
    codes = {"shots-on-target": "shots_on_target", "corners": "corners",
             "yellowcards": "yellow_cards", "redcards": "red_cards"}
    payload["data"]["statistics"] = [
        {"participant_id": 20, "type": {"code": code}, "data": {"value": 3}}
        for code in codes
    ]
    result = normalize_fixture(payload)
    for name in codes.values():
        assert result["statistics"][name] == {"home": None, "away": 3}


@pytest.mark.parametrize("value", [-1, "bad", float("nan"), float("inf"), True, 101])
def test_bad_statistic(payload, value):
    payload["data"]["statistics"][0]["data"]["value"] = value
    with pytest.raises(FixtureValidationError):
        normalize_fixture(payload)


def test_goal_types(payload):
    payload["data"]["events"] = [
        {"participant_id": 20, "type": {"code": code}, "minute": 30}
        for code in ["goal", "owngoal", "penalty", "missed_penalty", "yellowcard"]
    ]
    goals = normalize_fixture(payload)["goal_events"]
    assert [event["type"] for event in goals] == ["goal", "owngoal", "penalty"]
    assert all(event["side"] == "away" for event in goals)


def test_unavailable_events(payload):
    del payload["data"]["events"]
    assert normalize_fixture(payload)["goal_events"] is None


def test_required_date(payload):
    payload["data"]["starting_at"] = None
    with pytest.raises(FixtureValidationError):
        normalize_fixture(payload)
