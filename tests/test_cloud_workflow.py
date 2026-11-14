import json
from pathlib import Path
from unittest.mock import MagicMock,Mock

import pytest

from backend.cloud_receipts import CloudStateError,cipher,pack_receipts,unpack_receipts,restore_latest
from backend import cloud_workflow
from backend.lineups import LineupsNotReady

OAUTH=json.dumps({'refresh_token':'synthetic-refresh','client_id':'synthetic-client','client_secret':'synthetic-secret'})


def test_receipts_are_encrypted_not_public(tmp_path):
    source=tmp_path/'source'
    source.mkdir()
    receipt={'state':'uploaded','video_id':'abcdefghijk','body':{'description':'private script'}}
    (source/'123_prediction_youtube_upload.json').write_text(json.dumps(receipt))
    (source/'youtube_token.json').write_text(OAUTH)
    (source/'123_prediction.mp4').write_bytes(b'private-media')
    encrypted=pack_receipts(source,OAUTH)
    assert b'private script' not in encrypted and b'abcdefghijk' not in encrypted
    target=tmp_path/'target'
    assert unpack_receipts(encrypted,target,OAUTH)==1
    assert json.loads((target/'123_prediction_youtube_upload.json').read_text())==receipt
    assert list(path.name for path in target.iterdir())==['123_prediction_youtube_upload.json']


def test_oauth_rotation_fails_closed(tmp_path):
    encrypted=pack_receipts(tmp_path,OAUTH)
    with pytest.raises(CloudStateError,match='could not be verified'):
        unpack_receipts(encrypted,tmp_path,json.dumps({'refresh_token':'different-token'}))


def test_unsafe_state_paths_rejected(tmp_path):
    encrypted=cipher(OAUTH).encrypt(json.dumps({'version':1,'receipts':{'../secret.json':{}}}).encode())
    with pytest.raises(CloudStateError):
        unpack_receipts(encrypted,tmp_path,OAUTH)
    assert not (tmp_path.parent/'secret.json').exists()


def test_state_access_denied_stops_upload(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repository')
    monkeypatch.setenv('GITHUB_TOKEN','synthetic-github-token')
    session=Mock()
    session.get.return_value.status_code=403
    with pytest.raises(CloudStateError,match='Cannot read'):
        restore_latest(tmp_path,OAUTH,session=session)


def test_first_run_without_artifacts(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repository')
    monkeypatch.setenv('GITHUB_TOKEN','synthetic-github-token')
    session=Mock()
    session.get.return_value.status_code=200
    session.get.return_value.json.return_value={'artifacts':[]}
    assert restore_latest(tmp_path,OAUTH,session=session)==0


def test_prepare_requires_all_secrets(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','')
    with pytest.raises(CloudStateError,match='missing'):
        cloud_workflow.prepare()


def cloud_run_mocks(monkeypatch):
    monkeypatch.setenv('YOUTUBE_CHANNEL_ID','UCw3H9KY5toxOuN7cSDsIKqA')
    monkeypatch.setenv('MATCH_INPUT','Japan vs Brazil')
    monkeypatch.setattr('backend.video.require_tools',lambda:None)
    monkeypatch.setattr(cloud_workflow,'load_credentials',lambda:Mock())
    monkeypatch.setattr(cloud_workflow,'youtube_service',lambda *args:MagicMock())
    monkeypatch.setattr(cloud_workflow,'current_channel',lambda *args:{'id':'UCw3H9KY5toxOuN7cSDsIKqA'})
    monkeypatch.setattr(cloud_workflow,'PrematchClient',lambda:MagicMock())
    monkeypatch.setattr(cloud_workflow,'find_matches',lambda *args:[{'id':19878000}])
    monkeypatch.setattr(cloud_workflow,'lineup_fixture',lambda *args:{'id':19878000})


def test_validation_only_never_generates_or_uploads(monkeypatch):
    cloud_run_mocks(monkeypatch)
    monkeypatch.setenv('CLOUD_VALIDATE_ONLY','true')
    monkeypatch.setattr(cloud_workflow,'confirmed_lineups',lambda *args:{'confirmed':True})
    run=Mock()
    monkeypatch.setattr(cloud_workflow,'run_workflow',run)
    cloud_workflow.run()
    run.assert_not_called()


def test_waiting_never_generates_or_uploads(monkeypatch):
    cloud_run_mocks(monkeypatch)
    monkeypatch.setenv('CLOUD_VALIDATE_ONLY','false')
    monkeypatch.setattr(cloud_workflow,'confirmed_lineups',Mock(side_effect=LineupsNotReady('Not confirmed.')))
    run=Mock()
    monkeypatch.setattr(cloud_workflow,'run_workflow',run)
    cloud_workflow.run()
    run.assert_not_called()


def test_restored_receipt_prevents_paid_regeneration(tmp_path,monkeypatch):
    cloud_run_mocks(monkeypatch)
    monkeypatch.setattr(cloud_workflow,'ROOT',tmp_path)
    monkeypatch.setenv('CLOUD_VALIDATE_ONLY','false')
    monkeypatch.setattr(cloud_workflow,'confirmed_lineups',lambda *args:{'confirmed':True})
    out=tmp_path/'generated'
    out.mkdir()
    (out/'19878000_prediction_youtube_upload.json').write_text(json.dumps({'state':'uploaded',
        'channel_id':'UCw3H9KY5toxOuN7cSDsIKqA','video_id':'abcdefghijk'}))
    run=Mock()
    monkeypatch.setattr(cloud_workflow,'run_workflow',run)
    cloud_workflow.run()
    run.assert_not_called()


def retry_clock(monkeypatch):
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    state={'elapsed':0.0}
    base=datetime(2026,11,14,12,tzinfo=timezone.utc)
    clock=Mock();clock.now.side_effect=lambda *args:base+timedelta(seconds=state['elapsed'])
    monkeypatch.setattr(cloud_workflow,'datetime',clock)
    monkeypatch.setattr(cloud_workflow,'time',SimpleNamespace(monotonic=lambda:state['elapsed'],
        sleep=lambda seconds:state.update(elapsed=state['elapsed']+seconds)))
    monkeypatch.setattr(cloud_workflow,'PrematchClient',lambda:MagicMock())
    return state,base


def test_auto_wait_continues_once_lineups_ready(monkeypatch):
    state,base=retry_clock(monkeypatch)
    fixture={'id':123,'starting_at':'2026-11-14 13:00:00'}
    checks=Mock(side_effect=[LineupsNotReady('Not confirmed'),{'confirmed':True}])
    monkeypatch.setattr(cloud_workflow,'confirmed_lineups',checks)
    fetch=Mock(return_value=fixture);monkeypatch.setattr(cloud_workflow,'lineup_fixture',fetch)
    assert cloud_workflow.wait_for_lineups(123,fixture,auto_retry=True) is True
    assert state['elapsed']==180
    fetch.assert_called_once()
    assert checks.call_count==2


def test_auto_wait_stops_at_kickoff(monkeypatch):
    state,_=retry_clock(monkeypatch)
    fixture={'id':123,'starting_at':'2026-11-14 12:02:00'}
    monkeypatch.setattr(cloud_workflow,'confirmed_lineups',Mock(side_effect=LineupsNotReady('Not confirmed')))
    fetch=Mock();monkeypatch.setattr(cloud_workflow,'lineup_fixture',fetch)
    assert cloud_workflow.wait_for_lineups(123,fixture,auto_retry=True) is False
    assert state['elapsed']==120
    fetch.assert_not_called()


def test_auto_wait_rejects_matches_more_than_two_hours_away(monkeypatch):
    state,_=retry_clock(monkeypatch)
    monkeypatch.setattr(cloud_workflow,'confirmed_lineups',Mock(side_effect=LineupsNotReady('Too early')))
    assert cloud_workflow.wait_for_lineups(123,{'starting_at':'2026-11-14 15:00:00'},auto_retry=True) is False
    assert state['elapsed']==0


def test_auto_wait_budget_survives_rescheduling(monkeypatch):
    state,_=retry_clock(monkeypatch)
    fixture={'id':123,'starting_at':'2026-11-14 14:00:00'}
    monkeypatch.setattr(cloud_workflow,'confirmed_lineups',Mock(side_effect=LineupsNotReady('Waiting')))
    monkeypatch.setattr(cloud_workflow,'lineup_fixture',Mock(return_value={'id':123,'starting_at':'2026-11-14 18:00:00'}))
    assert cloud_workflow.wait_for_lineups(123,fixture,auto_retry=True) is False
    assert state['elapsed']==7200


def test_validation_only_disables_auto_wait(monkeypatch):
    cloud_run_mocks(monkeypatch)
    monkeypatch.setenv('CLOUD_VALIDATE_ONLY','true');monkeypatch.setenv('CLOUD_AUTO_RETRY','true')
    wait=Mock(return_value=False);monkeypatch.setattr(cloud_workflow,'wait_for_lineups',wait)
    cloud_workflow.run()
    assert wait.call_args.kwargs['auto_retry'] is False


def test_auto_wait_does_not_retry_api_failures(monkeypatch):
    from backend.sportmonks import SportmonksError
    retry_clock(monkeypatch)
    monkeypatch.setattr(cloud_workflow,'confirmed_lineups',Mock(side_effect=LineupsNotReady('Waiting')))
    fetch=Mock(side_effect=SportmonksError('Rate limited'));monkeypatch.setattr(cloud_workflow,'lineup_fixture',fetch)
    with pytest.raises(SportmonksError):
        cloud_workflow.wait_for_lineups(123,{'starting_at':'2026-11-14 13:00:00'},auto_retry=True)
    fetch.assert_called_once()
