from unittest.mock import Mock

import pytest
import requests

from backend.sportmonks import SportmonksClient, SportmonksError


@pytest.fixture
def session(payload):
    session = Mock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = payload
    return session


def test_request(session, payload):
    client = SportmonksClient(token="mock-credential", session=session)
    assert client.get_fixture(19427552) == payload
    args, kwargs = session.get.call_args
    assert args[0].endswith("/19427552")
    assert kwargs["params"]["include"] == client.INCLUDES
    assert kwargs["headers"]["Authorization"] == "mock-credential"
    assert "api_token" not in kwargs["params"]
    assert kwargs["timeout"] == 30


@pytest.mark.parametrize("fixture_id", [0, -1, "abc", "19427552", True, None])
def test_invalid_id(session, fixture_id):
    with pytest.raises(SportmonksError, match="positive integer"):
        SportmonksClient(token="mock-credential", session=session).get_fixture(fixture_id)
    session.get.assert_not_called()


@pytest.mark.parametrize("status,message", [(401, "authentication"), (403, "authentication"),
    (404, "not found"), (429, "rate limit"), (500, "HTTP 500"), (422, "HTTP 422")])
def test_http_errors(session, status, message):
    session.get.return_value.status_code = status
    with pytest.raises(SportmonksError, match=message) as exc:
        SportmonksClient(token="mock-credential", session=session).get_fixture(19427552)
    assert "mock-credential" not in str(exc.value)


@pytest.mark.parametrize("error", [requests.Timeout("mock-credential"), requests.ConnectionError("mock-credential")])
def test_network_errors(session, error):
    session.get.side_effect = error
    with pytest.raises(SportmonksError) as exc:
        SportmonksClient(token="mock-credential", session=session).get_fixture(19427552)
    assert "mock-credential" not in str(exc.value)


@pytest.mark.parametrize("data", [{}, {"data": None}, {"data": []}, {"data": {"id": 1}}, []])
def test_missing_data(session, data):
    session.get.return_value.json.return_value = data
    with pytest.raises(SportmonksError):
        SportmonksClient(token="mock-credential", session=session).get_fixture(19427552)


def test_invalid_json(session):
    session.get.return_value.json.side_effect = ValueError("mock-credential")
    with pytest.raises(SportmonksError, match="invalid JSON"):
        SportmonksClient(token="mock-credential", session=session).get_fixture(19427552)


def test_missing_token(monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    with pytest.raises(SportmonksError, match="Set SPORTMONKS_API_TOKEN"):
        SportmonksClient()


def test_xg_opt_in(session):
    SportmonksClient(token="mock-credential", session=session, include_xg=True).get_fixture(19427552)
    assert "xGFixture.type" in session.get.call_args.kwargs["params"]["include"]


def test_echo_redaction(session, payload):
    payload["data"]["participants"][0]["name"] = 'FC mock-credential'
    result = SportmonksClient(token="mock-credential", session=session).get_fixture(19427552)
    assert "mock-credential" not in str(result)
