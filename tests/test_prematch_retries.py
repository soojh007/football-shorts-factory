from unittest.mock import Mock

import pytest
import requests

from backend.prematch import PrematchClient,PrematchTemporaryError,PrematchDataUnavailableError
from backend.sportmonks import SportmonksError


def response(status=200,headers=None):
    r=Mock(status_code=status,headers=headers or {})
    r.json.return_value={'data':{'id':123}}
    return r


def test_transient_read_failure_retries_then_recovers(monkeypatch):
    sleep=Mock();monkeypatch.setattr('backend.prematch.time.sleep',sleep)
    session=Mock();session.get.side_effect=[requests.ConnectionError('synthetic-key URL'),response()]
    client=PrematchClient(token='synthetic-key',session=session)
    assert client.upcoming_fixture(123)['data']['id']==123
    assert session.get.call_count==2
    sleep.assert_called_once_with(1)


@pytest.mark.parametrize('failure',[requests.Timeout('synthetic-key'),requests.ConnectionError('synthetic-key'),
                                     requests.exceptions.ChunkedEncodingError('synthetic-key')])
def test_transport_retries_are_bounded_and_credential_safe(monkeypatch,failure):
    sleep=Mock();monkeypatch.setattr('backend.prematch.time.sleep',sleep)
    session=Mock();session.get.side_effect=failure
    with pytest.raises(PrematchTemporaryError) as error:
        PrematchClient(token='synthetic-key',session=session).upcoming_fixture(123)
    assert session.get.call_count==3 and sleep.call_count==2
    assert 'synthetic-key' not in str(error.value)


@pytest.mark.parametrize('status',[500,502,503,504])
def test_server_error_recovers_on_read_retry(monkeypatch,status):
    monkeypatch.setattr('backend.prematch.time.sleep',Mock())
    session=Mock();session.get.side_effect=[response(status),response()]
    assert PrematchClient(token='synthetic-key',session=session).upcoming_fixture(123)['data']['id']==123
    assert session.get.call_count==2


def test_long_rate_limit_is_not_ignored_or_waited_out(monkeypatch):
    sleep=Mock();monkeypatch.setattr('backend.prematch.time.sleep',sleep)
    session=Mock();session.get.return_value=response(429,{'Retry-After':'90'})
    with pytest.raises(PrematchTemporaryError) as error:
        PrematchClient(token='synthetic-key',session=session).upcoming_fixture(123)
    assert error.value.code=='rate_limited'
    assert session.get.call_count==1
    sleep.assert_not_called()


def test_short_retry_after_is_honoured(monkeypatch):
    sleep=Mock();monkeypatch.setattr('backend.prematch.time.sleep',sleep)
    session=Mock();session.get.side_effect=[response(429,{'Retry-After':'2'}),response()]
    assert PrematchClient(token='synthetic-key',session=session).upcoming_fixture(123)['data']['id']==123
    sleep.assert_called_once_with(2)


@pytest.mark.parametrize('status',[401,403,404])
def test_auth_and_missing_primary_fixture_do_not_retry_or_fabricate(monkeypatch,status):
    sleep=Mock();monkeypatch.setattr('backend.prematch.time.sleep',sleep)
    session=Mock();session.get.return_value=response(status)
    with pytest.raises(SportmonksError):PrematchClient(token='synthetic-key',session=session).upcoming_fixture(123)
    assert session.get.call_count==1
    sleep.assert_not_called()
