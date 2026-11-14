"""Auditable lineup- and venue-conditioned forecast, not a calibrated betting model."""
from copy import deepcopy
import math

from backend.prediction import PredictionError,make_prediction
from backend.prematch import kickoff_utc


def venue_context(fixture,team_id):
    venue=fixture.get('venue') or {}
    if not venue.get('name') or type(venue.get('country_id')) is not int:
        raise PredictionError('A verified venue and venue country are required for the contextual forecast.')
    participants=fixture.get('participants') or []
    own=next((p for p in participants if p.get('id')==team_id),{})
    other=next((p for p in participants if p.get('id')!=team_id),{})
    neutral=None
    for meta in fixture.get('metadata') or []:
        code=(meta.get('type') or {}).get('code')
        if code=='neutral_venue' or meta.get('type_id')==35:
            value=(meta.get('values') or {}).get('neutral')
            if type(value) is bool: neutral=value
    country=venue['country_id']
    if neutral is True:
        role='neutral'
    elif country==own.get('country_id') and neutral is False:
        role='own_country'
    elif country==other.get('country_id') and neutral is False:
        role='opponent_country'
    elif type(own.get('country_id')) is int and type(other.get('country_id')) is int and country not in (own['country_id'],other['country_id']):
        role='third_country'
    else:
        role='neutrality_unverified'
    return {'id':venue.get('id'),'name':venue['name'],'city':venue.get('city_name'),
            'country_id':country,'neutral':neutral,'role':role,'image_url':venue.get('image_path')}


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
    if len(samples)<3:
        raise PredictionError('Fewer than three recent matches have usable historical starting XIs. A scores-only forecast will not be substituted.')
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
    values=[(h,a,math.exp(-home_rate-away_rate)*home_rate**h/math.factorial(h)*away_rate**a/math.factorial(a))
            for h in range(16) for a in range(16)]
    mass=sum(p for _,_,p in values)
    probabilities={key:sum(p for h,a,p in values if ('home' if h>a else 'away' if a>h else 'draw')==key)/mass
                   for key in ('home','draw','away')}
    outcome=max(probabilities,key=probabilities.get)
    h,a,p=max((row for row in values if ('home' if row[0]>row[1] else 'away' if row[1]>row[0] else 'draw')==outcome),key=lambda row:row[2])
    return probabilities,outcome,{'home':h,'away':a},p/mass


def contextual_prediction(fixture,histories,lineups,as_of,*,league_id=1082,research=None):
    if lineups.get('confirmed') is not True or lineups.get('fixture_id')!=fixture.get('id'):
        raise PredictionError('The contextual forecast requires matching confirmed lineups.')
    result=make_prediction(fixture,histories,as_of=as_of,league_id=league_id)
    profiles={};venues={}
    for side in ('home','away'):
        team=result['teams'][side]
        venues[side]=venue_context(fixture,team['id'])
        profiles[side]=lineup_profile(team['id'],lineups[side],histories[side],result['form'][side],as_of)
    factors={'own_country':1.06,'opponent_country':.97,'neutral':1.0,'third_country':1.0,'neutrality_unverified':1.0}
    h,a=profiles['home'],profiles['away']
    home_rate=(h['rates']['goals_for']+a['rates']['goals_against'])/2*h['rating_factor']*factors[venues['home']['role']]
    away_rate=(a['rates']['goals_for']+h['rates']['goals_against'])/2*a['rating_factor']*factors[venues['away']['role']]
    probabilities,outcome,pick,score_mass=distribution(home_rate,away_rate)
    result['lineups']=deepcopy(lineups)
    result['context']={'venue':venues['home'],'venue_by_team':venues,'lineup_profiles':profiles,
                       'web_research':research or {'performed':False,'claims':[],'sources':[]}}
    result['forecast']={'model':'lineup-venue-poisson-v2','calibrated':False,'probabilities':probabilities,
        'outcome':outcome,'score_pick':pick,'score_pick_probability':score_mass,
        'model_goal_rates':{'home':home_rate,'away':away_rate},
        'assumptions':{'prior_matches':3,'prior_goals_per_game':1.4,'lineup_weight':'0.35 + 0.65 * overlap/11',
            'rating_adjustment':'1 + 0.08 * current-XI mean minus historical-XI mean; clipped 0.92–1.08; >=6 rated starters required',
            'venue_factors':factors,'coefficients_hand_set_not_fitted':True},
        'limitations':['Experimental coefficients, not backtested or calibrated.','Lineup overlap is not a complete player-strength model.',
            'Player ratings are missing for some players and depend on provider coverage.','Opponent strength, travel and weather are not quantitatively modeled.',
            'Internet reports are sourced context and cross-checks, not arbitrary numeric boosts.']}
    home,away=result['teams']['home']['name'],result['teams']['away']['name']
    preferred=home if outcome=='home' else away if outcome=='away' else 'a draw'
    featured={side:sorted(lineups[side]['starters'],key=lambda p:profiles[side]['player_ratings'].get(str(p['player_id']),-1),reverse=True)[:2] for side in ('home','away')}
    result['featured_players']=featured
    venue=venues['home']
    place=venue['city'] or venue['name']
    venue_text=(f"This one's in {place}. I give {home} a small venue edge on home soil." if venue['role']=='own_country'
        else f"This one's in {place}, so I am not assuming a home-ground advantage." if venue['role'] in ('neutral','third_country','neutrality_unverified')
        else f"This one's in {place}. I give {away} the small venue edge here.")
    lineup_text=(f"I'm checking the actual eleven. {home} retain {h['latest_starters_retained']} starters from their latest sampled friendly; "
                 f"{away} retain {a['latest_starters_retained']}. That changes how I weight their recent results.")
    claims=(research or {}).get('claims') or []
    news=next((claim for claim in claims if claim['status']=='confirmed' and claim['topic']=='team_news'),None)
    sections=[{'kind':'hook','text':f"I'm leaning towards {preferred}. But I'm checking the players and the ground, not just the last score."},
              {'kind':'players','text':lineup_text}, {'kind':'venue','text':venue_text}]
    if news:
        sections.append({'kind':'research','text':f"I've also checked the team news: {news['summary']}"})
    elif (research or {}).get('performed'):
        sections.append({'kind':'research','text':"I checked outside reports too, but I'm not adding unverified team news."})
    sections.extend([{'kind':'pick','text':f"My call is {home} {pick['home']}, {away} {pick['away']}. That's my read of the lineup-weighted form and the venue."},
                     {'kind':'caveat','text':"What could trip me up? Opponent quality and late changes. This is my tentative pick, not a certainty."}])
    if len(' '.join(section['text'] for section in sections).split())>150:
        sections=[section for section in sections if section['kind']!='research']
    result['sections']=sections
    result['script']=' '.join(section['text'] for section in sections)
    result['word_count']=len(result['script'].split())
    return result
