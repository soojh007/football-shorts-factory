from copy import deepcopy
from datetime import datetime,timedelta,timezone

import pytest
from backend.backtest import evaluate_round,prematch_fixture
from backend.league_poisson import MODEL_VERSION
from backend.prediction import PredictionError


@pytest.fixture
def historical_round(payload):
    kickoff=datetime(2026,11,6,20,tzinfo=timezone.utc)
    target=deepcopy(payload['data'])
    target.update(id=999,starting_at=kickoff.isoformat(),round_id=10,round={'name':'10'})
    for p in target['participants']:p['type']='domestic';p['meta']['winner']=True
    history=[]
    for i in range(10):
        row=deepcopy(target);row.update(id=100+i,round_id=9,starting_at=(kickoff-timedelta(days=10+i)).isoformat())
        history.append(row)
    return target,history


def test_backtest_inputs_strip_actual_results_and_winner_flags(historical_round):
    target,_=historical_round
    clean=prematch_fixture(target)
    assert clean['state_id']==1
    assert not any(k in clean for k in ['scores','events','lineups','statistics'])
    assert all(set(p['meta'])=={'location'} for p in clean['participants'])


def test_changing_target_scores_cannot_change_prediction(historical_round):
    target,history=historical_round
    first=evaluate_round([target],history,expected_matches=1)
    changed=deepcopy(target)
    for row in changed['scores']:
        if row['description']=='CURRENT':row['score']['goals']=9
    second=evaluate_round([changed],history,expected_matches=1)
    p=first['matches'][0]['predictions'][MODEL_VERSION]
    q=second['matches'][0]['predictions'][MODEL_VERSION]
    assert p['goal_rates']==q['goal_rates']
    assert p['probabilities']==q['probabilities']
    assert p['score_pick']==q['score_pick']
    assert first['matches'][0]['actual']!=second['matches'][0]['actual']


def test_entire_round_is_frozen_and_future_history_cannot_leak(historical_round):
    target,history=historical_round
    later=deepcopy(target);later.update(id=1000,starting_at='2026-11-08 20:00:00')
    poison=deepcopy(target);poison.update(id=2000,starting_at='2026-11-07 20:00:00')
    for row in poison['scores']:
        if row['description']=='CURRENT':row['score']['goals']=50
    report=evaluate_round([target,later],history+[target,later,poison],expected_matches=2)
    assert report['training_cutoff']=='2026-11-06T19:59:59+00:00'
    for result in report['matches']:
        assert result['league_sample_size']==10
        assert not {999,1000,2000}&set(result['training_fixture_ids'])
    assert report['matches'][0]['predictions'][MODEL_VERSION]['probabilities']==report['matches'][1]['predictions'][MODEL_VERSION]['probabilities']


def test_metrics_are_computed_from_all_predictions(historical_round):
    target,history=historical_round
    report=evaluate_round([target],history,expected_matches=1)
    p=report['matches'][0]['predictions'][MODEL_VERSION]
    m=report['metrics'][MODEL_VERSION]
    assert m['outcomes_correct']==int(p['correct_outcome'])
    assert m['exact_scores']==int(p['exact_score'])
    assert m['brier_score']==pytest.approx(sum((p['probabilities'][k]-(1 if k=='home' else 0))**2 for k in ('home','draw','away')))
    assert m['outcome_log_loss']>=0 and m['scoreline_log_loss']>=0
    assert not report['calibration_established']


def test_incomplete_mixed_or_unfinished_round_is_not_silently_selected(historical_round):
    target,history=historical_round
    with pytest.raises(PredictionError,match='incomplete'):evaluate_round([target],history)
    other=deepcopy(target);other.update(id=1000,season_id=1)
    with pytest.raises(PredictionError,match='one league'):evaluate_round([target,other],history,expected_matches=2)
    target['state_id']=1
    with pytest.raises(PredictionError,match='FT'):evaluate_round([target],history,expected_matches=1)
