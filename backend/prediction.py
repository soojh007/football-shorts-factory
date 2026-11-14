"""Transparent recent-form forecast, deliberately separate from completed-match data."""
from datetime import datetime, timezone
import math

from backend.prematch import kickoff_utc
from backend.sportmonks import SportmonksError
from backend.validate import FixtureValidationError, validate_fixture

MODEL_VERSION = 'recent-form-poisson-v1'


class PredictionError(ValueError):
    """Safe prediction data/model error."""


def teams_for_preview(fixture, as_of, league_id=8):
    if fixture.get('league_id') != league_id or fixture.get('state_id') != 1:
        raise PredictionError('Prediction requires a not-started fixture in the configured league.')
    state = fixture.get('state') or {}
    if state.get('id', 1) != 1:
        raise PredictionError('Fixture state metadata disagrees with not-started status.')
    if kickoff_utc(fixture) <= as_of:
        raise PredictionError('Prediction kickoff must be in the future; retrospective forecasts are rejected.')
    teams = {}
    for participant in fixture.get('participants') or []:
        side = (participant.get('meta') or {}).get('location')
        if side not in ('home', 'away') or side in teams:
            raise PredictionError('Missing or ambiguous pre-match team mapping.')
        if type(participant.get('id')) is not int or participant['id'] <= 0 or not isinstance(participant.get('name'), str) or not participant['name'].strip():
            raise PredictionError('Missing pre-match team identity.')
        teams[side] = {'id': participant['id'], 'name': participant['name'].strip()}
    if set(teams) != {'home', 'away'} or teams['home']['id'] == teams['away']['id']:
        raise PredictionError('Prediction needs two distinct teams.')
    return teams


def recent_form(fixtures, team_id, as_of, *, league_id=8, sample_size=5):
    eligible, excluded = [], []
    seen = set()
    for fixture in fixtures:
        if fixture.get('id') in seen:
            continue
        seen.add(fixture.get('id'))
        if fixture.get('league_id') != league_id or fixture.get('state_id') != 5:
            continue
        if kickoff_utc(fixture) >= as_of:
            continue
        try:
            teams, score, _ = validate_fixture(fixture, league_id)
        except FixtureValidationError:
            excluded.append(fixture.get('id'))
            continue
        sides = [side for side, team in teams.items() if team.id == team_id]
        if len(sides) != 1:
            continue
        side = sides[0]
        opponent = 'away' if side == 'home' else 'home'
        goals_for, goals_against = getattr(score, side), getattr(score, opponent)
        eligible.append({'fixture_id': fixture['id'], 'kickoff': kickoff_utc(fixture).isoformat(),
                         'opponent': teams[opponent].name, 'location': side,
                         'goals_for': goals_for, 'goals_against': goals_against,
                         'result': 'W' if goals_for > goals_against else 'D' if goals_for == goals_against else 'L'})
    eligible.sort(key=lambda match: match['kickoff'], reverse=True)
    sample = eligible[:sample_size]
    if len(sample) < 3:
        raise PredictionError('At least three valid recent results in the selected competition per team are required; no prediction fabricated.')
    return {'team_id': team_id, 'sample_size': len(sample), 'matches': sample,
            'sequence': ''.join(match['result'] for match in sample),
            'wins': sum(match['result'] == 'W' for match in sample),
            'draws': sum(match['result'] == 'D' for match in sample),
            'losses': sum(match['result'] == 'L' for match in sample),
            'goals_for': sum(match['goals_for'] for match in sample),
            'goals_against': sum(match['goals_against'] for match in sample),
            'excluded_invalid_fixture_ids': excluded}


def poisson_forecast(home_form, away_form, *, home_multiplier=1.0):
    # Small-sample shrinkage toward an explicit 1.4 goal/team/game prior.
    # This is an illustrative assumption, not a measured league baseline.
    prior_matches, prior_goals = 3, 1.4
    def rate(form, field):
        return (form[field] + prior_matches * prior_goals) / (form['sample_size'] + prior_matches)
    home_rate = (rate(home_form, 'goals_for') + rate(away_form, 'goals_against')) / 2 * home_multiplier
    away_rate = (rate(away_form, 'goals_for') + rate(home_form, 'goals_against')) / 2
    masses = []
    for home in range(16):
        for away in range(16):
            probability = (math.exp(-home_rate) * home_rate ** home / math.factorial(home)
                           * math.exp(-away_rate) * away_rate ** away / math.factorial(away))
            masses.append((home, away, probability))
    total = sum(probability for _, _, probability in masses)
    probabilities = {'home': 0.0, 'draw': 0.0, 'away': 0.0}
    for home, away, probability in masses:
        probabilities['home' if home > away else 'away' if away > home else 'draw'] += probability / total
    outcome = max(probabilities, key=probabilities.get)
    # Pick the most likely score CONDITIONAL on the chosen most-likely outcome,
    # rather than claiming the overall modal score always matches that outcome.
    candidates = [(home, away, probability) for home, away, probability in masses
                  if ('home' if home > away else 'away' if away > home else 'draw') == outcome]
    home, away, mass = max(candidates, key=lambda item: item[2])
    return {'model': MODEL_VERSION, 'calibrated': False, 'outcome': outcome,
            'score_pick': {'home': home, 'away': away},
            'probabilities': probabilities, 'score_pick_probability': mass / total,
            'model_goal_rates': {'home': home_rate, 'away': away_rate},
            'assumptions': {'prior_matches': prior_matches, 'prior_goals_per_team_per_match': prior_goals,
                            'home_multiplier': home_multiplier, 'result_probability_mass_truncated_then_renormalized': True, 'score_grid_max_goals': 15,
                            'retained_probability_mass': total},
            'limitations': ['Exploratory small-sample model; not backtested or calibrated.',
                'Opponent strength and home/away-specific form are not adjusted.',
                'Lineups, injuries, rest, transfers and market odds are not included.',
                'Model goal rates are estimates, not measured xG statistics.',
                'A selected score is speculative, not a guaranteed result.']}


def make_prediction(fixture, histories, *, as_of=None, league_id=8):
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        raise PredictionError('Prediction cutoff must include a timezone.')
    teams = teams_for_preview(fixture, as_of, league_id)
    forms = {side: recent_form(histories[side], team['id'], as_of, league_id=league_id)
             for side, team in teams.items()}
    forecast = poisson_forecast(forms['home'], forms['away'], home_multiplier=1.0)
    h, a = teams['home']['name'], teams['away']['name']
    pick = forecast['score_pick']
    selection = f"{h} to win" if forecast['outcome'] == 'home' else f"{a} to win" if forecast['outcome'] == 'away' else 'a draw'
    competition = (fixture.get('league') or {}).get('name') or ('Friendly International' if league_id == 1082 else 'the selected competition')
    form_label = 'international friendlies' if league_id == 1082 else 'games in this competition'
    home_wins = 'win' if forms['home']['wins'] == 1 else 'wins'
    away_wins = 'win' if forms['away']['wins'] == 1 else 'wins'
    away_draws = 'draw' if forms['away']['draws'] == 1 else 'draws'
    sections = [
        {'kind': 'hook', 'text': f"{h} have {forms['home']['wins']} {home_wins} in their last {forms['home']['sample_size']} {form_label}. My pick is {selection}. Here's the case."},
        {'kind': 'home_form', 'text': f"{h} have scored {forms['home']['goals_for']} and conceded {forms['home']['goals_against']} across those {forms['home']['sample_size']} games."},
        {'kind': 'away_form', 'text': f"{a} have {forms['away']['wins']} {away_wins} and {forms['away']['draws']} {away_draws} in their last {forms['away']['sample_size']}, scoring {forms['away']['goals_for']} and conceding {forms['away']['goals_against']}."},
        {'kind': 'pick', 'text': f"The model combines recent scoring with the other side's conceding. My score pick: {h} {pick['home']}, {a} {pick['away']}."},
        {'kind': 'caveat', 'text': "That is speculative. This model is not calibrated, doesn't adjust for opponent strength, and doesn't know the lineups. In a friendly, changes in personnel can matter."},
    ]
    script = ' '.join(section['text'] for section in sections)
    return {'schema_version': 1, 'content_type': 'prediction', 'fixture_id': fixture['id'],
            'league_id': league_id, 'competition': competition, 'kickoff': kickoff_utc(fixture).isoformat(),
            'as_of': as_of.isoformat(), 'teams': teams, 'form': forms, 'forecast': forecast,
            'title': f"{h} vs {a} | Score prediction", 'script': script,
            'word_count': len(script.split()), 'sections': sections, 'requires_editorial_review': True}
