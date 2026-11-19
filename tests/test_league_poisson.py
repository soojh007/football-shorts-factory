from copy import deepcopy
from datetime import datetime,timedelta,timezone
import math
from unittest.mock import Mock

import pytest
from backend.league_poisson import league_rates,score_matrix,poisson_masses,collect_league_results
from backend.prediction import PredictionError

NOW=datetime(2026,11,19,tzinfo=timezone.utc)


@pytest.fixture
def league_data(payload):
    fixture=deepcopy(payload['data'])
    fixture.update(id=999,league_id=564,season_id=123,state_id=1,state={'id':1},starting_at=(NOW+timedelta(hours=1)).isoformat())
    for p in fixture['participants']:p['type']='domestic'
    def match(i,home_id=10,away_id=20,hg=2,ag=1):
        f=deepcopy(payload['data'])
        f.update(id=i,league_id=564,season_id=123,starting_at=(NOW-timedelta(days=i)).isoformat())
        for p in f['participants']:p['id']={'home':home_id,'away':away_id}[p['meta']['location']]
        f['scores']=[{'participant_id':home_id,'description':'CURRENT','score':{'participant':'home','goals':hg}},
                     {'participant_id':away_id,'description':'CURRENT','score':{'participant':'away','goals':ag}}]
        return f
    return fixture,[match(i) for i in range(1,11)],match


def test_example_matrix_and_home_win_triangle():
    result=score_matrix(1.5,1)
    grid=result['score_matrix']['cells']
    assert grid[0][0]==pytest.approx(math.exp(-2.5))
    assert poisson_masses(1.5)[:3]==pytest.approx([.2231301601,.3346952402,.2510214302])
    assert result['probabilities']==pytest.approx({'home':.4879456833,'draw':.2598473743,'away':.2522069424})
    assert sum(result['probabilities'].values())==pytest.approx(1)
    assert sum(p for h,row in enumerate(grid) for a,p in enumerate(row) if h>a)==pytest.approx(result['probabilities']['home'])
    assert result['overall_modal_score']=={'home':1,'away':0}
    assert result['score_matrix']['tail_probability']<2e-12


def test_baseline_strength_recovers_league_lambdas(league_data):
    f,rows,_=league_data
    rates,info=league_rates(f,rows,NOW)
    assert rates==pytest.approx((2,1))
    assert info['league_goal_averages']=={'home':2,'away':1}
    assert info['teams']['home']['attack_strength']==1
    assert info['teams']['away']['defence_weakness']==1
    assert info['teams']['home']['goals_against_baseline']==1
    assert info['teams']['away']['goals_against_baseline']==2


def test_asymmetric_strengths_use_correct_opponent_denominators(league_data):
    f,_,match=league_data
    rows=[match(i,100+i,200+i) for i in range(1,7)]
    rows += [match(7,10,300,4,0),match(8,10,301,4,0),match(9,302,20,1,2),match(10,303,20,1,2)]
    rates,info=league_rates(f,rows,NOW)
    assert info['league_goal_averages']==pytest.approx({'home':2.2,'away':1})
    assert rates[0]==pytest.approx(((8+3*2.2)/5)*((2+3*2.2)/5)/2.2)
    assert rates[1]==pytest.approx(((4+3)/5)*((0+3)/5))


def test_neutral_uses_pooled_team_rates_and_is_role_symmetric(league_data):
    f,rows,_=league_data
    rates,info=league_rates(f,rows,NOW,neutral=True)
    swapped=deepcopy(f)
    for p in swapped['participants']:p['meta']['location']='away' if p['meta']['location']=='home' else 'home'
    reverse,other=league_rates(swapped,rows,NOW,neutral=True)
    assert reverse==pytest.approx(rates[::-1])
    assert info['teams']['home']['goals_for_baseline']==1.5
    assert other['venue_basis']=='neutral_pooled'


def test_deduplication_and_wrong_season_league_future_incomplete_excluded(league_data):
    f,rows,match=league_data
    extras=[deepcopy(rows[0])]
    for i,changes in enumerate([{'league_id':8},{'season_id':124},{'state_id':1},
                               {'starting_at':(NOW+timedelta(hours=1)).isoformat()},
                               {'starting_at':(NOW-timedelta(days=181)).isoformat()}],11):
        row=match(i);row.update(changes);extras.append(row)
    rates,info=league_rates(f,rows+extras,NOW)
    assert rates==pytest.approx((2,1))
    assert info['sample_size']==10
    assert info['fixture_ids']==list(range(10,0,-1))


def test_conflicting_duplicates_do_not_enter_baseline(league_data):
    f,rows,match=league_data
    _,info=league_rates(f,rows+[match(1,hg=8)],NOW)
    assert not info['applied'] and info['sample_size']==9
    assert info['excluded_conflicting_fixture_ids']==[1]


def test_no_role_results_shrink_to_measured_baseline(league_data):
    f,_,match=league_data
    rows=[match(i,100+i,200+i) for i in range(1,11)]
    rates,info=league_rates(f,rows,NOW)
    assert rates==pytest.approx((2,1))
    assert info['teams']['home']['sample_size']==0
    assert info['teams']['away']['sample_size']==0


def test_missing_or_zero_baseline_falls_back_explicitly(league_data):
    f,rows,match=league_data
    assert league_rates(f,[],NOW)[0] is None
    assert league_rates(f,[match(i,hg=0,ag=0) for i in range(1,11)],NOW)[1]['reason']=='zero_scoring_baseline'
    f.pop('season_id')
    assert league_rates(f,rows,NOW)[1]['reason']=='missing_season_id'


@pytest.mark.parametrize('bad',[-1,float('nan'),float('inf'),True,101])
def test_invalid_lambdas_fail_clearly(bad):
    with pytest.raises(PredictionError):score_matrix(bad,1)


def test_large_gap_and_zero_goal_rates_keep_probability_mass():
    result=score_matrix(.2,20)
    assert result['score_matrix']['max_away_goals']>20
    assert sum(result['probabilities'].values())==pytest.approx(1)
    assert result['outcome']=='away'
    assert score_matrix(0,0)['probabilities']['draw']==1


def test_collection_uses_all_league_teams_and_bounded_date_windows(league_data):
    fixture,_,_=league_data
    client=Mock();client.fixture_window.return_value=[]
    collect_league_results(client,fixture,NOW)
    assert client.fixture_window.call_count==2
    for call in client.fixture_window.call_args_list:
        assert call.kwargs=={'league_id':564}
        assert (call.args[1]-call.args[0]).days<=99
        assert call.args[1]<=NOW.date()


def test_lineup_weight_provenance_only_counts_selected_observations(league_data):
    f,rows,_=league_data
    _,info=league_rates(f,rows,NOW,profiles={'home':{'samples':[{'fixture_id':99999,'lineup_weight':.35}]}})
    assert not info['lineup_weighting_applied']
    _,info=league_rates(f,rows,NOW,profiles={'home':{'samples':[{'fixture_id':1,'lineup_weight':.35}]}})
    assert info['lineup_weighting_applied']
