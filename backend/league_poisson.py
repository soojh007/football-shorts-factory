"""League-relative attack/defence goal rates and auditable independent Poisson grid."""
from datetime import timedelta
import math

from backend.prediction import PredictionError
from backend.prematch import kickoff_utc
from backend.sportmonks import SportmonksError
from backend.validate import validate_fixture, FixtureValidationError

MODEL_VERSION='league-attack-defence-poisson-v1'
PRIOR_MATCHES=3
MIN_LEAGUE_MATCHES=10
LOOKBACK_DAYS=180


def club_fixture(fixture):
    participants=fixture.get('participants') or []
    return len(participants)==2 and all(p.get('type') in ('domestic','club') for p in participants)


def collect_league_results(client,fixture,as_of):
    """League-wide sample, not just the two teams. No future requests or mixed leagues."""
    if not club_fixture(fixture):return []
    rows=[];start=as_of.date()-timedelta(days=LOOKBACK_DAYS)
    while start<=as_of.date():
        end=min(start+timedelta(days=99),as_of.date())
        rows.extend(client.fixture_window(start,end,league_id=fixture['league_id']))
        start=end+timedelta(days=1)
    return rows


def league_rates(fixture,rows,as_of,*,neutral=False,profiles=None):
    """Return (lambdas, provenance), or an explicit missing-data fallback reason."""
    detail={'applied':False,'model':MODEL_VERSION,'league_id':fixture.get('league_id'),
            'season_id':fixture.get('season_id'),'cutoff':as_of.isoformat(),
            'lookback_days':LOOKBACK_DAYS,'prior_matches':PRIOR_MATCHES,
            'minimum_league_matches':MIN_LEAGUE_MATCHES}
    def unavailable(reason):return None,{**detail,'reason':reason}
    if not club_fixture(fixture):return unavailable('not_a_verified_club_fixture')
    if type(fixture.get('season_id')) is not int:return unavailable('missing_season_id')
    completed={};conflicts=set()
    for row in rows or []:
        if not isinstance(row,dict) or type(row.get('id')) is not int:continue
        if row.get('id')==fixture['id'] or row.get('league_id')!=fixture['league_id'] or row.get('season_id')!=fixture['season_id'] or row.get('state_id')!=5:continue
        try:
            stamp=kickoff_utc(row)
            if not as_of-timedelta(days=LOOKBACK_DAYS)<=stamp<as_of:continue
            teams,score,_=validate_fixture(row,fixture['league_id'])
        except (FixtureValidationError,SportmonksError,ValueError,TypeError):continue
        value={'fixture_id':row['id'],'kickoff':stamp.isoformat(),
               'home_id':teams['home'].id,'away_id':teams['away'].id,
               'home_goals':score.home,'away_goals':score.away}
        if row['id'] in completed and completed[row['id']]!=value:conflicts.add(row['id'])
        completed[row['id']]=value
    for key in conflicts:completed.pop(key,None)
    matches=sorted(completed.values(),key=lambda m:m['kickoff'])
    detail.update(sample_size=len(matches),fixture_ids=[m['fixture_id'] for m in matches],
                  excluded_conflicting_fixture_ids=sorted(conflicts))
    if len(matches)<MIN_LEAGUE_MATCHES:return unavailable('insufficient_current_season_league_results')
    home_mean=sum(m['home_goals'] for m in matches)/len(matches)
    away_mean=sum(m['away_goals'] for m in matches)/len(matches)
    if min(home_mean,away_mean)<=0:return unavailable('zero_scoring_baseline')
    means={'home':home_mean,'away':away_mean}
    detail['league_goal_averages']=means
    teams={p['meta']['location']:p['id'] for p in fixture['participants']}
    summaries={};used_lineup_weights=False
    for side in ('home','away'):
        weights={m['fixture_id']:m['lineup_weight'] for m in (profiles or {}).get(side,{}).get('samples',[])}
        observations=[]
        for m in matches:
            location='home' if m['home_id']==teams[side] else 'away' if m['away_id']==teams[side] else None
            if location is None or (not neutral and location!=side):continue
            other='away' if location=='home' else 'home'
            observations.append((m,location,other,weights.get(m['fixture_id'],1.0)))
        used_lineup_weights=used_lineup_weights or any(w!=1 for _,_,_,w in observations)
        total=sum(w for _,_,_,w in observations)
        for_baseline=(home_mean+away_mean)/2 if neutral else means[side]
        against_baseline=(home_mean+away_mean)/2 if neutral else means['away' if side=='home' else 'home']
        gf=sum(m[loc+'_goals']*w for m,loc,_,w in observations)
        ga=sum(m[other+'_goals']*w for m,_,other,w in observations)
        attack=(gf+PRIOR_MATCHES*for_baseline)/(total+PRIOR_MATCHES)/for_baseline
        defence=(ga+PRIOR_MATCHES*against_baseline)/(total+PRIOR_MATCHES)/against_baseline
        summaries[side]={'team_id':teams[side],'sample_size':len(observations),'effective_matches':total,
                         'fixture_ids':[m['fixture_id'] for m,_,_,_ in observations],
                         'weighted_goals_for':gf,'weighted_goals_against':ga,
                         'attack_strength':attack,'defence_weakness':defence,
                         'goals_for_baseline':for_baseline,'goals_against_baseline':against_baseline}
    h,a=summaries['home'],summaries['away']
    home_base=(home_mean+away_mean)/2 if neutral else home_mean
    away_base=(home_mean+away_mean)/2 if neutral else away_mean
    rates=(home_base*h['attack_strength']*a['defence_weakness'],
           away_base*a['attack_strength']*h['defence_weakness'])
    return rates,{**detail,'applied':True,'teams':summaries,
                  'venue_basis':'neutral_pooled' if neutral else 'designated_home_away',
                  'physical_home_ground_verified':False,
                  'formula':'lambda_home = mu_home * home_attack * away_defence_weakness; lambda_away = mu_away * away_attack * home_defence_weakness',
                  'lineup_weighting_applied':used_lineup_weights,
                  'base_goal_rates':{'home':rates[0],'away':rates[1]}}


def poisson_masses(rate):
    if type(rate) not in (int,float) or not math.isfinite(rate) or not 0<=rate<=100:
        raise PredictionError('Poisson goal rate must be finite and between 0 and 100.')
    values=[math.exp(-rate)]
    while len(values)<max(16,math.ceil(rate)+1) or math.fsum(values)<1-1e-12:
        k=len(values);values.append(values[-1]*rate/k)
        if len(values)>512:raise PredictionError('Poisson support did not converge.')
    return values


def score_matrix(home_rate,away_rate):
    home,away=poisson_masses(home_rate),poisson_masses(away_rate)
    grid=[[h*a for a in away] for h in home]
    retained=math.fsum(math.fsum(row) for row in grid)
    probabilities={key:math.fsum(p for h,row in enumerate(grid) for a,p in enumerate(row)
                    if ('home' if h>a else 'away' if a>h else 'draw')==key)/retained for key in ('home','draw','away')}
    outcome=max(probabilities,key=probabilities.get)
    cells=[(p,h,a) for h,row in enumerate(grid) for a,p in enumerate(row)]
    # Stable low-score tie break, matching existing presentation behavior.
    mode=max(cells,key=lambda x:x[0])
    chosen=max((x for x in cells if ('home' if x[1]>x[2] else 'away' if x[2]>x[1] else 'draw')==outcome),key=lambda x:x[0])
    return {'probabilities':probabilities,'outcome':outcome,'score_pick':{'home':chosen[1],'away':chosen[2]},
            'score_pick_probability':chosen[0]/retained,'overall_modal_score':{'home':mode[1],'away':mode[2]},
            'overall_modal_score_probability':mode[0]/retained,
            'score_matrix':{'rows':'home_goals','columns':'away_goals','cells':grid,
                            'max_home_goals':len(home)-1,'max_away_goals':len(away)-1,
                            'retained_probability_mass':retained,'tail_probability':max(0,1-retained),
                            'cells_are_unconditional_probabilities':True,'outcomes_renormalized_to_retained_mass':True}}


def main(argv=None):
    import argparse,json
    from pathlib import Path
    parser=argparse.ArgumentParser(description='Calculate independent Poisson score probabilities from two goal rates.')
    parser.add_argument('--home-rate',required=True,type=float)
    parser.add_argument('--away-rate',required=True,type=float)
    parser.add_argument('--output',type=Path,help='Optional JSON containing the complete probability matrix.')
    args=parser.parse_args(argv)
    try:result=score_matrix(args.home_rate,args.away_rate)
    except PredictionError as exc:parser.error(str(exc))
    if args.output:
        from backend.main import save_json
        save_json(args.output,result)
    print(json.dumps({'lambda_home':args.home_rate,'lambda_away':args.away_rate,
                      'p_0_0':result['score_matrix']['cells'][0][0],
                      'probabilities':result['probabilities'],'overall_modal_score':result['overall_modal_score'],
                      'score_pick_conditional_on_outcome':result['score_pick']},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
