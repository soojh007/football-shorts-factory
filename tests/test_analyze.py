import json
from unittest.mock import MagicMock

import pytest

from backend.analyze import main
from backend.normalize import normalize_fixture


@pytest.fixture
def input_path(tmp_path, payload):
    path = tmp_path / "normalized.json"
    path.write_text(json.dumps(normalize_fixture(payload)), encoding="utf-8")
    return path


def test_preview_files(input_path, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.openai_client.requests.Session", lambda: pytest.fail("Preview must not call OpenAI"))
    output = tmp_path / "output"
    assert main(["--input", str(input_path), "--output-dir", str(output), "--offline-preview"]) == 0
    data = json.loads((output / "19427552_preview.json").read_text())
    assert (output / "19427552_preview_script.txt").read_text().strip() == data["script"]
    assert data["mode"] == "offline_preview"
    assert not (output / "19427552_analysis.json").exists()


def test_missing_key_writes_nothing(input_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    output = tmp_path / "output"
    assert main(["--input", str(input_path), "--output-dir", str(output)]) == 1
    assert not output.exists()
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_mocked_ai_files(input_path, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    session = MagicMock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"hook": "numbers", "fact_ids": ["total_shots", "possession"]})}]}]}
    monkeypatch.setattr("backend.openai_client.requests.Session", lambda: session)
    output = tmp_path / "output"
    assert main(["--input", str(input_path), "--output-dir", str(output)]) == 0
    data = json.loads((output / "19427552_analysis.json").read_text())
    assert data["mode"] == "ai"
    assert (output / "19427552_analysis_script.txt").exists()


def test_invalid_input_writes_nothing(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[]")
    output = tmp_path / "output"
    assert main(["--input", str(path), "--output-dir", str(output), "--offline-preview"]) == 1
    assert not output.exists()


def test_missing_input(tmp_path):
    assert main(["--input", str(tmp_path / "missing.json"), "--offline-preview"]) == 1
