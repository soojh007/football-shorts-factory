from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest

from backend.contextual_prediction import contextual_prediction, venue_context
from backend.discover import available_matches
from backend.prediction import PredictionError
from backend.research import ResearchError, validate_research
from backend.player_media import MediaError, collect_player_media, commons_photo

NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)

@pytest.fixture
def contextual_input(payload):
    fixture = deepcopy(payload['data'])
    fixture.update(id=999, league_id=1082, state_id=1, state={'id':1,'state':'NS'}, starting_at='2026-11-14 00:45:00',
                   venue={'name':'Home Ground','country_id':1}, metadata=[{'type':{'code':'neutral_venue'},'values':{'neutral':False}}])
    fixture['participants'][0]['country_id']=2
    fixture['participants'][1]['country_id']=1
    lineups={'confirmed':True,'fixture_id':999}
    histories={}
    for side,team in [('home',10),('away',20)]:
        lineups[side]={'starters':[{'player_id':team*100+i,'name':f'{side} player {i}'} for i in range(11)]}
        histories[side]=[]
        for n in range(5):
            past=deepcopy(payload['data'])
            past.update(id=100+n, league_id=1082, starting_at=f'2026-10-{10+n:02} 12:00:00')
            # Distinct historical XIs and scores make overlap weighting observable.
            past['lineups']=[{'team_id':team,'type_id':11,'player_id':team*100+i+(0 if n==4 else 50),
                             'details':[{'type':{'code':'rating'},'data':{'value':8 if n==4 else 6}}]} for i in range(11)]
            for score in past['scores']:
                if score['description']=='CURRENT' and score['participant_id']==team:
                    score['score']['goals']=4 if n==4 else 1
            histories[side].append(past)
    return fixture,histories,lineups


def test_xi_changes_forecast_with_same_past_scores(contextual_input):
    fixture,histories,lineups=contextual_input
    original=contextual_prediction(fixture,histories,lineups,NOW)
    changed=deepcopy(lineups)
    for player in changed['home']['starters']: player['player_id']+=50
    updated=contextual_prediction(fixture,histories,changed,NOW)
    assert original['forecast']['model_goal_rates']['home'] != updated['forecast']['model_goal_rates']['home']
    assert original['context']['lineup_profiles']['home']['latest_starters_retained']==11
    assert updated['context']['lineup_profiles']['home']['latest_starters_retained']==0
    assert original['forecast']['calibrated'] is False
    assert "I'm" in original['script'] and 'My call' in original['script']
    assert 75<=original['word_count']<=150


def test_neutral_venue_changes_forecast(contextual_input):
    fixture,histories,lineups=contextual_input
    home=contextual_prediction(fixture,histories,lineups,NOW)
    fixture['metadata'][0]['values']['neutral']=True
    neutral=contextual_prediction(fixture,histories,lineups,NOW)
    assert home['forecast']['model_goal_rates']['home'] > neutral['forecast']['model_goal_rates']['home']
    assert neutral['context']['venue']['role']=='neutral'


def test_missing_ratings_no_fabricated_boost(contextual_input):
    fixture,histories,lineups=contextual_input
    for rows in histories.values():
        for match in rows:
            for player in match['lineups']: player['details']=[]
    result=contextual_prediction(fixture,histories,lineups,NOW)
    profile=result['context']['lineup_profiles']['home']
    assert profile['current_starter_mean_rating'] is None
    assert profile['rating_factor']==1 and profile['rating_factor_applied'] is False


def test_insufficient_historical_lineups_rejected(contextual_input):
    fixture,histories,lineups=contextual_input
    for match in histories['home'][:3]: match['lineups']=[]
    with pytest.raises(PredictionError,match='three'): contextual_prediction(fixture,histories,lineups,NOW)


def test_unverified_neutrality_no_home_edge(contextual_input):
    fixture,_,_=contextual_input
    fixture['metadata']=[]
    assert venue_context(fixture,10)['role']=='neutrality_unverified'
    fixture['venue']={}
    with pytest.raises(PredictionError,match='venue'): venue_context(fixture,10)


def research_payload(claims=None,venue='unverified'):
    return {'status':'completed','output':[
        {'type':'web_search_call','status':'completed','action':{'sources':[{'url':'https://example.org/team-news'}]}},
        {'type':'message','content':[{'type':'output_text','text':json.dumps({'venue_check':venue,'claims':claims or [],'gaps':[]})}]}]}


def claim(**kw):
    return {'topic':'team_news','summary':'The team has announced its starting eleven.','source_url':'https://example.org/team-news',
            'publisher':'Official association','published_at':'2026-11-13T12:00:00Z','status':'confirmed',**kw}


def test_research_requires_actual_completed_search():
    payload=research_payload([claim()]); payload['output']=payload['output'][1:]
    with pytest.raises(ResearchError,match='search'): validate_research(payload,{'id':1},NOW)


def test_research_drops_unsupported_future_and_stale_news():
    payload=research_payload([claim(source_url='https://invented.example/news'),claim(published_at='2026-11-15T00:00:00Z'),
                              claim(published_at='2026-09-01T00:00:00Z'),claim()])
    result=validate_research(payload,{'id':1},NOW)
    assert len(result['claims'])==1
    assert result['claims'][0]['source_url']=='https://example.org/team-news'
    assert result['performed'] is True
    assert result['gaps']


def test_undated_research_never_confirmed():
    result=validate_research(research_payload([claim(published_at=None)]),{'id':1},NOW)
    assert result['claims'][0]['status']=='reported'


def test_conflicting_venue_stops_generation():
    with pytest.raises(ResearchError,match='conflict'): validate_research(research_payload(venue='conflicting'),{'id':1},NOW)


def test_discovery_filters_window_and_started_matches(contextual_input):
    fixture,_,_=contextual_input
    later=deepcopy(fixture); later.update(id=1000,starting_at='2026-11-14 01:45:00')
    past=deepcopy(fixture); past.update(id=1001,starting_at='2026-11-13 23:45:00')
    started=deepcopy(fixture); started.update(id=1002,state_id=2)
    client=Mock(); client.fixture_window.return_value=[later,past,started,fixture]
    assert [m['fixture_id'] for m in available_matches(client,hours=1,now=NOW)['matches']]==[999]
    assert [m['fixture_id'] for m in available_matches(client,hours=2,now=NOW)['matches']]==[999,1000]
    assert available_matches(client,now=NOW)['matches'][0]['lineups_status']=='not_checked'


def test_discovery_crosses_midnight(contextual_input):
    client=Mock(); client.fixture_window.return_value=[]
    now=NOW.replace(hour=23)
    available_matches(client,now=now)
    client.fixture_window.assert_called_once_with(now.date(),(now+timedelta(hours=2)).date(),league_id=1082)


def test_commons_rejects_other_player_and_unsupported_license():
    session=Mock(); session.get.return_value.status_code=200
    session.get.return_value.json.return_value={'query':{'pages':{'1':{'title':'File:Someone Else.jpg','imageinfo':[{'extmetadata':{'LicenseShortName':{'value':'CC0'}}}]}}}}
    assert commons_photo('Kaoru Mitoma',session) is None


def test_real_image_required_for_each_team(tmp_path,monkeypatch):
    monkeypatch.setattr('backend.player_media.commons_photo',lambda *args:None)
    prediction={'featured_players':{side:[{'player_id':i,'name':'A Player'}] for i,side in enumerate(('home','away'))}}
    with pytest.raises(MediaError,match='visual'): collect_player_media(prediction,tmp_path,session=Mock())
