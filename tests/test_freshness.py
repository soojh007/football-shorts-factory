from copy import deepcopy
from datetime import datetime,timezone
from unittest.mock import Mock

from backend.freshness import latest_completed

NOW=datetime(2026,11,17,9,tzinfo=timezone.utc)


def test_latest_crosses_competitions_and_excludes_future_and_invalid_results(payload):
    past=deepcopy(payload['data']);past.update(id=100,starting_at='2026-11-14 10:15:00',league_id=24,league={'name':'Cup'})
    old=deepcopy(past);old.update(id=99,starting_at='2026-11-13 10:00:00',league_id=8)
    future=deepcopy(past);future.update(id=101,starting_at='2026-11-18 10:00:00')
    invalid=deepcopy(past);invalid.update(id=102,starting_at='2026-11-16 10:00:00',scores=[])
    client=Mock();client.fixture_window.return_value=[future,old,invalid,past]
    latest=latest_completed(client,{'home':{'id':20,'name':'Away FC'}},NOW)['home']
    assert latest['fixture_id']==100 and latest['result']=='L'
    assert (latest['goals_for'],latest['goals_against'])==(1,2)
    assert latest['competition']=='Cup'
    assert client.fixture_window.call_args.kwargs['league_id'] is None


def test_no_accessible_latest_result_is_optional():
    client=Mock();client.fixture_window.return_value=[]
    assert latest_completed(client,{'home':{'id':10}},NOW)=={}
