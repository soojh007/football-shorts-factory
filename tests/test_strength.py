from copy import deepcopy
from datetime import datetime,timezone
import json
import math

import pytest
from backend.strength import strength_rates,load_model
from backend.contextual_prediction import distribution
from backend.calibrate_strength import samples

NOW=datetime(2026,11,17,9,tzinfo=timezone.utc)
FIXTURE={'league_id':1082,'participants':[{'type':'national','gender':'male'},{'type':'national','gender':'male'}]}


def ranks(home=1800,away=1060):
    return {'home':{'points':home,'rank':6,'ranking_date':'2026-11-01','official':True},
            'away':{'points':away,'rank':149,'ranking_date':'2026-11-01','official':True}}


def test_large_strength_gap_changes_scores_despite_equal_recent_form():
    equal,_=strength_rates(ranks(1500,1500),FIXTURE,NOW,1.4,1.4,'neutral')
    gap,detail=strength_rates(ranks(),FIXTURE,NOW,1.4,1.4,'neutral')
    assert detail['fitted'] is True and detail['applied'] is True
    assert gap[0]>3*gap[1] and gap[0]-gap[1]>3
    assert abs(equal[0]-equal[1])<1e-9
    _,outcome,score,_=distribution(*gap)
    assert outcome=='home' and score['home']-score['away']>=3


def test_neutral_strength_forecast_is_symmetric_when_sides_swap():
    original,_=strength_rates(ranks(),FIXTURE,NOW,1.4,1.8,'neutral')
    reverse,_=strength_rates(ranks(1060,1800),FIXTURE,NOW,1.8,1.4,'neutral')
    assert original==pytest.approx(reverse[::-1])


def test_ordinal_rank_gap_does_not_invent_points():
    data=ranks();data['away']['points']=None
    result,detail=strength_rates(data,FIXTURE,NOW,1.4,1.4,'neutral')
    assert result is None and detail['applied'] is False
    data=ranks(1500,1500)
    result,_=strength_rates(data,FIXTURE,NOW,1.4,1.4,'neutral')
    assert result[0]==pytest.approx(result[1])


@pytest.mark.parametrize('change',[{'ranking_date':'2026-12-01'},{'ranking_date':'2026-10-01'},
    {'official':False},{'retrieved_at':'2026-11-17T09:01:00+00:00'},{'points':float('nan')}, {'points':True}])
def test_future_mismatched_or_invalid_strength_data_is_optional(change):
    data=ranks();data['home'].update(change)
    assert strength_rates(data,FIXTURE,NOW,1.4,1.4,'neutral')[0] is None


def test_clubs_and_pre_model_cutoffs_do_not_use_national_strength_model():
    fixture=deepcopy(FIXTURE);fixture['participants'][0]['type']='domestic'
    assert strength_rates(ranks(),fixture,NOW,1.4,1.4,'neutral')[0] is None
    data=ranks()
    for row in data.values():row['ranking_date']='2024-08-01'
    result,detail=strength_rates(data,FIXTURE,datetime(2024,9,1,tzinfo=timezone.utc),1.4,1.4,'neutral')
    assert result is None and detail['reason']=='strength_model_not_available_before_cutoff'


def test_bundled_fit_has_a_chronological_holdout_and_beats_capped_baseline():
    model=load_model()
    assert model['train_end']<model['holdout_start']<=model['evaluated_through']<'2026-01-01'
    assert model['training_fixtures']>=300 and model['validation_passed']
    for group in ('all','large_gap_500_plus'):
        result=model['validation'][group]
        assert result['strength_model']['goal_nll_per_fixture']<result['capped_fifa']['goal_nll_per_fixture']
        assert result['strength_model']['goal_difference_mae']<result['capped_fifa']['goal_difference_mae']


def test_historical_rank_join_never_uses_same_day_or_future_release(tmp_path):
    ranking=tmp_path/'ranks.csv';results=tmp_path/'matches.csv'
    ranking.write_text('team,total_points,date\nA,1100,2018-08-30\nB,2000,2018-08-30\nA,2500,2018-08-31\nA,2900,2018-09-02\n')
    results.write_text('date,home_team,away_team,home_score,away_score,tournament,country,neutral\n2018-08-31,A,B,0,4,Friendly,A,FALSE\n2018-09-03,A,B,9,0,Friendly,A,FALSE\n')
    from datetime import date
    rows,_=samples(results,ranking,end=date(2018,8,31))
    assert len(rows)==1
    assert rows[0]['features'][0][1]==pytest.approx((1100-2000)/600)


def test_score_grid_covers_large_expected_goal_totals():
    probabilities,outcome,score,mass=distribution(.2,20)
    assert outcome=='away' and score['away']>=19
    assert sum(probabilities.values())==pytest.approx(1)
    assert probabilities['away']>.99 and 0<mass<1


def test_extrapolation_guard_is_symmetric_outside_the_training_range():
    original,detail=strength_rates(ranks(2500,500),FIXTURE,NOW,1.4,1.4,'neutral')
    reverse,_=strength_rates(ranks(500,2500),FIXTURE,NOW,1.4,1.4,'neutral')
    assert detail['points_gap_clipped_to_training_domain']
    assert original==pytest.approx(reverse[::-1])
