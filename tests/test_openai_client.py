import json
from unittest.mock import Mock

import pytest
import requests

from backend.analysis import AnalysisError, build_facts, checked_fixture
from backend.normalize import normalize_fixture
from backend.openai_client import OpenAIClient


@pytest.fixture
def session():
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {
        "status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"hook": "result", "fact_ids": ["possession", "total_shots"]})}
        ]}],
    }
    return session


@pytest.fixture
def facts(payload):
    return build_facts(checked_fixture(normalize_fixture(payload)))


def test_structured_request(session, facts):
    client = OpenAIClient(api_key="synthetic-test-key", model="mock-model", session=session)
    plan = client.select_facts(facts)
    assert plan.fact_ids == ["possession", "total_shots"]
    args, kwargs = session.post.call_args
    assert args == ("https://api.openai.com/v1/responses",)
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-test-key"
    body = kwargs["json"]
    assert body["model"] == "mock-model"
    assert body["store"] is False
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    selection = body["text"]["format"]["schema"]["properties"]["fact_ids"]
    assert selection["minItems"] == selection["maxItems"] == 2
    assert set(selection["items"]["enum"]) == {"possession", "total_shots"}
    assert kwargs["timeout"] == 60


@pytest.mark.parametrize("status", [401, 403, 429, 400, 500])
def test_api_failure_does_not_leak_key(session, facts, status):
    session.post.return_value.status_code = status
    with pytest.raises(AnalysisError) as exc:
        OpenAIClient(api_key="synthetic-test-key", session=session).select_facts(facts)
    assert "synthetic-test-key" not in str(exc.value)


@pytest.mark.parametrize("error", [requests.Timeout("synthetic-test-key"), requests.ConnectionError("synthetic-test-key")])
def test_network_failure_does_not_leak_key(session, facts, error):
    session.post.side_effect = error
    with pytest.raises(AnalysisError) as exc:
        OpenAIClient(api_key="synthetic-test-key", session=session).select_facts(facts)
    assert "synthetic-test-key" not in str(exc.value)


@pytest.mark.parametrize("response_payload", [None, [], {}, {"status": "incomplete"},
    {"status": "completed", "output": []},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "not-json"}]}]},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"hook":"result","fact_ids":[],"extra":"untrusted prose"}'}]}]},
])
def test_reject_invalid_responses(session, facts, response_payload):
    session.post.return_value.json.return_value = response_payload
    with pytest.raises(AnalysisError):
        OpenAIClient(api_key="synthetic-test-key", session=session).select_facts(facts)


def test_invalid_json(session, facts):
    session.post.return_value.json.side_effect = ValueError("synthetic-test-key")
    with pytest.raises(AnalysisError):
        OpenAIClient(api_key="synthetic-test-key", session=session).select_facts(facts)


def test_missing_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(AnalysisError, match="OPENAI_API_KEY"):
        OpenAIClient()
