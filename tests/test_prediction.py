from copy import deepcopy
from datetime import datetime,timezone
from unittest.mock import Mock

import pytest

from backend.prediction import PredictionError,make_prediction,poisson_forecast,recent_form,teams_for_preview
from backend.prematch import PrematchClient
from backend.prediction_video import draw_prediction_frame
from backend.sportmonks import SportmonksError
from backend.video import VideoError,font_path

NOW=datetime(2026,11,14,tzinfo=timezone.utc)


@pytest.fixture
def forecast_input(payload):
    fixture=deepcopy(payload['data'])
    fixture.update(id=19878000,league_id=1082,state_id=1,state={'id':1,'state':'NS'},
                   starting_at='2026-11-21 12:00:00',league={'name':'Friendly International'})
    fixture.pop('scores')
    history=[]
    for i in range(5):
        past=deepcopy(payload['data'])
        past.update(id=100+i,league_id=1082,starting_at=f'2026-10-{10+i:02} 12:00:00')
        history.append(past)
    return fixture,{'home':history,'away':history}


def test_prediction_from_facts(forecast_input):
    fixture,histories=forecast_input
    result=make_prediction(fixture,histories,as_of=NOW,league_id=1082)
    assert result['content_type']=='prediction'
    assert result['league_id']==1082
    assert result['form']['home']['wins']==5
    assert result['form']['away']['wins']==0
    assert result['form']['home']['goals_for']==10
    assert result['form']['away']['goals_for']==5
    assert result['forecast']['calibrated'] is False
    assert result['forecast']['assumptions']['home_multiplier']==1
    assert abs(sum(result['forecast']['probabilities'].values())-1)<1e-10
    assert 75<=result['word_count']<=150
    assert 'Premier League' not in result['script']
    assert 'international friendlies' in result['script']
    assert ' '.join(section['text'] for section in result['sections'])==result['script']


@pytest.mark.parametrize('state',[2,5,10,11,22])
def test_started_or_cancelled_rejected(forecast_input,state):
    fixture,_=forecast_input
    fixture['state_id']=state
    with pytest.raises(PredictionError):
        teams_for_preview(fixture,NOW,1082)


def test_past_kickoff_rejected(forecast_input):
    fixture,_=forecast_input
    fixture['starting_at']='2026-11-13 12:00:00'
    with pytest.raises(PredictionError,match='future'):
        teams_for_preview(fixture,NOW,1082)


def test_wrong_league_rejected(forecast_input):
    fixture,_=forecast_input
    with pytest.raises(PredictionError):
        teams_for_preview(fixture,NOW,8)


def test_insufficient_form_rejected(forecast_input):
    _,history=forecast_input
    with pytest.raises(PredictionError,match='three'):
        recent_form(history['home'][:2],10,NOW,league_id=1082)


def test_no_future_results_leak(forecast_input):
    _,histories=forecast_input
    future=deepcopy(histories['home'][0])
    future.update(id=999,starting_at='2026-11-16 12:00:00')
    result=recent_form(histories['home']+[future],10,NOW,league_id=1082)
    assert 999 not in [match['fixture_id'] for match in result['matches']]
    assert result['sample_size']==5


def test_cross_competition_excluded(forecast_input):
    _,history=forecast_input
    other=deepcopy(history['home'][0])
    other.update(id=999,league_id=1)
    assert recent_form(history['home']+[other],10,NOW,league_id=1082)['sample_size']==5


def test_form_order_and_duplicates(forecast_input):
    _,history=forecast_input
    sample=recent_form(history['home']+history['home'],10,NOW,league_id=1082)
    assert sample['sample_size']==5
    assert sample['matches'][0]['fixture_id']==104


def test_symmetric_form_model():
    form={'goals_for':5,'goals_against':5,'sample_size':5}
    forecast=poisson_forecast(form,form)
    assert forecast['probabilities']['home']==pytest.approx(forecast['probabilities']['away'])
    assert forecast['model_goal_rates']['home']==forecast['model_goal_rates']['away']


def test_pick_matches_selected_outcome(forecast_input):
    fixture,history=forecast_input
    forecast=make_prediction(fixture,history,as_of=NOW,league_id=1082)['forecast']
    score=forecast['score_pick']
    outcome='home' if score['home']>score['away'] else 'away' if score['away']>score['home'] else 'draw'
    assert outcome==forecast['outcome']


def test_prediction_graphic(forecast_input):
    fixture,history=forecast_input
    result=make_prediction(fixture,history,as_of=NOW,league_id=1082)
    try:
        font_path()
    except VideoError:
        pytest.skip('No usable font')
    for word in (0,30,50,result['word_count']-1):
        image=draw_prediction_frame(result,{'word_start':word,'text':'Prediction, not a result.'},0.5)
        assert image.size==(1080,1920)


def test_prematch_client_uses_no_prediction_addon(forecast_input):
    fixture,_=forecast_input
    session=Mock()
    session.get.return_value.status_code=200
    session.get.return_value.json.return_value={'data':fixture}
    client=PrematchClient(token='synthetic-key',session=session)
    assert client.upcoming_fixture(19878000)['data']['id']==19878000
    assert 'predictions' not in session.get.call_args.kwargs['params']['include']


def test_prematch_client_access_error():
    session=Mock()
    session.get.return_value.status_code=403
    with pytest.raises(SportmonksError):
        PrematchClient(token='synthetic-key',session=session).upcoming_fixture(1)


def test_single_draw_grammar(forecast_input):
    fixture,histories=forecast_input
    # Shared history fixture: change one home win into a draw.
    histories['home'][0]['scores'][2]['score']['goals']=1
    result=make_prediction(fixture,histories,as_of=NOW,league_id=1082)
    assert '1 draw in their last' in result['script']
    assert '1 draws' not in result['script']
