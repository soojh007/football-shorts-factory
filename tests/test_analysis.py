import copy
from unittest.mock import Mock

import pytest

from backend.analysis import AnalysisError, EditorialPlan, build_facts, checked_fixture, generate_analysis
from backend.normalize import normalize_fixture


@pytest.fixture
def normalized(payload):
    return normalize_fixture(payload)


def test_preview_is_grounded(normalized):
    result = generate_analysis(normalized, offline_preview=True)
    assert result["fixture_id"] == 19427552
    assert result["mode"] == "offline_preview"
    assert result["model"] is None
    assert 75 <= result["word_count"] <= 150
    assert 30 <= result["estimated_duration_seconds"] <= 60
    assert result["requires_editorial_review"]
    assert len(result["source_sha256"]) == 64
    for point in result["key_points"]:
        assert point["sentence"] in result["script"]
        for evidence in point["evidence"]:
            value = normalized
            for part in evidence["path"].split("."):
                value = value[part]
            assert value == evidence["value"]


def test_missing_statistics_not_invented(normalized):
    for pair in normalized["statistics"].values():
        pair.update(home=None, away=None)
    result = generate_analysis(normalized, offline_preview=True)
    assert [point["id"] for point in result["key_points"]] == ["score"]
    assert 75 <= result["word_count"] <= 150
    assert "possession" not in result["script"]
    assert any("expected_goals" in note for note in result["limitations"])


def test_partial_statistic(normalized):
    result = generate_analysis(normalized, offline_preview=True)
    point = next(point for point in result["key_points"] if point["id"] == "total_shots")
    assert "Home FC recorded 12 total shots" in point["sentence"]
    assert "Away FC" not in point["sentence"]
    assert "higher" not in point["sentence"]


def test_model_order_is_used(normalized):
    client = Mock(model="mock-model")
    client.select_facts.return_value = EditorialPlan(hook="numbers", fact_ids=["total_shots", "possession"])
    result = generate_analysis(normalized, client)
    assert result["mode"] == "ai"
    assert result["model"] == "mock-model"
    assert [point["id"] for point in result["key_points"]] == ["score", "total_shots", "possession"]
    assert result["script"].startswith("What do")


@pytest.mark.parametrize("ids", [["invented", "possession"], ["possession", "possession"],
                                     ["score", "possession"], [], ["possession"]])
def test_invalid_ai_selection(normalized, ids):
    client = Mock(model="mock-model")
    client.select_facts.return_value = EditorialPlan(hook="result", fact_ids=ids)
    with pytest.raises(AnalysisError, match="invalid"):
        generate_analysis(normalized, client)


@pytest.mark.parametrize("field,value", [("match_status", "LIVE"), ("league_id", 564),
                                         ("fixture_id", 0), ("schema_version", 2)])
def test_reject_invalid_source(normalized, field, value):
    normalized[field] = value
    with pytest.raises(AnalysisError):
        generate_analysis(normalized, offline_preview=True)


def test_reject_duplicate_teams(normalized):
    normalized["away_team"]["id"] = normalized["home_team"]["id"]
    with pytest.raises(AnalysisError):
        generate_analysis(normalized, offline_preview=True)


@pytest.mark.parametrize("metric,value", [("possession", 101), ("total_shots", 1.5), ("expected_goals", float("inf"))])
def test_reject_bad_statistics(normalized, metric, value):
    normalized["statistics"][metric]["home"] = value
    with pytest.raises(AnalysisError):
        generate_analysis(normalized, offline_preview=True)


def test_statistical_comparison_tie_and_zero(normalized):
    normalized["statistics"]["total_shots"] = {"home": 0, "away": 0}
    facts = build_facts(checked_fixture(normalized))
    point = next(fact for fact in facts if fact.id == "total_shots")
    assert "recorded 0 total shots" in point.sentence
    assert "level on this measure" in point.sentence


def test_source_hash_changes_with_values(normalized):
    other = copy.deepcopy(normalized)
    other["final_score"]["home"] = 3
    assert generate_analysis(normalized, offline_preview=True)["source_sha256"] != generate_analysis(other, offline_preview=True)["source_sha256"]


def test_source_unchanged(normalized):
    before = copy.deepcopy(normalized)
    generate_analysis(normalized, offline_preview=True)
    assert normalized == before
