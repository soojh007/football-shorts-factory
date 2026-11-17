from copy import deepcopy
from datetime import datetime,timedelta,timezone
from http.server import ThreadingHTTPServer
import json
import threading
from unittest.mock import MagicMock,Mock

import pytest
import requests

from backend.dashboard import JobStore,make_handler
from backend.lineups import LineupsNotReady,add_lineup_sections,confirmed_lineups
from backend.prediction import make_prediction,prediction_content_hash
from backend.workflow import find_matches,prediction_upload_body,run_workflow

NOW=datetime(2026,11,14,9,30,tzinfo=timezone.utc)
CHANNEL='UCw3H9KY5toxOuN7cSDsIKqA'


@pytest.fixture
def ready(payload):
    fixture=deepcopy(payload['data'])
    fixture.update(id=19878000,league_id=1082,state_id=1,state={'id':1},
        starting_at=(NOW+timedelta(minutes=30)).isoformat(),league={'name':'Friendly International'},
        metadata=[{'type_id':572,'type':{'code':'lineup-confirmed'},'values':{'confirmed':True}}])
    fixture['lineups']=[{'team_id':team,'type_id':11,'player_id':team*100+i,
        'player_name':f'Player {team} {i}','jersey_number':i} for team in (10,20) for i in range(1,12)]
    history=[]
    for i in range(5):
        past=deepcopy(payload['data'])
        past.update(id=100+i,league_id=1082,starting_at=f'2026-10-{10+i:02} 12:00:00')
        history.append(past)
    return fixture,{'fixture':fixture,'histories':{'home':history,'away':history},'as_of':NOW.isoformat()}


def test_complete_confirmed_xis(ready):
    lineups=confirmed_lineups(ready[0],NOW)
    assert len(lineups['home']['starters'])==len(lineups['away']['starters'])==11


@pytest.mark.parametrize('flag',[False,None,'true',1])
def test_non_true_confirmation_never_used(ready,flag):
    ready[0]['metadata'][0]['values']['confirmed']=flag
    with pytest.raises(LineupsNotReady):
        confirmed_lineups(ready[0],NOW)


def test_missing_confirmation_never_inferred_from_22_players(ready):
    ready[0]['metadata']=[]
    with pytest.raises(LineupsNotReady):
        confirmed_lineups(ready[0],NOW)


def test_more_than_hour_waits(ready):
    ready[0]['starting_at']=(NOW+timedelta(minutes=61)).isoformat()
    with pytest.raises(LineupsNotReady,match='hour'):
        confirmed_lineups(ready[0],NOW)


def test_incomplete_xi_waits(ready):
    ready[0]['lineups'].pop()
    with pytest.raises(LineupsNotReady):
        confirmed_lineups(ready[0],NOW)


def test_duplicate_player_waits(ready):
    ready[0]['lineups'][-1]['player_id']=ready[0]['lineups'][0]['player_id']
    with pytest.raises(LineupsNotReady):
        confirmed_lineups(ready[0],NOW)


def make_ready_prediction(ready):
    fixture,source=ready
    prediction=make_prediction(fixture,source['histories'],as_of=NOW,league_id=1082)
    return add_lineup_sections(prediction,confirmed_lineups(fixture,NOW))


def test_team_sheet_narration_and_hash(ready):
    prediction=make_ready_prediction(ready)
    assert 75<=prediction['word_count']<=150
    assert 'lineup_home' in [section['kind'] for section in prediction['sections']]
    assert "doesn't know the lineups" not in prediction['script']
    assert 'player strength' in prediction['script']
    other=deepcopy(prediction)
    other['as_of']='another retrieval time'
    other['lineups']['checked_at']='another check time'
    assert prediction_content_hash(prediction)==prediction_content_hash(other)
    other['lineups']['home']['starters'][0]['name']='Different Player'
    assert prediction_content_hash(prediction)!=prediction_content_hash(other)


def test_prediction_upload_metadata_is_private_and_not_epl(ready):
    body=prediction_upload_body(make_ready_prediction(ready))
    assert body['status']['privacyStatus']=='private'
    assert body['status']['containsSyntheticMedia'] is True
    assert 'PremierLeague' not in body['snippet']['description']
    assert 'confirmed' in body['snippet']['description']
    assert 'not calibrated' in body['snippet']['description']


def test_search_resolves_both_names(ready):
    client=Mock()
    client.fixture_window.return_value=[ready[0]]
    assert find_matches('Away FC vs Home FC',client,NOW)[0]['id']==19878000
    assert not find_matches('Unrelated Team',client,NOW)


def setup_workflow(monkeypatch,ready):
    client=MagicMock()
    monkeypatch.setattr('backend.workflow.PrematchClient',lambda:client)
    monkeypatch.setattr('backend.fifa_rankings.fetch_rankings',lambda *args:[])
    monkeypatch.setattr('backend.workflow.lineup_fixture',lambda *args:deepcopy(ready[0]))
    monkeypatch.setattr('backend.workflow.collect',lambda *args,**kwargs:deepcopy(ready[1]))
    clock=Mock()
    clock.now.return_value=NOW
    monkeypatch.setattr('backend.workflow.datetime',clock)
    monkeypatch.setattr('backend.workflow.enrich_history',lambda source,now:source)
    def contextual(fixture,histories,lineups,now,league_id,research=None):
        return add_lineup_sections(make_prediction(fixture,histories,as_of=now,league_id=league_id),lineups)
    monkeypatch.setattr('backend.workflow.contextual_prediction',contextual)
    researcher=MagicMock();researcher.brief.return_value={'performed':True,'claims':[],'sources':[]}
    monkeypatch.setattr('backend.workflow.ResearchClient',lambda:researcher)
    editor=MagicMock();editor.write.side_effect=lambda prediction:prediction
    monkeypatch.setattr('backend.workflow.EditorialClient',lambda:editor)
    monkeypatch.setattr('backend.workflow.collect_player_media',lambda *args:[])
    monkeypatch.setattr('backend.workflow.venue_context',lambda *args:{'name':'Test venue'})
    return client


def test_missing_lineups_continue_with_available_evidence(ready,tmp_path,monkeypatch):
    ready[0]['metadata'][0]['values']['confirmed']=False
    setup_workflow(monkeypatch,ready)
    render=Mock()
    monkeypatch.setattr('backend.workflow.render_prediction',render)
    run_workflow(19878000,out=tmp_path,upload=False)
    render.assert_called_once()


def test_local_workflow_does_not_authenticate_or_upload(ready,tmp_path,monkeypatch):
    setup_workflow(monkeypatch,ready)
    monkeypatch.setattr('backend.workflow.reusable_video',lambda *args:True)
    auth=Mock()
    monkeypatch.setattr('backend.workflow.load_credentials',auth)
    result=run_workflow(19878000,out=tmp_path,upload=False)
    assert result['uploaded'] is False
    auth.assert_not_called()
    assert (tmp_path/'19878000_workflow_result.json').exists()


def test_upload_flow_checks_channel_and_uploads_privately(ready,tmp_path,monkeypatch):
    setup_workflow(monkeypatch,ready)
    monkeypatch.setenv('YOUTUBE_CHANNEL_ID',CHANNEL)
    monkeypatch.setattr('backend.workflow.reusable_video',lambda *args:True)
    (tmp_path/'19878000_prediction.mp4').write_bytes(b'fake-video')
    monkeypatch.setattr('backend.workflow.load_credentials',lambda:Mock())
    monkeypatch.setattr('backend.workflow.youtube_service',lambda *args:MagicMock())
    monkeypatch.setattr('backend.workflow.current_channel',lambda *args:{'id':CHANNEL})
    upload=Mock(return_value=({'url':'https://www.youtube.com/watch?v=abcdefghijk','returned_privacy':'private'},False))
    monkeypatch.setattr('backend.workflow.upload_video',upload)
    result=run_workflow(19878000,out=tmp_path,upload=True)
    assert result['uploaded'] is True
    assert upload.call_args.args[2]['status']['privacyStatus']=='private'
    assert upload.call_args.args[-1].name=='19878000_prediction_youtube_upload.json'


def test_lineup_change_before_upload_blocks(ready,tmp_path,monkeypatch):
    setup_workflow(monkeypatch,ready)
    monkeypatch.setenv('YOUTUBE_CHANNEL_ID',CHANNEL)
    monkeypatch.setattr('backend.workflow.reusable_video',lambda *args:True)
    monkeypatch.setattr('backend.workflow.load_credentials',lambda:Mock())
    monkeypatch.setattr('backend.workflow.youtube_service',lambda *args:MagicMock())
    monkeypatch.setattr('backend.workflow.current_channel',lambda *args:{'id':CHANNEL})
    fixtures=[deepcopy(ready[0]),deepcopy(ready[0])]
    fixtures[-1]['lineups'][0]['player_name']='Changed Player'
    monkeypatch.setattr('backend.workflow.lineup_fixture',Mock(side_effect=fixtures))
    upload=Mock()
    monkeypatch.setattr('backend.workflow.upload_video',upload)
    with pytest.raises(LineupsNotReady,match='changed'):
        run_workflow(19878000,out=tmp_path,upload=True)
    upload.assert_not_called()


def test_dashboard_requires_csrf_for_work(tmp_path):
    store=JobStore(tmp_path)
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(store,'test-csrf-token'))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        page=requests.get(base,timeout=5)
        assert page.status_code==200
        assert 'Create video &amp;' not in page.text
        assert 'Create video & upload privately' in page.text
        response=requests.post(base+'/api/jobs',json={'fixture_id':19878000},timeout=5)
        assert response.status_code==403
        assert not store.jobs
        store.submit=Mock(return_value='job-id')
        response=requests.post(base+'/api/jobs',json={'fixture_id':19878000},headers={'X-CSRF-Token':'test-csrf-token'},timeout=5)
        assert response.status_code==202
        assert store.submit.call_count==1
    finally:
        server.shutdown()
        server.server_close()
        store.executor.shutdown(wait=False,cancel_futures=True)


def test_fixture_lock_blocks_concurrent_runs(tmp_path,monkeypatch):
    (tmp_path/'.19878000_workflow.lock').write_text('existing-process')
    client=Mock()
    monkeypatch.setattr('backend.workflow.PrematchClient',client)
    from backend.prediction import PredictionError
    with pytest.raises(PredictionError,match='already has a workflow'):
        run_workflow(19878000,out=tmp_path,upload=False)
    client.assert_not_called()


def test_wrong_channel_stops_before_generation(ready,tmp_path,monkeypatch):
    setup_workflow(monkeypatch,ready)
    monkeypatch.setenv('YOUTUBE_CHANNEL_ID',CHANNEL)
    monkeypatch.setattr('backend.workflow.load_credentials',lambda:Mock())
    monkeypatch.setattr('backend.workflow.youtube_service',lambda *args:MagicMock())
    monkeypatch.setattr('backend.workflow.current_channel',lambda *args:{'id':'UC'+'x'*22})
    render=Mock()
    monkeypatch.setattr('backend.workflow.render_prediction',render)
    from backend.youtube_auth import YouTubeError
    with pytest.raises(YouTubeError,match='does not match'):
        run_workflow(19878000,out=tmp_path,upload=True)
    render.assert_not_called()
    assert not (tmp_path/'.19878000_workflow.lock').exists()


def test_production_infers_competition_instead_of_friendly(ready,tmp_path,monkeypatch):
    fixture,source=ready
    fixture['league_id']=8; fixture['league']={'name':'Premier League'}
    for rows in source['histories'].values():
        for past in rows: past['league_id']=8
    setup_workflow(monkeypatch,ready)
    monkeypatch.setattr('backend.workflow.reusable_video',lambda *args:True)
    result=run_workflow(fixture['id'],out=tmp_path,upload=False)
    prediction=json.loads((tmp_path/f"{fixture['id']}_prediction.json").read_text())
    assert prediction['league_id']==8 and prediction['competition']=='Premier League'
    body=prediction_upload_body(prediction)
    assert 'Premier League prediction' in body['snippet']['description']
    assert 'international friendly' not in body['snippet']['description'].lower()
    assert body['status']['privacyStatus']=='private'
    assert result['uploaded'] is False


def test_search_returns_multiple_accessible_competitions(ready):
    fixture=ready[0]
    domestic=deepcopy(fixture); domestic.update(id=123,league_id=8,league={'name':'Premier League'})
    client=Mock();client.fixture_window.return_value=[fixture,domestic]
    result=find_matches('Home FC',client,NOW)
    assert {m['league_id'] for m in result}=={8,1082}
    assert client.fixture_window.call_args.kwargs['league_id'] is None
    assert len(confirmed_lineups(domestic,NOW)['home']['starters'])==11


def test_missing_lineup_description_does_not_claim_confirmation():
    from backend.workflow import prediction_upload_body
    prediction={'teams':{'home':{'name':'Team A'},'away':{'name':'Team B'}},
        'forecast':{'score_pick':{'home':2,'away':1}},'kickoff':'2026-11-17T12:00:00Z',
        'league_id':1082,'script':'My pick.','lineups':{'confirmed':False}}
    body=prediction_upload_body(prediction)
    assert 'Both official starting elevens were confirmed' not in body['snippet']['description']
    assert 'unavailable' in body['snippet']['description']
    assert body['status']['privacyStatus']=='private'


def test_sharealike_images_require_video_licence_and_attribution():
    from backend.workflow import prediction_upload_body
    p={'teams':{'home':{'name':'Home'},'away':{'name':'Away'}},'forecast':{'score_pick':{'home':1,'away':2}},
        'league_id':1082,'kickoff':'2026-11-17','script':'My prediction.',
        'media_assets':[{'name':'A Player','title':'Action photo','artist':'Photographer','license':'CC BY-SA 4.0',
            'license_url':'https://creativecommons.org/licenses/by-sa/4.0/','source_url':'https://commons.wikimedia.org/wiki/File:Action.jpg'}]}
    body=prediction_upload_body(p)
    assert 'This video adaptation is licensed under CC BY-SA 4.0' in body['snippet']['description']
    assert 'Photographer' in body['snippet']['description'] and 'Changes:' in body['snippet']['description']
    assert body['status']['privacyStatus']=='private'
