"""Latest accessible completed matches, separate from competition-specific form."""
from datetime import timedelta

from backend.prematch import kickoff_utc
from backend.validate import validate_fixture,FixtureValidationError


def latest_completed(client,teams,cutoff):
    latest={}
    for side,team in teams.items():
        rows=client.fixture_window(cutoff.date()-timedelta(days=90),cutoff.date(),
                                   team_id=team['id'],league_id=None)
        candidates=[]
        for row in rows:
            if row.get('state_id') not in (5,7,8):continue
            try:
                played=kickoff_utc(row)
                if played>=cutoff:continue
                mapped,score,_=validate_fixture(row,row.get('league_id'))
                own=next((key for key,value in mapped.items() if value.id==team['id']),None)
                if own is None:continue
                other='away' if own=='home' else 'home'
                gf,ga=getattr(score,own),getattr(score,other)
                candidates.append({'fixture_id':row['id'],'kickoff':played.isoformat(),
                    'opponent':mapped[other].name,'goals_for':gf,'goals_against':ga,
                    'result':'W' if gf>ga else 'L' if gf<ga else 'D',
                    'competition':(row.get('league') or {}).get('name') or f"competition {row['league_id']}",
                    'source':'Sportmonks','checked_at':cutoff.isoformat()})
            except (FixtureValidationError,ValueError,TypeError):continue
        if candidates:latest[side]=max(candidates,key=lambda item:item['kickoff'])
    return latest
