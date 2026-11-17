"""Fit/evaluate a point-in-time international goals model; no current fixtures used."""
import argparse
from bisect import bisect_left
from collections import defaultdict,deque
import csv
from datetime import date,timedelta
import hashlib
import json
import math
from pathlib import Path
import unicodedata

FEATURES=['intercept','fifa_points_gap_per_600','home_soil','friendly','log_recent_goal_rate']
ALIASES={'iran':'ir iran','south korea':'korea republic','north korea':'korea dpr','united states':'usa',
         'dr congo':'congo dr','ivory coast':"cote d'ivoire",'cape verde':'cabo verde','czech republic':'czechia',
         'turkey':'turkiye','east timor':'timor-leste','saint kitts and nevis':'st. kitts and nevis',
         'saint lucia':'st. lucia','saint vincent and the grenadines':'st. vincent / grenadines',
         'curacao':'curacao','swaziland':'eswatini','china':'china pr'}


def normalized(name):
    text=unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode().lower().strip()
    return ALIASES.get(text,text)


def samples(results_path,rankings_path,*,end):
    rankings=defaultdict(dict)
    with open(rankings_path,newline='',encoding='utf-8-sig') as handle:
        for row in csv.DictReader(handle):
            stamp=date.fromisoformat(row['date'])
            if stamp<date(2018,8,16) or stamp>end:continue
            try:points=float(row['total_points'])
            except ValueError:continue
            if math.isfinite(points) and 0<points<3000:rankings[normalized(row['team'])][stamp]=points
    indexed={team:sorted(values.items()) for team,values in rankings.items()}
    dates={team:[stamp for stamp,_ in values] for team,values in indexed.items()}
    def points(team,stamp):
        key=normalized(team);index=bisect_left(dates.get(key,[]),stamp)-1
        if index<0:return None
        released,value=indexed[key][index]
        return value if (stamp-released).days<=90 else None
    with open(results_path,newline='',encoding='utf-8-sig') as handle:
        rows=sorted(csv.DictReader(handle),key=lambda row:row['date'])
    history=defaultdict(lambda:deque(maxlen=12));output=[];skipped=0
    for row in rows:
        stamp=date.fromisoformat(row['date'])
        if stamp>end:break
        if stamp<date(2017,1,1):continue
        try:hg,ag=int(row['home_score']),int(row['away_score'])
        except ValueError:continue
        if hg<0 or ag<0:continue
        home,away=normalized(row['home_team']),normalized(row['away_team']);tournament=row['tournament']
        def form(team):
            prior=[m for m in history[(team,tournament)] if stamp-timedelta(days=365)<=m[0]<stamp][-5:]
            return [(sum(m[index] for m in prior)+4.2)/(len(prior)+3) for index in (1,2)]
        hf,ha=form(home);af,aa=form(away)
        base=[(hf+aa)/2,(af+ha)/2]
        hp,ap=points(home,stamp),points(away,stamp)
        if hp is not None and ap is not None and stamp>=date(2018,8,17):
            soil=row['neutral'].upper()=='FALSE' and normalized(row['country'])==home
            friendly=tournament=='Friendly'
            diff=(hp-ap)/600
            features=[[1,diff,.5 if soil else 0,int(friendly),math.log(base[0])],
                      [1,-diff,-.5 if soil else 0,int(friendly),math.log(base[1])]]
            output.append({'date':stamp.isoformat(),'home':row['home_team'],'away':row['away_team'],
                'goals':[hg,ag],'features':features,'baseline_rates':base,'points_gap':abs(hp-ap),'friendly':friendly})
        elif stamp>=date(2018,8,17):skipped+=1
        history[(home,tournament)].append((stamp,hg,ag));history[(away,tournament)].append((stamp,ag,hg))
    return output,skipped


def dot(a,b):return sum(x*y for x,y in zip(a,b))
def rates(coef,row):return [math.exp(max(-10,min(5,dot(coef,x)))) for x in row['features']]


def objective(coef,rows):
    return sum(y*math.log(mu)-mu for row in rows for y,mu in zip(row['goals'],rates(coef,row)))


def solve(matrix,target):
    a=[list(row)+[value] for row,value in zip(matrix,target)];n=len(target)
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(a[r][col]));a[col],a[pivot]=a[pivot],a[col]
        scale=a[col][col]
        if abs(scale)<1e-12:raise ValueError('Insufficient independent calibration features.')
        a[col]=[v/scale for v in a[col]]
        for r in range(n):
            if r==col:continue
            factor=a[r][col];a[r]=[v-factor*w for v,w in zip(a[r],a[col])]
    return [row[-1] for row in a]


def fit(rows):
    if len(rows)<300:raise ValueError('At least 300 dated training fixtures are required.')
    coef=[0,0,0,0,1];n=len(coef)
    for _ in range(35):
        gradient=[0.]*n;information=[[0.]*n for _ in range(n)]
        for row in rows:
            for x,y,mu in zip(row['features'],row['goals'],rates(coef,row)):
                for i in range(n):
                    gradient[i]+=x[i]*(y-mu)
                    for j in range(n):information[i][j]+=mu*x[i]*x[j]
        for i in range(n):information[i][i]+=1e-6
        step=solve(information,gradient);old=objective(coef,rows);scale=1.
        while scale>1e-7:
            candidate=[v+scale*d for v,d in zip(coef,step)]
            candidate[1]=max(0,candidate[1]);candidate[4]=max(0,min(1,candidate[4]))
            if objective(candidate,rows)>=old-1e-9:break
            scale/=2
        if max(abs(v-w) for v,w in zip(candidate,coef))<1e-8:break
        coef=candidate
    return coef


def metrics(rows,coef=None,*,baseline=None):
    if not rows:return {'fixtures':0}
    nll=margin_error=pred_margin=actual_margin=0.
    for row in rows:
        means=rates(coef,row) if coef else row['baseline_rates']
        if baseline=='capped_fifa':
            factor=math.exp(max(-.35,min(.35,row['features'][0][1]/2)))
            means=[means[0]*factor,means[1]/factor]
        nll+=sum(mu-y*math.log(mu)+math.lgamma(y+1) for y,mu in zip(row['goals'],means))
        difference=row['goals'][0]-row['goals'][1];estimate=means[0]-means[1]
        margin_error+=abs(difference-estimate)
        sign=1 if row['features'][0][1]>=0 else -1
        pred_margin+=sign*estimate;actual_margin+=sign*difference
    return {'fixtures':len(rows),'goal_nll_per_fixture':nll/len(rows),'goal_difference_mae':margin_error/len(rows),
            'mean_stronger_team_predicted_margin':pred_margin/len(rows),'mean_stronger_team_actual_margin':actual_margin/len(rows)}


def train(results_path,rankings_path,*,split='2023-01-01',end='2024-09-19'):
    rows,skipped=samples(results_path,rankings_path,end=date.fromisoformat(end))
    training=[r for r in rows if r['date']<split];holdout=[r for r in rows if r['date']>=split]
    if len(holdout)<100:raise ValueError('At least 100 later holdout fixtures are required.')
    coef=fit(training)
    groups={'all':holdout,'friendlies':[r for r in holdout if r['friendly']],
            'large_gap_500_plus':[r for r in holdout if r['points_gap']>=500],
            'close_gap_under_100':[r for r in holdout if r['points_gap']<100]}
    comparisons={name:{'recent_form':metrics(group),'capped_fifa':metrics(group,baseline='capped_fifa'),'strength_model':metrics(group,coef)} for name,group in groups.items()}
    passed=(comparisons['all']['strength_model']['goal_nll_per_fixture']<comparisons['all']['capped_fifa']['goal_nll_per_fixture']
        and comparisons['large_gap_500_plus']['strength_model'].get('fixtures',0)>=30
        and comparisons['large_gap_500_plus']['strength_model']['goal_nll_per_fixture']<comparisons['large_gap_500_plus']['capped_fifa']['goal_nll_per_fixture'])
    return {'schema_version':1,'model':'fifa-strength-poisson-v1','features':FEATURES,'coefficients':coef,
        'train_start':min(r['date'] for r in training),'train_end':max(r['date'] for r in training),
        'holdout_start':split,'evaluated_through':end,'training_fixtures':len(training),'excluded_missing_ranks':skipped,
        'points_gap_training_range':[min(r['features'][0][1] for r in training),max(r['features'][0][1] for r in training)],
        'validation_passed':passed,'validation':comparisons,
        'source_sha256':{Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (results_path,rankings_path)},
        'sources':['https://github.com/martj42/international_results','https://github.com/Dato-Futbol/fifa-ranking'],
        'limitations':['Retrospective chronological holdout, not prospective validation.','FIFA points, not ordinal rank gaps, measure relative strength.',
                       'Historical ratings are the last release strictly before each match; maximum age 90 days.',
                       'Training and holdout end before 2026; Singapore–Brazil 2026 is not included.',
                       'Runtime lineup-rating factors are heuristic overlays, not fitted individual-player effects.']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--results',required=True);p.add_argument('--rankings',required=True)
    p.add_argument('--output',required=True);p.add_argument('--split',default='2023-01-01');p.add_argument('--end',default='2024-09-19')
    a=p.parse_args();model=train(a.results,a.rankings,split=a.split,end=a.end)
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(model,indent=2)+'\n')
    print(json.dumps({k:model[k] for k in ('coefficients','training_fixtures','validation_passed','validation')},indent=2))
    if not model['validation_passed']:raise SystemExit('Strength model did not improve on its held-out baseline.')


if __name__=='__main__':main()
