"""Public schedule discovery: no keys or private predictions in the published JSON."""
import argparse
from datetime import datetime,timedelta,timezone
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from backend.main import ROOT,save_json
from backend.prematch import PrematchClient,kickoff_utc
from backend.prediction import teams_for_preview


def available_matches(client,*,hours=2,now=None):
    if hours not in (1,2): raise ValueError('Choose a one- or two-hour window.')
    now=now or datetime.now(timezone.utc)
    end=now+timedelta(hours=hours)
    fixtures=client.fixture_window(now.date(),end.date(),league_id=1082)
    matches=[]
    for fixture in fixtures:
        try:
            teams=teams_for_preview(fixture,now,1082)
            kickoff=kickoff_utc(fixture)
        except (ValueError,TypeError,AttributeError): continue
        if kickoff>end: continue
        matches.append({'fixture_id':fixture['id'],'home':teams['home']['name'],'away':teams['away']['name'],
                        'kickoff':kickoff.isoformat(),'kickoff_singapore':kickoff.astimezone(ZoneInfo('Asia/Singapore')).strftime('%d %b %H:%M SGT'),
                        'minutes_to_kickoff':round((kickoff-now).total_seconds()/60),
                        'lineups_status':'not_checked','creation_window_open':kickoff<=now+timedelta(hours=1)})
    return {'schema_version':1,'fetched_at':now.isoformat(),'window_hours':hours,'competition_id':1082,
            'matches':sorted(matches,key=lambda m:m['kickoff'])}


def main(argv=None):
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser()
    parser.add_argument('--hours',type=int,choices=(1,2),default=2)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    client=PrematchClient()
    with client.session: result=available_matches(client,hours=args.hours)
    if args.output: save_json(args.output,result)
    lines=[f"## Friendlies in the next {args.hours} hours",'',f"Updated {result['fetched_at']}",'',
           '| Match | Singapore kickoff | Fixture ID |','|---|---|---|']
    for match in result['matches']:
        lines.append(f"| {match['home']} vs {match['away']} | {match['kickoff_singapore']} | {match['fixture_id']} |")
    if not result['matches']: lines.append('No upcoming fixtures in this window.')
    lines.append('\nOfficial starting elevens are checked separately before generation. Enter the fixture ID in Create prediction video.')
    text='\n'.join(lines)
    print(text)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as handle: handle.write(text+'\n')
    return 0


if __name__=='__main__': raise SystemExit(main())
