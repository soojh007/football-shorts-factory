"""Historically fitted national-team goal rates; optional when evidence is missing."""
from datetime import date,datetime,timedelta
from functools import lru_cache
import json
import math
from pathlib import Path

MODEL_PATH=Path(__file__).parent/'models'/'fifa_strength_v1.json'


@lru_cache(maxsize=1)
def load_model():
    return json.loads(MODEL_PATH.read_text())


def strength_rates(rankings,fixture,as_of,home_form_rate,away_form_rate,venue_role):
    """Return no adjustment for missing/incompatible/future evidence."""
    reason='matching_fifa_points_unavailable'
    if set(rankings)!={'home','away'}:return None,{'applied':False,'reason':reason}
    if len(fixture.get('participants',[]))!=2 or any(p.get('type')!='national' or p.get('gender')!='male' for p in fixture.get('participants',[])):
        return None,{'applied':False,'reason':'not_senior_mens_national_teams'}
    h,a=rankings['home'],rankings['away']
    try:
        if type(h.get('official')) is not bool or h['official']!=a.get('official') or h['ranking_date']!=a['ranking_date']:raise ValueError()
        released=date.fromisoformat(h['ranking_date'])
        if not as_of.date()-timedelta(days=90)<=released<=as_of.date():raise ValueError()
        for row in (h,a):
            if row.get('retrieved_at') and datetime.fromisoformat(row['retrieved_at'].replace('Z','+00:00'))>as_of:raise ValueError()
            if type(row.get('points')) not in (float,int) or not math.isfinite(row['points']) or not 0<row['points']<=3000:raise ValueError()
        model=load_model()
        if model.get('validation_passed') is not True or date.fromisoformat(model['evaluated_through'])>=as_of.date():
            return None,{'applied':False,'reason':'strength_model_not_available_before_cutoff'}
        difference=(h['points']-a['points'])/600
        low,high=model['points_gap_training_range']
        limit=min(abs(low),abs(high))
        used_gap=max(-limit,min(limit,difference))
        home_soil=.5 if venue_role=='own_country' else -.5 if venue_role=='opponent_country' else 0.
        friendly=int(fixture.get('league_id')==1082 or (fixture.get('league') or {}).get('sub_type')=='friendly')
        features=[[1,used_gap,home_soil,friendly,math.log(home_form_rate)],
                  [1,-used_gap,-home_soil,friendly,math.log(away_form_rate)]]
        rates=[math.exp(sum(v*c for v,c in zip(x,model['coefficients']))) for x in features]
        if any(not math.isfinite(value) or value<=0 for value in rates):raise ValueError()
        return rates,{'applied':True,'model':model['model'],'fitted':True,'prospectively_validated':False,
            'points_gap':h['points']-a['points'],'points_gap_clipped_to_training_domain':used_gap!=difference,
            'features':model['features'],'coefficients':model['coefficients'],
            'training_fixtures':model['training_fixtures'],'evaluated_through':model['evaluated_through'],
            'validation_artifact':'backend/models/fifa_strength_v1.json',
            'venue_factors':{'home':math.exp(model['coefficients'][2]*home_soil),'away':math.exp(-model['coefficients'][2]*home_soil)}}
    except (ValueError,TypeError,KeyError,OSError,OverflowError):
        return None,{'applied':False,'reason':'invalid_or_incompatible_strength_evidence'}
