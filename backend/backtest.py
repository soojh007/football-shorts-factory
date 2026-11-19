"""Frozen-round retrospective evaluation; no speech, research or upload calls."""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
import math
from pathlib import Path

from backend.league_poisson import LOOKBACK_DAYS,MODEL_VERSION,league_rates,score_matrix
from backend.main import save_json
from backend.prediction import PredictionError,make_prediction
from backend.prematch import PrematchClient,kickoff_utc
from backend.validate import validate_fixture


def prematch_fixture(fixture):
    """Whitelist model inputs: discard scores, events, lineups and winner flags."""
    return {'id':fixture['id'],'league_id':fixture['league_id'],'season_id':fixture['season_id'],
            'starting_at':kickoff_utc(fixture).isoformat(),'state_id':1,'state':{'id':1},
            'participants':[{'id':p['id'],'name':p['name'],'type':p.get('type'),
                'meta':{'location':p['meta']['location']}} for p in fixture['participants']]}


def outcome(home,away):
    return 'home' if home>away else 'away' if away>home else 'draw'


def evaluate_round(targets,history,*,expected_matches=10):
    if len(targets)!=expected_matches or len({f['id'] for f in targets})!=expected_matches:
        raise PredictionError('Round is incomplete or has duplicate targets; no selective backtest reported.')
    identities={(f['league_id'],f['season_id'],f.get('round_id')) for f in targets}
    if len(identities)!=1:raise PredictionError('Targets must belong to one league, season and round.')
    targets=sorted(targets,key=lambda f:(kickoff_utc(f),f['id']))
    cutoff=kickoff_utc(targets[0])-timedelta(seconds=1)
    target_ids={f['id'] for f in targets}
    # Freeze the entire holdout round: not even Friday's result trains Sunday's picks.
    training=[f for f in history if f.get('id') not in target_ids and kickoff_utc(f)<cutoff]
    results=[]
    for target in targets:
        if target.get('state_id')!=5:raise PredictionError('All target matches must have valid regulation-time FT results.')
        teams,actual,_=validate_fixture(target,target['league_id'])
        clean=prematch_fixture(target)
        rates,detail=league_rates(clean,training,cutoff)
        if rates is None:raise PredictionError('League baseline unavailable for the frozen holdout: '+detail['reason'])
        models={MODEL_VERSION:score_matrix(*rates)}
        averages=detail['league_goal_averages']
        models['league_averages_only']=score_matrix(averages['home'],averages['away'])
        legacy=make_prediction(clean,{'home':training,'away':training},as_of=cutoff,league_id=target['league_id'],min_matches=1)['forecast']
        models['legacy_recent_form']=score_matrix(legacy['model_goal_rates']['home'],legacy['model_goal_rates']['away'])
        model_rates={MODEL_VERSION:dict(zip(('home','away'),rates)),
                     'league_averages_only':averages,'legacy_recent_form':legacy['model_goal_rates']}
        predictions={}
        actual_outcome=outcome(actual.home,actual.away)
        for name,forecast in models.items():
            pick=forecast['score_pick'];prob=forecast['probabilities'];lam=model_rates[name]
            # Direct log PMF avoids a score outside the retained grid being scored as zero.
            score_nll=sum(lam[s]-g*math.log(max(lam[s],1e-15))+math.lgamma(g+1)
                          for s,g in [('home',actual.home),('away',actual.away)])
            predictions[name]={'score_pick':pick,'overall_modal_score':forecast['overall_modal_score'],
                'goal_rates':lam,'probabilities':prob,'outcome':forecast['outcome'],
                'correct_outcome':forecast['outcome']==actual_outcome,
                'exact_score':pick=={'home':actual.home,'away':actual.away},
                'exact_overall_mode':forecast['overall_modal_score']=={'home':actual.home,'away':actual.away},
                'score_pick_mae_per_team':(abs(pick['home']-actual.home)+abs(pick['away']-actual.away))/2,
                'expected_goals_mae_per_team':(abs(lam['home']-actual.home)+abs(lam['away']-actual.away))/2,
                'brier_score':sum((prob[k]-(1 if k==actual_outcome else 0))**2 for k in ('home','draw','away')),
                'outcome_log_loss':-math.log(max(prob[actual_outcome],1e-15)),
                'scoreline_log_loss':score_nll}
        results.append({'fixture_id':target['id'],'kickoff':kickoff_utc(target).isoformat(),
                        'home':teams['home'].name,'away':teams['away'].name,
                        'actual':{'home':actual.home,'away':actual.away},'actual_outcome':actual_outcome,
                        'league_sample_size':detail['sample_size'],'training_fixture_ids':detail['fixture_ids'],
                        'team_samples':detail['teams'],'predictions':predictions})
    metrics={}
    for name in results[0]['predictions']:
        values=[r['predictions'][name] for r in results]
        metrics[name]={'matches':len(values),'outcomes_correct':sum(v['correct_outcome'] for v in values),
                       'exact_scores':sum(v['exact_score'] for v in values),
                       'exact_overall_modes':sum(v['exact_overall_mode'] for v in values)}
        for field in ('score_pick_mae_per_team','expected_goals_mae_per_team','brier_score','outcome_log_loss','scoreline_log_loss'):
            metrics[name][field]=sum(v[field] for v in values)/len(values)
    league,season,round_id=next(iter(identities))
    return {'model_version':MODEL_VERSION,'competition':(targets[0].get('league') or {}).get('name') or f'League {league}',
            'round_number':(targets[0].get('round') or {}).get('name') or str(round_id),'league_id':league,'season_id':season,'round_id':round_id,
            'training_cutoff':cutoff.isoformat(),'holdout_fixture_ids':sorted(target_ids),
            'protocol':'Frozen before first round kickoff; all round targets excluded from training; no lineup/rating/research overlays.',
            'not_original_prekickoff_forecasts':True,'calibration_established':False,
            'metrics':metrics,'matches':results}


def fetch_snapshot(client,league_id,round_number,start,end,season_id=None):
    if start>end or (end-start).days>99:raise PredictionError('Round discovery window must be 1–100 days.')
    fixtures=[]
    for page in range(1,201):
        payload=client.fixture_request(f'between/{start.isoformat()}/{end.isoformat()}',
            includes='participants;scores;state;league;round',league_id=league_id,page=page)
        rows=payload.get('data')
        if not isinstance(rows,list):raise PredictionError('Round discovery returned invalid fixtures.')
        fixtures.extend(rows)
        if not (payload.get('pagination') or {}).get('has_more'):break
        if not rows or page==200:raise PredictionError('Round discovery pagination incomplete.')
    targets=[f for f in fixtures if str((f.get('round') or {}).get('name'))==str(round_number)
             and (season_id is None or f.get('season_id')==season_id)]
    if not targets:raise PredictionError('No fixtures found for the selected round.')
    cutoff=min(kickoff_utc(f) for f in targets)-timedelta(seconds=1)
    history=[];day=cutoff.date()-timedelta(days=LOOKBACK_DAYS)
    while day<=cutoff.date():
        last=min(day+timedelta(days=99),cutoff.date())
        history.extend(client.fixture_window(day,last,league_id=league_id))
        day=last+timedelta(days=1)
    return {'retrieved_at':datetime.now(timezone.utc).isoformat(),'source':'Sportmonks Football API v3',
            'league_id':league_id,'round_number':round_number,'targets':targets,'history':history}


def markdown_report(report):
    lines=[f"# {report['competition']}: round {report['round_number']} retrospective backtest",'',
           f"Season ID: {report['season_id']}.",'',
           f"Training frozen at **{report['training_cutoff']}**.",
           report['protocol'],'',
           'These are reconstructed model outputs, not archived pre-match predictions. No parameters were tuned on this round.',
           f"Current API results may contain later corrections. {len(report['matches'])} games do not establish calibration.",'',
           '| Match | Model pick | Actual | Correct outcome | Home / draw / away |',
           '|---|---:|---:|:---:|---:|']
    for row in report['matches']:
        p=row['predictions'][MODEL_VERSION];pick=p['score_pick'];a=row['actual'];q=p['probabilities']
        lines.append(f"| {row['home']} vs {row['away']} | {pick['home']}–{pick['away']} | {a['home']}–{a['away']} | {'Yes' if p['correct_outcome'] else 'No'} | {q['home']:.1%} / {q['draw']:.1%} / {q['away']:.1%} |")
    lines+=['','| Model | W/D/L correct | Exact score | Score MAE/team | Brier ↓ | Outcome log loss ↓ | Scoreline log loss ↓ |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for name,m in report['metrics'].items():
        lines.append(f"| {name} | {m['outcomes_correct']}/{m['matches']} | {m['exact_scores']}/{m['matches']} | {m['score_pick_mae_per_team']:.3f} | {m['brier_score']:.3f} | {m['outcome_log_loss']:.3f} | {m['scoreline_log_loss']:.3f} |")
    lines+=['','Brier is the sum of squared errors across the three outcome probabilities (range 0–2). Log losses use natural logarithms.',
            'Exact score uses the score selected conditional on the most likely outcome; the overall modal score is retained separately in JSON.',
            'League-averages-only uses the same frozen league baseline without team strengths. Legacy uses the previous five-match recent-form model.',
            f"Source: {report.get('source','Sportmonks Football API v3')}; snapshot retrieved {report.get('retrieved_at','unknown')}.",
            f"Input snapshot SHA-256: `{report.get('input_sha256','unknown')}`.",'']
    return '\n'.join(lines)


def main(argv=None):
    from dotenv import load_dotenv
    from backend.main import ROOT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,help='Replay a saved snapshot without network or credentials.')
    parser.add_argument('--league',type=int,default=8)
    parser.add_argument('--round',type=int,default=10)
    parser.add_argument('--season-id',type=int)
    parser.add_argument('--date-from',type=datetime.fromisoformat,default=datetime(2026,11,1))
    parser.add_argument('--date-to',type=datetime.fromisoformat,default=datetime(2026,11,15))
    parser.add_argument('--expected-matches',type=int,default=10)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    load_dotenv(ROOT/'.env')
    if args.input:snapshot=json.loads(args.input.read_text())
    else:
        client=PrematchClient()
        with client.session:snapshot=fetch_snapshot(client,args.league,args.round,args.date_from.date(),args.date_to.date(),args.season_id)
    report=evaluate_round(snapshot['targets'],snapshot['history'],expected_matches=args.expected_matches)
    args.output.mkdir(parents=True,exist_ok=True)
    save_json(args.output/'input.json',snapshot)
    raw=(args.output/'input.json').read_bytes()
    report.update(source=snapshot['source'],retrieved_at=snapshot['retrieved_at'],input_sha256=hashlib.sha256(raw).hexdigest())
    save_json(args.output/'results.json',report)
    import csv
    with (args.output/'matches.csv').open('w',newline='') as handle:
        writer=csv.writer(handle)
        writer.writerow(['fixture_id','home','away','predicted_home','predicted_away','actual_home','actual_away','correct_outcome','home_probability','draw_probability','away_probability'])
        for row in report['matches']:
            p=row['predictions'][MODEL_VERSION]
            writer.writerow([row['fixture_id'],row['home'],row['away'],p['score_pick']['home'],p['score_pick']['away'],row['actual']['home'],row['actual']['away'],p['correct_outcome'],*[p['probabilities'][k] for k in ('home','draw','away')]])
    (args.output/'report.md').write_text(markdown_report(report))
    print(markdown_report(report))
    return 0


if __name__=='__main__':raise SystemExit(main())
