from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from backend.editorial import EditorialClient,EditorialError,evidence_packet,validate_draft


@pytest.fixture
def editorial_input():
    p={'fixture_id':123,'competition':'La Liga 2','teams':{'home':{'name':'Tenerife'},'away':{'name':'Ceuta'}},
       'forecast':{'score_pick':{'home':2,'away':1}},'form':{},'lineups':{'confirmed':True},'context':{'lineup_profiles':{},'venue':{},'web_research':{'claims':[]}}}
    for side,name,pid in [('home','Enric Gallego',382072),('away','Jordi Escobar',20335304)]:
        p['form'][side]={'sample_size':5,'wins':3,'draws':1,'losses':1,'goals_for':8,'goals_against':4}
        p['lineups'][side]={'starters':[{'name':name,'player_id':pid}]}
        p['context']['lineup_profiles'][side]={'latest_starters_retained':8,'player_ratings':{str(pid):7}}
    return p


@pytest.fixture
def draft():
    return {'pick_side':'home','featured_player_ids':[382072,20335304],'sections':[
        {'kind':'hook','text':"I'm backing Tenerife in this one. For me, there is enough in their recent games to make a narrow win the call I like.",'evidence_ids':['home_form']},
        {'kind':'players','text':"Enric Gallego starts for Tenerife, and Jordi Escobar is in Ceuta's eleven. Those are the names that catch my eye when I look at this matchup.",'evidence_ids':['player_382072','player_20335304']},
        {'kind':'players','text':"Tenerife have scored 8 goals across their last 5 league matches. That gives me a concrete reason to back them here. I can see this being close right through to the finish. That is what pushes me towards them in this particular matchup.",'evidence_ids':['home_form']} ]}


def response(value):
    r=Mock(status_code=200);r.json.return_value={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]}
    return r


def test_personal_script_names_confirmed_players_and_fixed_score(editorial_input,draft):
    result=validate_draft(draft,editorial_input,evidence_packet(editorial_input))
    assert 'Enric Gallego' in result['script'] and 'Jordi Escobar' in result['script']
    assert result['script'].endswith("I'm going Tenerife 2, Ceuta 1. That's my pick.")
    assert result['forecast']==editorial_input['forecast']
    assert 75<=result['word_count']<=140
    assert 'caveat' not in [s['kind'] for s in result['sections']]


@pytest.mark.parametrize('change',['unknown_player','missing_opponent','missing_name','unknown_evidence','boilerplate','score','unsupported_number'])
def test_editorial_guards(editorial_input,draft,change):
    if change=='unknown_player': draft['featured_player_ids'][0]=999
    if change=='missing_opponent': draft['featured_player_ids']=[382072]
    if change=='missing_name': draft['sections'][1]['text']='The starting teams interest me.'
    if change=='unknown_evidence': draft['sections'][0]['evidence_ids']=['invented']
    if change=='boilerplate': draft['sections'][0]['text']="I'm checking the players and the ground."
    if change=='score': draft['sections'][0]['text']="I'm predicting 9-0."
    if change=='unsupported_number': draft['sections'][0]['text']="I saw 999 goals."
    with pytest.raises(EditorialError): validate_draft(draft,editorial_input,evidence_packet(editorial_input))


def test_client_runs_independent_grounding_review(editorial_input,draft):
    session=Mock();session.post.side_effect=[response(draft),response({'approved':True,'issues':[]})]
    result=EditorialClient(api_key='synthetic-key',session=session).write(editorial_input)
    assert result['editorial']['grounding_review_passed'] is True
    assert session.post.call_count==2
    assert session.post.call_args.kwargs['json']['text']['format']['name']=='editorial_grounding_review'
    assert session.post.call_args.kwargs['json']['store'] is False


def test_grounding_failure_gets_one_revision_then_checked_backup(editorial_input,draft):
    session=Mock();session.post.side_effect=[response(draft),response({'approved':False,'issues':['Unsupported player ability.']}),response(draft),response({'approved':False,'issues':['Unsupported claim.']})]
    result=EditorialClient(api_key='synthetic-key',session=session).write(editorial_input)
    assert result['editorial']['mode']=='grounded_backup'
    assert result['editorial']['programmatic_facts_checked'] is True
    assert result['editorial']['grounding_review_passed'] is False
    assert result['editorial']['attempt_diagnostics']==[{'attempt':1,'code':'grounding_rejected'},{'attempt':2,'code':'grounding_rejected'}]
    assert 'Unsupported player ability' not in result['script']
    assert 'Enric Gallego' in result['script'] and 'Jordi Escobar' in result['script']
    assert result['forecast']==editorial_input['forecast']
    assert session.post.call_count==4


def test_editorial_api_failure_is_safe(editorial_input):
    session=Mock();session.post.return_value.status_code=401
    with pytest.raises(EditorialError,match='HTTP 401'): EditorialClient(api_key='synthetic-key',session=session).write(editorial_input)


def test_packet_excludes_unconfirmed_reports(editorial_input):
    editorial_input['context']['web_research']['claims']=[{'status':'reported','summary':'Unverified injury'}]
    assert not any(k.startswith('news_') for k in evidence_packet(editorial_input)['evidence'])


def test_curly_apostrophe_is_personal_voice(editorial_input,draft):
    draft['sections'][0]['text']=draft['sections'][0]['text'].replace("I'm","I’m")
    assert validate_draft(draft,editorial_input,evidence_packet(editorial_input))['word_count']>=75


def test_hook_must_lead_with_personal_pick(editorial_input,draft):
    draft['sections'][0]['text']='Something has got to give in this matchup tonight.'
    with pytest.raises(EditorialError,match='first-person pick'): validate_draft(draft,editorial_input,evidence_packet(editorial_input))


def test_editorial_pick_side_matches_score(editorial_input,draft):
    draft['pick_side']='away'
    with pytest.raises(EditorialError,match='pick side'): validate_draft(draft,editorial_input,evidence_packet(editorial_input))

def test_goals_do_not_establish_chance_creation(editorial_input,draft):
    draft['sections'][0]['text']="I'm backing Tenerife because Ceuta struggled to create chances."
    with pytest.raises(EditorialError,match='boilerplate'): validate_draft(draft,editorial_input,evidence_packet(editorial_input))


@pytest.mark.parametrize('model',['gpt-5.2','gpt-4.1'])
def test_editorial_model_request_compatibility(editorial_input,draft,model):
    session=Mock();session.post.side_effect=[response(draft),response({'approved':True,'issues':[]})]
    EditorialClient(api_key='synthetic-key',session=session,model=model).write(editorial_input)
    for call in session.post.call_args_list:
        body=call.kwargs['json']
        assert body['model']==model
        if model=='gpt-5.2': assert body['reasoning']=={'effort':'none'}
        else: assert 'reasoning' not in body


def test_malformed_ai_drafts_cannot_fail_the_whole_video(editorial_input):
    session=Mock();session.post.side_effect=[response({'bad':'private rejected draft'}),response({'bad':'private rejected draft'})]
    result=EditorialClient(api_key='synthetic-key',session=session).write(editorial_input)
    assert result['editorial']['mode']=='grounded_backup'
    assert 'private rejected draft' not in result['script']
    assert 95<=result['word_count']<=150
    assert all(x['code']=='schema' for x in result['editorial']['attempt_diagnostics'])


def test_backup_never_uses_unconfirmed_starters(editorial_input):
    from backend.editorial import grounded_backup
    editorial_input['lineups']['confirmed']=False
    result=grounded_backup(editorial_input,evidence_packet(editorial_input),[])
    assert result['editorial']['featured_player_ids']==[]
    assert all(not players for players in result['featured_players'].values())
    assert 'starting eleven' not in result['script']


def test_public_diagnostics_do_not_echo_model_prose_or_secrets():
    from backend.editorial import diagnostic_code
    assert diagnostic_code('Evidence review: SECRET_KEY plus private script')=='grounding_rejected'
    assert diagnostic_code('untrusted arbitrary private prose')=='draft_validation'


def test_review_service_auth_failure_is_not_hidden_by_backup(editorial_input,draft):
    session=Mock();bad=Mock(status_code=401)
    session.post.side_effect=[response(draft),bad]
    with pytest.raises(EditorialError,match='HTTP 401'):
        EditorialClient(api_key='synthetic-key',session=session).write(editorial_input)
    assert session.post.call_count==2


def test_latest_defeat_cannot_be_hidden_behind_aggregate(editorial_input,draft):
    editorial_input['form']['home']['matches']=[{'opponent':'Japan','result':'L','goals_for':2,'goals_against':3,'kickoff':'2026-11-14T10:15:00Z'}]
    packet=evidence_packet(editorial_input)
    assert packet['evidence']['home_latest']['result']=='L'
    with pytest.raises(EditorialError,match='latest completed result'):
        validate_draft(draft,editorial_input,packet)
    from backend.editorial import grounded_backup
    result=grounded_backup(editorial_input,packet,[])
    assert 'lost to Japan' in result['script']
    assert result['sections'][-1]['kind']=='pick'


def test_latest_cross_competition_result_keeps_scope(editorial_input):
    editorial_input['context']['latest_matches']={'home':{'opponent':'Japan','result':'L','goals_for':2,'goals_against':3,'competition':'World Cup'}}
    packet=evidence_packet(editorial_input)
    assert packet['evidence']['home_latest']['competition']=='World Cup'
    assert packet['evidence']['home_form']['sample_size']==5


def test_latest_opponent_reference_must_state_the_result(editorial_input,draft):
    editorial_input['form']['home']['matches']=[{'opponent':'Japan','result':'L','goals_for':2,'goals_against':3}]
    draft['sections'][-1]['text']+=' Japan were the opposition in their last league game.'
    draft['sections'][-1]['evidence_ids'].append('home_latest')
    with pytest.raises(EditorialError,match='latest completed result'):
        validate_draft(draft,editorial_input,evidence_packet(editorial_input))
