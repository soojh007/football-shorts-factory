import json
from unittest.mock import MagicMock

import pytest

from backend.main import main


def test_cli_writes_json(monkeypatch, tmp_path, payload, capsys):
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "mock-credential")
    session = MagicMock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = payload
    monkeypatch.setattr("backend.sportmonks.requests.Session", lambda: session)
    assert main(["--fixture", "19427552", "--output-dir", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "19427552_raw.json").read_text()) == payload
    result = json.loads((tmp_path / "19427552_normalized.json").read_text())
    assert result["final_score"] == {"home": 2, "away": 1}
    assert "Home FC 2–1 Away FC (FT)" in capsys.readouterr().out


def test_rejected_fixture_writes_nothing(monkeypatch, tmp_path, payload, capsys):
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "mock-credential")
    payload["data"]["state_id"] = 1
    session = MagicMock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = payload
    monkeypatch.setattr("backend.sportmonks.requests.Session", lambda: session)
    assert main(["--fixture", "19427552", "--output-dir", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []
    assert "not completed" in capsys.readouterr().err


@pytest.mark.parametrize("fixture_id", ["0", "-1", "abc"])
def test_cli_invalid_id(fixture_id):
    with pytest.raises(SystemExit) as exc:
        main(["--fixture", fixture_id])
    assert exc.value.code == 2
