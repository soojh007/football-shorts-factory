"""Evidence-constrained match analysis and narration assembly.

The model chooses a sequence of verified facts, never arbitrary publishable prose.
This deliberately trades creative freedom for auditable factual output.
"""
import hashlib
import json
from typing import Literal

from pydantic import Field, ValidationError

from backend.validate import NormalizedFixture, Schema


class AnalysisError(ValueError):
    """Safe-to-display analysis failure."""


class EditorialPlan(Schema):
    hook: Literal["result", "numbers"]
    fact_ids: list[str]


class Evidence(Schema):
    path: str
    value: str | int | float


class Fact(Schema):
    id: str
    sentence: str
    evidence: list[Evidence]


class AnalysisResult(Schema):
    schema_version: Literal[1] = 1
    fixture_id: int
    mode: Literal["ai", "offline_preview"]
    model: str | None
    source_sha256: str
    title: str
    summary: str
    key_points: list[Fact]
    limitations: list[str]
    script: str
    word_count: int = Field(ge=75, le=150)
    estimated_duration_seconds: float = Field(ge=30, le=60)
    assumed_words_per_minute: Literal[150] = 150
    requires_editorial_review: Literal[True] = True


LABELS = {
    "possession": "possession", "total_shots": "total shots",
    "shots_on_target": "shots on target", "expected_goals": "expected goals",
    "corners": "corners", "yellow_cards": "yellow cards", "red_cards": "straight red cards",
}


def canonical_source(fixture):
    return json.dumps(fixture, sort_keys=True, ensure_ascii=False, allow_nan=False)


def checked_fixture(value, league_id=8):
    try:
        fixture = NormalizedFixture.model_validate(value).model_dump(mode="json")
    except ValidationError:
        raise AnalysisError("Invalid normalized fixture JSON; retrieve the fixture again.") from None
    if fixture["league_id"] != league_id:
        raise AnalysisError("Fixture is not in the configured EPL league.")
    if fixture["home_team"]["id"] == fixture["away_team"]["id"]:
        raise AnalysisError("Fixture teams must be distinct.")
    for team in (fixture["home_team"], fixture["away_team"]):
        if not team["name"].strip() or any(ord(char) < 32 for char in team["name"]):
            raise AnalysisError("Invalid team name.")
    for metric, pair in fixture["statistics"].items():
        for number in pair.values():
            if number is None:
                continue
            if metric == "possession" and number > 100:
                raise AnalysisError("Possession exceeds 100 percent.")
            if metric not in ("possession", "expected_goals") and not number.is_integer():
                raise AnalysisError("Count statistics must be integers.")
    return fixture


def number(value):
    return format(value, ".12g")


def build_facts(fixture):
    home, away = fixture["home_team"]["name"], fixture["away_team"]["name"]
    score = fixture["final_score"]
    facts = [Fact(
        id="score", sentence=f"The recorded final score was {home} {score['home']}, {away} {score['away']}.",
        evidence=[Evidence(path=path, value=value) for path, value in (
            ("home_team.name", home), ("away_team.name", away),
            ("final_score.home", score["home"]), ("final_score.away", score["away"]),
        )],
    )]
    for metric, label in LABELS.items():
        pair = fixture["statistics"][metric]
        values, evidence = [], []
        for side, name in (("home", home), ("away", away)):
            value = pair[side]
            if value is None:
                continue
            unit = " percent" if metric == "possession" else ""
            values.append(f"{name} recorded {number(value)}{unit} {label}")
            evidence.extend([Evidence(path=f"{side}_team.name", value=name),
                             Evidence(path=f"statistics.{metric}.{side}", value=value)])
        if not values:
            continue
        sentence = ", while ".join(values) + "."
        if all(value is not None for value in pair.values()):
            if pair["home"] == pair["away"]:
                sentence += " The teams were level on this measure."
            else:
                leader = home if pair["home"] > pair["away"] else away
                sentence += f" {leader} had the higher recorded figure."
        facts.append(Fact(id=metric, sentence=sentence, evidence=evidence))
    return facts


def assemble_analysis(fixture, facts, plan, *, mode="ai", model=None):
    by_id = {fact.id: fact for fact in facts}
    ids = plan.fact_ids
    expected_count = min(4, len(facts) - 1)
    if (len(ids) != expected_count or len(ids) != len(set(ids))
            or any(fact_id not in by_id or fact_id == "score" for fact_id in ids)):
        raise AnalysisError("AI selected invalid, duplicate, or unavailable facts.")
    selected = [by_id["score"], *(by_id[fact_id] for fact_id in ids)]
    limitations = []
    for metric, pair in fixture["statistics"].items():
        missing = [side for side, value in pair.items() if value is None]
        if missing:
            limitations.append(f"{metric}: unavailable for {', '.join(missing)}; no values inferred.")
    limitations.append("Aggregate statistics do not establish tactics, causation, or player performance.")
    limitations.append("Goal chronology is not analyzed; provider goal events may require reconciliation.")
    opening = {
        "result": "Here is the final score, followed by the available match numbers. Let's look at what the recorded data tells us.",
        "numbers": "What do the recorded numbers tell us about this match? Start with the final score, then look at the available statistics.",
    }[plan.hook]
    sentences = [fact.sentence for fact in selected]
    closing = ("These figures describe the recorded match totals. They do not tell us why the result happened, "
               "or establish how either team set up tactically. What stands out to you from the available numbers?")
    script = " ".join([opening, *sentences, closing])
    # Long team names/large facts can exceed a Shorts budget. Drop lower-ranked facts,
    # retaining a source reference for every sentence that actually appears.
    while len(script.split()) > 150 and len(selected) > 1:
        selected.pop()
        script = " ".join([opening, *(fact.sentence for fact in selected), closing])
    if len(script.split()) < 75:
        script += (" This is a data summary rather than a full account of every moment in the game. "
                   "A complete tactical assessment would also require reviewing the match footage.")
    count = len(script.split())
    if not 75 <= count <= 150:
        raise AnalysisError("Unable to fit verified facts within the narration word budget.")
    home, away = fixture["home_team"]["name"], fixture["away_team"]["name"]
    score = fixture["final_score"]
    return AnalysisResult(
        fixture_id=fixture["fixture_id"], mode=mode, model=model,
        source_sha256=hashlib.sha256(canonical_source(fixture).encode()).hexdigest(),
        title=f"{home} {score['home']}–{score['away']} {away} | Match numbers",
        summary=" ".join(fact.sentence for fact in selected), key_points=selected,
        limitations=limitations, script=script, word_count=count,
        estimated_duration_seconds=round(count / 150 * 60, 1),
    ).model_dump(mode="json")


def generate_analysis(source, client=None, *, offline_preview=False, league_id=8):
    fixture = checked_fixture(source, league_id)
    facts = build_facts(fixture)
    if offline_preview:
        plan = EditorialPlan(hook="result", fact_ids=[fact.id for fact in facts[1:5]])
        return assemble_analysis(fixture, facts, plan, mode="offline_preview")
    if client is None:
        raise AnalysisError("An AI client is required unless --offline-preview is selected.")
    plan = client.select_facts(facts)
    return assemble_analysis(fixture, facts, plan, model=client.model)
