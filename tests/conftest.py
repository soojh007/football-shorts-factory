import pytest


@pytest.fixture
def payload():
    # Deliberately reverse participants and score entries; do not rely on array order.
    return {"data": {
        "id": 19427552, "league_id": 8, "season_id": 25583,
        "starting_at": "2025-08-16 14:00:00", "state_id": 5,
        "state": {"id": 5, "state": "FT"},
        "participants": [
            {"id": 20, "name": "Away FC", "meta": {"location": "away"}},
            {"id": 10, "name": "Home FC", "meta": {"location": "home"}},
        ],
        "scores": [
            {"participant_id": 20, "description": "CURRENT", "score": {"goals": 1, "participant": "away"}},
            {"participant_id": 10, "description": "1ST_HALF", "score": {"goals": 0, "participant": "home"}},
            {"participant_id": 10, "description": "CURRENT", "score": {"goals": 2, "participant": "home"}},
        ],
        "statistics": [
            {"participant_id": 20, "type_id": 45, "type": {"code": "ball-possession"}, "data": {"value": 40}},
            {"participant_id": 10, "type_id": 45, "type": {"code": "ball-possession"}, "data": {"value": 60}},
            {"participant_id": 10, "type_id": 42, "type": {"code": "shots-total"}, "data": {"value": 12}},
        ],
        "events": [{"id": 1, "participant_id": 10, "type": {"code": "goal"},
                    "minute": 50, "extra_minute": None, "player_name": "A Player", "result": "1-0"}],
    }}
