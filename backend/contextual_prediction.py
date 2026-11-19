"""Auditable lineup- and venue-conditioned forecast, not a calibrated betting model."""
from copy import deepcopy
import math

from backend.prediction import PredictionError,make_prediction
from backend.prematch import kickoff_utc


def venue_context(fixture,team_id):
    venue=fixture.get('venue')
    if not isinstance(venue,dict): venue={}
    participants=fixture.get('participants') or []
    own=next((p for p in participants if p.get('id')==team_id),{})
    other=next((p for p in participants if p.get('id')!=team_id),{})
    neutral=None
    for meta in fixture.get('metadata') or []:
        code=(meta.get('type') or {}).get('code')
        if code=='neutral_venue' or meta.get('type_id')==35:
            value=(meta.get('values') or {}).get('neutral')
            if type(value) is bool: neutral=value
    country=venue.get('country_id')
    if type(country) is not int: country=None
    if neutral is True:
        role='neutral'
    elif country is None:
        role='unknown'
    elif own.get('country_id')==other.get('country_id'):
        # Domestic clubs share a country: country alone proves no home-ground edge.
        role='neutrality_unverified'
    elif country==own.get('country_id') and neutral is False:
        role='own_country'
    elif country==other.get('country_id') and neutral is False:
        role='opponent_country'
    elif type(own.get('country_id')) is int and type(other.get('country_id')) is int and country not in (own['country_id'],other['country_id']):
        role='third_country'
    else:
        role='neutrality_unverified'
    return {'id':venue.get('id'),'name':venue.get('name') or None,'city':venue.get('city_name'),
            'country_id':country,'neutral':neutral,'role':role,'image_url':venue.get('image_path')}


def venue_changed(before,after):
    """Only contradicting known facts require a rebuild; missing fields do not."""
    return any(before.get(key) is not None and after.get(key) is not None
               and before[key]!=after[key] for key in ('id','name','city','country_id','neutral'))


def rating(entry):
    for detail in entry.get('details') or []:
        if (detail.get('type') or {}).get('code')=='rating':
            value=(detail.get('data') or {}).get('value')
            if type(value) in (float,int) and math.isfinite(value) and 0<=value<=10:
                return float(value)
    return None


def lineup_profile(team_id,current,histories,form,cutoff):
    wanted={p['player_id'] for p in current['starters']}
    by_id={f['id']:f for f in histories if kickoff_utc(f)<cutoff}
    samples=[];player_ratings={};historical_ratings=[]
    for match in form['matches']:
        source=by_id.get(match['fixture_id']) or {}
        starters=[p for p in source.get('lineups') or [] if p.get('team_id')==team_id and p.get('type_id')==11]
        ids={p.get('player_id') for p in starters if type(p.get('player_id')) is int}
        if len(ids)!=11:
            continue
        overlap=len(wanted&ids)
        weight=.35+.65*overlap/11
        samples.append({**match,'starters_retained':overlap,'lineup_weight':weight})
        for player in starters:
            value=rating(player)
            if value is not None:
                historical_ratings.append(value)
                if player['player_id'] in wanted:
                    player_ratings.setdefault(player['player_id'],[]).append(value)
    if len(samples)<3 or not wanted:
        samples=[{**match,'starters_retained':None,'lineup_weight':1.0} for match in form['matches']]
        player_ratings={}; historical_ratings=[]
    current_values=[sum(values)/len(values) for values in player_ratings.values()]
    average=sum(current_values)/len(current_values) if current_values else None
    baseline=sum(historical_ratings)/len(historical_ratings) if historical_ratings else None
    delta=average-baseline if len(current_values)>=6 and baseline is not None else 0.0
    quality_factor=max(.92,min(1.08,1+.08*delta))
    total=sum(m['lineup_weight'] for m in samples)
    rates={field:(sum(m[field]*m['lineup_weight'] for m in samples)+3*1.4)/(total+3)
           for field in ('goals_for','goals_against')}
    latest=samples[0]
    return {'samples':samples,'rates':rates,'latest_starters_retained':latest['starters_retained'],
            'rated_current_starters':len(current_values),'current_starter_mean_rating':average,
            'historical_starter_mean_rating':baseline,'rating_factor':quality_factor,
            'rating_factor_applied':len(current_values)>=6,'player_ratings':{str(key):sum(values)/len(values) for key,values in player_ratings.items()}}


def distribution(home_rate,away_rate):
    from backend.league_poisson import score_matrix
    grid=score_matrix(home_rate,away_rate)
    return grid['probabilities'],grid['outcome'],grid['score_pick'],grid['score_pick_probability']


def contextual_prediction(fixture,histories,lineups,as_of,*,league_id=None,research=None,league_fixtures=None):
    if lineups.get('fixture_id')!=fixture.get('id'):
        raise PredictionError('The contextual forecast requires matching fixture identity.')
    lineups=deepcopy(lineups)
    if not lineups.get('confirmed'):
        for side in ('home','away'):lineups[side]['starters']=[]
    league_id=fixture.get('league_id') if league_id is None else league_id
    result=make_prediction(fixture,histories,as_of=as_of,league_id=league_id,min_matches=1)
    profiles={};venues={}
    for side in ('home','away'):
        team=result['teams'][side]
        # Conflicting venue reports exclude only venue context, not the match.
        venue_fixture={} if (research or {}).get('venue_check')=='conflicting' else fixture
        venues[side]=venue_context(venue_fixture,team['id'])
        profiles[side]=lineup_profile(team['id'],lineups[side],histories[side],result['form'][side],as_of)
    factors={'own_country':1.06,'opponent_country':.97,'neutral':1.0,'third_country':1.0,'neutrality_unverified':1.0,'unknown':1.0}
    h,a=profiles['home'],profiles['away']
    home_rate=(h['rates']['goals_for']+a['rates']['goals_against'])/2*h['rating_factor']*factors[venues['home']['role']]
    away_rate=(a['rates']['goals_for']+h['rates']['goals_against'])/2*a['rating_factor']*factors[venues['away']['role']]
    rankings={row['team_id']:row for row in (research or {}).get('fifa_rankings',[])}
    rank_by_side={side:rankings[team['id']] for side,team in result['teams'].items() if team['id'] in rankings}
    from backend.strength import strength_rates
    base_home=(h['rates']['goals_for']+a['rates']['goals_against'])/2
    base_away=(a['rates']['goals_for']+h['rates']['goals_against'])/2
    fitted,strength=strength_rates(rank_by_side,fixture,as_of,base_home,base_away,venues['home']['role'])
    applied_venue={side:factors[venues[side]['role']] for side in venues}
    if fitted:
        home_rate=fitted[0]*h['rating_factor'];away_rate=fitted[1]*a['rating_factor']
        applied_venue=strength['venue_factors']
    from backend.league_poisson import league_rates,score_matrix,MODEL_VERSION
    league_fit,league_detail=league_rates(fixture,league_fixtures,as_of,
        neutral=venues['home']['neutral'] is True,profiles=profiles)
    if league_fit and not fitted:
        home_rate=league_fit[0]*h['rating_factor']
        away_rate=league_fit[1]*a['rating_factor']
        # League home/away averages already encode the fixture-role effect.
        applied_venue={'home':1.0,'away':1.0}
    matrix=score_matrix(home_rate,away_rate)
    probabilities,outcome,pick,score_mass=(matrix[k] for k in ('probabilities','outcome','score_pick','score_pick_probability'))
    result['lineups']=deepcopy(lineups)
    result['context']={'venue':venues['home'],'venue_by_team':venues,'lineup_profiles':profiles,
                       'fifa_rankings':rank_by_side,'latest_matches':(research or {}).get('provider_latest',{}),'web_research':research or {'performed':False,'claims':[],'sources':[]}}
    result['forecast']={'model':'lineup-fifa-strength-poisson-v4' if fitted else MODEL_VERSION if league_fit else 'lineup-venue-form-poisson-v4','calibrated':False,'probabilities':probabilities,
        'outcome':outcome,'score_pick':pick,'score_pick_probability':score_mass,
        'model_goal_rates':{'home':home_rate,'away':away_rate},
        'overall_modal_score':matrix['overall_modal_score'],'overall_modal_score_probability':matrix['overall_modal_score_probability'],
        'score_matrix':matrix['score_matrix'],
        'assumptions':{'league_strength_model':league_detail,'score_selection':'modal score conditional on most likely outcome; overall modal score provided separately','independent_goal_counts':True,'strength_model':strength,'prior_matches':3,'prior_goals_per_game':None if league_fit else 1.4,'prior_baseline':{side:league_detail['teams'][side]['goals_for_baseline'] for side in ('home','away')} if league_fit else 'fixed recent-form prior','lineup_weight':'0.35 + 0.65 * overlap/11',
            'rating_adjustment':'1 + 0.08 * current-XI mean minus historical-XI mean; clipped 0.92–1.08; >=6 rated starters required',
            'venue_factors':factors,'applied_venue_factors':applied_venue,'lineup_overlay_coefficients_hand_set':True,'strength_coefficients_fitted':strength.get('applied',False)},
        'limitations':['FIFA strength coefficients have chronological retrospective validation; outcome probabilities are not prospectively calibrated.' if fitted else 'The applied form/league model is not chronologically backtested or calibrated.','Lineup overlap is not a complete player-strength model.',
            'Player ratings are missing for some players and depend on provider coverage.','Travel and weather are not quantitatively modeled; rank-based strength requires matching FIFA points.',
            'Internet reports are sourced context and cross-checks, not arbitrary numeric boosts.']}
    if league_fit:
        result['forecast']['limitations'].append('League attack/defence model uses current-season pre-cutoff results with hand-set shrinkage; not yet chronologically backtested or calibrated.')
    else:
        result['forecast']['limitations'].append('League-relative baseline not applied: '+league_detail['reason']+'.')
    if any(form['sample_size']<3 for form in result['form'].values()):
        result['forecast']['limitations'].append('Small available result sample; prior shrinkage retained and actual sample sizes recorded.')
    if venues['home']['role']=='unknown' and not league_fit:
        result['forecast']['limitations'].append('Venue context unavailable or conflicting; no venue adjustment applied.')
    home,away=result['teams']['home']['name'],result['teams']['away']['name']
    preferred=home if outcome=='home' else away if outcome=='away' else 'a draw'
    featured={side:sorted(lineups[side]['starters'],key=lambda p:profiles[side]['player_ratings'].get(str(p['player_id']),-1),reverse=True)[:2] for side in ('home','away')}
    result['featured_players']=featured
    result['archive_players']={}
    for side in ('home','away'):
        completed=sorted((row for row in histories[side] if kickoff_utc(row)<as_of),key=kickoff_utc,reverse=True)
        pool=[];seen=set()
        for row in completed[:3]:
            for player in row.get('lineups') or []:
                pid=player.get('player_id');name=player.get('player_name')
                if player.get('team_id')==result['teams'][side]['id'] and player.get('type_id')==11 and type(pid) is int and isinstance(name,str) and name.strip() and pid not in seen:
                    seen.add(pid);pool.append({'player_id':pid,'name':name.strip(),'archive_only':True})
        result['archive_players'][side]=pool[:6]
    # Offline assembly is a plain-language preview. Production uses EditorialClient.
    home_player=featured['home'][0]['name'] if featured['home'] else None;away_player=featured['away'][0]['name'] if featured['away'] else None
    sections=[{'kind':'hook','text':f"I'm backing {preferred} here. This is the sort of matchup where the starting eleven makes the difference for me."},
        {'kind':'players','text':f"{home_player} starts for {home}, and {away_player} is in {away}'s eleven. Those are two names I'll be watching. {home} bring back {h['latest_starters_retained']} starters from their last sampled match, compared with {a['latest_starters_retained']} for {away}."},
        {'kind':'players','text':f"Across their last {result['form']['home']['sample_size']} matches in this competition, {home} scored {result['form']['home']['goals_for']} goals. {away} scored {result['form']['away']['goals_for']} across their last {result['form']['away']['sample_size']}. That's the recent picture behind my call."},
        {'kind':'pick','text':f"My call is {home} {pick['home']}, {away} {pick['away']}. That's my pick."}]
    if not lineups.get('confirmed'):
        sections=[sections[0],sections[2],sections[-1]]
        sections[0]['text']=f"I'm backing {preferred} here. For me, this matchup has the makings of an interesting contest."
        result['forecast']['limitations'].append('Confirmed lineups unavailable; no starter continuity or player-rating adjustment applied.')
    if lineups.get('confirmed') and (h['latest_starters_retained'] is None or a['latest_starters_retained'] is None):
        sections[1]['text']=f"{home_player} starts for {home}, and {away_player} is in {away}'s eleven. Those are two names I'll be watching."
    result['sections']=sections
    result['script']=' '.join(section['text'] for section in sections)
    result['word_count']=len(result['script'].split())
    return result
