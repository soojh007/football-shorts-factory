from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest

from backend.contextual_prediction import contextual_prediction, venue_context, venue_changed
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


def test_insufficient_historical_lineups_use_available_form(contextual_input):
    fixture,histories,lineups=contextual_input
    for match in histories['home'][:3]: match['lineups']=[]
    result=contextual_prediction(fixture,histories,lineups,NOW)
    assert result['context']['lineup_profiles']['home']['latest_starters_retained'] is None
    assert result['context']['lineup_profiles']['home']['rating_factor']==1
    assert 'None' not in result['script']


def test_unverified_neutrality_no_home_edge(contextual_input):
    fixture,_,_=contextual_input
    fixture['metadata']=[]
    assert venue_context(fixture,10)['role']=='neutrality_unverified'
    fixture['venue']={}
    assert venue_context(fixture,10)['name'] is None
    assert venue_context(fixture,10)['role']=='unknown'


def research_payload(claims=None,venue='unverified'):
    return {'status':'completed','output':[
        {'type':'web_search_call','status':'completed','action':{'sources':[{'url':'https://example.org/team-news'}]}},
        {'type':'message','content':[{'type':'output_text','text':json.dumps({'venue_check':venue,'claims':claims or [],'fifa_rankings':[],'gaps':[]})}]}]}


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


def test_conflicting_venue_excluded_without_stopping_research():
    result=validate_research(research_payload([claim(topic='venue'),claim()],venue='conflicting'),{'id':1},NOW)
    assert result['venue_check']=='conflicting'
    assert [row['topic'] for row in result['claims']]==['team_news']
    assert result['gaps']


def test_discovery_filters_window_and_started_matches(contextual_input):
    fixture,_,_=contextual_input
    later=deepcopy(fixture); later.update(id=1000,starting_at='2026-11-14 01:45:00')
    past=deepcopy(fixture); past.update(id=1001,starting_at='2026-11-13 23:45:00')
    started=deepcopy(fixture); started.update(id=1002,state_id=2)
    client=Mock(); client.subscribed_leagues.return_value=[]; client.fixture_window.return_value=[later,past,started,fixture]
    assert [m['fixture_id'] for m in available_matches(client,hours=1,now=NOW)['matches']]==[999]
    assert [m['fixture_id'] for m in available_matches(client,hours=2,now=NOW)['matches']]==[999,1000]
    assert available_matches(client,now=NOW)['matches'][0]['lineups_status']=='not_checked'


def test_discovery_crosses_midnight(contextual_input):
    client=Mock(); client.subscribed_leagues.return_value=[]; client.fixture_window.return_value=[]
    now=NOW.replace(hour=23)
    available_matches(client,now=now)
    client.fixture_window.assert_called_once_with(now.date(),(now+timedelta(hours=2)).date(),league_id=None)


def test_commons_rejects_other_player_and_unsupported_license():
    session=Mock(); session.get.return_value.status_code=200
    session.get.return_value.json.return_value={'query':{'pages':{'1':{'title':'File:Someone Else.jpg','imageinfo':[{'extmetadata':{'LicenseShortName':{'value':'CC0'}}}]}}}}
    assert commons_photo('Kaoru Mitoma',session) is None


def test_missing_free_media_uses_graphics_instead_of_fake_players(tmp_path,monkeypatch):
    monkeypatch.setattr('backend.player_media.commons_photo',lambda *args:None)
    prediction={'featured_players':{side:[{'player_id':i,'name':'A Player'}] for i,side in enumerate(('home','away'))}}
    assert collect_player_media(prediction,tmp_path,session=Mock())==[]


def test_tracking_parameters_do_not_discard_retrieved_source():
    payload=research_payload([claim()])
    payload['output'][0]['action']['sources'][0]['url']='https://example.org/team-news?utm_source=openai'
    assert len(validate_research(payload,{'id':1},NOW)['claims'])==1


def test_ai_predictions_excluded_and_unknown_publishers_not_confirmed():
    payload=research_payload([claim(source_url='https://scoregpt.app/news'),claim(),claim(source_url='https://jfa.jp/news')])
    payload['output'][0]['action']['sources'] += [{'url':'https://scoregpt.app/news'},{'url':'https://jfa.jp/news'}]
    result=validate_research(payload,{'id':1},NOW)
    assert len(result['claims'])==2
    assert result['claims'][0]['status']=='reported'
    assert result['claims'][1]['status']=='confirmed'


def test_unknown_venue_report_cannot_confirm_venue():
    result=validate_research(research_payload([claim(topic='venue')],venue='consistent'),{'id':1},NOW)
    assert result['venue_check']=='unverified'


@pytest.mark.parametrize('venue',[None,{}, {'name':'Known stadium'}, {'country_id':1}])
def test_optional_venue_never_blocks_forecast(contextual_input,venue):
    fixture,histories,lineups=contextual_input
    fixture['venue']=venue
    if not venue or 'country_id' not in venue: fixture['metadata']=[]
    result=contextual_prediction(fixture,histories,lineups,NOW)
    assert 75<=result['word_count']<=150
    assert 'None' not in result['script']
    if not venue or not venue.get('name'):
        assert 'venue' not in [section['kind'] for section in result['sections']]
    if not venue or 'country_id' not in venue:
        assert result['forecast']['assumptions']['applied_venue_factors']=={'home':1,'away':1}
        assert 'venue edge' not in result['script']


def test_conflicting_venue_does_not_change_available_lineup_forecast(contextual_input):
    fixture,histories,lineups=contextual_input
    result=contextual_prediction(fixture,histories,lineups,NOW,research={'performed':True,'venue_check':'conflicting','claims':[]})
    assert result['context']['venue']['name'] is None
    assert result['forecast']['assumptions']['applied_venue_factors']=={'home':1,'away':1}
    assert 'venue' not in [section['kind'] for section in result['sections']]
    assert result['context']['lineup_profiles']['home']['latest_starters_retained']==11


def test_venue_recheck_ignores_missing_fields_but_detects_known_changes():
    assert not venue_changed({'name':'Stadium','country_id':1},{'name':None,'country_id':None})
    assert not venue_changed({'name':None},{'name':'Newly available'})
    assert venue_changed({'name':'Old stadium'},{'name':'New stadium'})
    assert venue_changed({'neutral':False},{'neutral':True})


@pytest.mark.parametrize('venue',[None,{'city_name':'Basra'}])
def test_optional_venue_video_scenes_render(contextual_input,venue):
    from backend.personal_video import draw_personal_frame
    fixture,histories,lineups=contextual_input
    fixture['venue']=venue
    result=contextual_prediction(fixture,histories,lineups,NOW)
    word=0
    for section in result['sections']:
        frame=draw_personal_frame(result,{'word_start':word,'text':'My matchday take.'},0,1)
        assert frame.size==(1080,1920)
        word+=len(section['text'].split())


def test_discovery_covers_all_accessible_leagues_and_extended_window(contextual_input):
    fixture,_,_=contextual_input
    domestic=deepcopy(fixture);domestic.update(id=123,league_id=8,league={'name':'Premier League'},starting_at='2026-11-14 23:00:00')
    client=Mock();client.subscribed_leagues.return_value=[{'id':8,'name':'Premier League','country':'England'}]
    client.fixture_window.return_value=[fixture,domestic]
    result=available_matches(client,hours=24,now=NOW)
    assert {m['league_id'] for m in result['matches']}=={8,1082}
    assert result['leagues']==client.subscribed_leagues.return_value
    assert result['coverage']=='all_accessible_competitions'
    assert client.fixture_window.call_args.kwargs['league_id'] is None


def test_domestic_clubs_do_not_both_get_country_advantage(contextual_input):
    fixture,histories,lineups=contextual_input
    fixture['league_id']=8;fixture['league']={'name':'Premier League'}
    for participant in fixture['participants']: participant['country_id']=1
    for rows in histories.values():
        for past in rows: past['league_id']=8
    result=contextual_prediction(fixture,histories,lineups,NOW)
    assert result['league_id']==8
    assert result['forecast']['assumptions']['applied_venue_factors']=={'home':1,'away':1}
    assert 'sampled friendly' not in result['script']


def test_missing_lineups_keep_venue_research_and_final_score(contextual_input):
    from backend.editorial import evidence_packet,grounded_backup
    from backend.personal_video import draw_personal_frame
    fixture,histories,lineups=contextual_input
    lineups['confirmed']=False  # Even supplied expected-player rows must not leak.
    result=contextual_prediction(fixture,histories,lineups,NOW,research={'performed':True,'claims':[]})
    assert result['context']['venue']['name']=='Home Ground'
    assert result['context']['web_research']['performed']
    assert all(not rows for rows in result['featured_players'].values())
    for profile in result['context']['lineup_profiles'].values():
        assert profile['rating_factor']==1 and profile['latest_starters_retained'] is None
    result=grounded_backup(result,evidence_packet(result),[])
    assert 'player 0' not in result['script']
    assert result['sections'][-1]['kind']=='pick'
    assert result['script'].endswith("That's my pick.")
    word=0
    for section in result['sections']:
        assert draw_personal_frame(result,{'word_start':word,'text':'My pick.'},0,1).size==(1080,1920)
        word+=len(section['text'].split())


def test_production_uses_smaller_available_result_sample(contextual_input):
    from backend.editorial import evidence_packet,grounded_backup
    fixture,histories,lineups=contextual_input
    lineups['confirmed']=False
    histories={side:rows[:1] for side,rows in histories.items()}
    result=contextual_prediction(fixture,histories,lineups,NOW)
    assert all(form['sample_size']==1 for form in result['form'].values())
    assert all(len(profile['samples'])==1 for profile in result['context']['lineup_profiles'].values())
    assert grounded_backup(result,evidence_packet(result),[])['sections'][-1]['kind']=='pick'


def test_no_results_never_fabricates_form(contextual_input):
    fixture,histories,lineups=contextual_input
    histories['home']=[]
    with pytest.raises(PredictionError,match='No verified recent results'):
        contextual_prediction(fixture,histories,lineups,NOW)


def ranking_payload(fixture,**updates):
    payload=research_payload()
    row={'team_id':fixture['participants'][0]['id'],'rank':6,'points':1800.0,'ranking_date':'2026-11-01',
         'official':True,'source_url':'https://inside.fifa.com/ranking/BRA',
         'release_source_url':'https://inside.fifa.com/ranking/men'}
    row.update(updates)
    payload['output'][0]['action']['sources'] += [{'url':row['source_url']},{'url':row['release_source_url']}]
    brief=json.loads(payload['output'][1]['content'][0]['text']);brief['fifa_rankings']=[row]
    payload['output'][1]['content'][0]['text']=json.dumps(brief)
    return payload


def test_official_fifa_rankings_bound_to_national_team_date_and_sources(contextual_input):
    fixture,_,_=contextual_input
    fixture['participants'][0].update(type='national',gender='male')
    result=validate_research(ranking_payload(fixture),fixture,NOW)
    assert result['fifa_rankings'][0]['rank']==6
    assert result['fifa_rankings'][0]['ranking_date']=='2026-11-01'


@pytest.mark.parametrize('change',[{'official':False},{'ranking_date':'2026-11-15'},
    {'ranking_date':'2025-01-01'},{'source_url':'https://fifa.com.example.org/ranking'}, {'team_id':9999}])
def test_unverified_fifa_rankings_excluded_without_blocking(contextual_input,change):
    fixture,_,_=contextual_input
    fixture['participants'][0].update(type='national',gender='male')
    assert validate_research(ranking_payload(fixture,**change),fixture,NOW)['fifa_rankings']==[]


def test_clubs_do_not_inherit_national_fifa_rankings(contextual_input):
    fixture,_,_=contextual_input
    assert validate_research(ranking_payload(fixture),fixture,NOW)['fifa_rankings']==[]


def test_fifa_points_adjustment_requires_matching_official_release(contextual_input):
    fixture,histories,lineups=contextual_input
    base=contextual_prediction(fixture,histories,lineups,NOW)
    for participant in fixture['participants']:participant.update(type='national',gender='male')
    ranks=[{'team_id':10,'rank':6,'points':1800,'official':True,'ranking_date':'2026-11-01'},
           {'team_id':20,'rank':149,'points':1000,'official':True,'ranking_date':'2026-11-01'}]
    result=contextual_prediction(fixture,histories,lineups,NOW,research={'fifa_rankings':ranks})
    assert result['forecast']['model_goal_rates']['home']>base['forecast']['model_goal_rates']['home']
    assert result['forecast']['model_goal_rates']['away']<base['forecast']['model_goal_rates']['away']
    ranks[0]['ranking_date']='2026-10-01'
    result=contextual_prediction(fixture,histories,lineups,NOW,research={'fifa_rankings':ranks})
    assert result['forecast']['assumptions']['strength_model']['applied'] is False


def test_research_query_does_not_search_raw_fixture_json(payload):
    from backend.research import ResearchClient
    from datetime import timedelta
    fixture=payload['data'];fixture['starting_at']=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    session=Mock();session.post.return_value.status_code=200
    session.post.return_value.json.return_value=research_payload()
    client=ResearchClient(api_key='synthetic-key',session=session)
    client.brief(fixture)
    body=session.post.call_args.kwargs['json']
    assert len(body['input'])<300
    assert 'fixture_id' not in body['input']
    assert 'untrusted data' in body['instructions']
