"""Four distinct personal takes, rotated by successfully uploaded prediction videos."""
import json
from pathlib import Path
import re

VERSION='four-personal-formats-v1'
TEMPLATES=(
    {'index':0,'name':'The direct pick','order':['verdict','players','case'],
     'instructions':'Lead with your personal verdict, without the score. Then introduce the confirmed starters you are watching. Finish the argument with the latest results and any useful FIFA/venue context. Punchy, confident fan-to-friend delivery; no stock scene-setting.'},
    {'index':1,'name':'The recent-result reaction','order':['results','players','verdict'],
     'instructions':'Start with the latest completed results and your first-person reaction to them, not with the pick. Move to the confirmed starters and the football case. Only then give your verdict, without its score. React to a defeat honestly; never invent a bounce-back record or claim a winning streak.'},
    {'index':2,'name':'The players-first take','order':['players','results','verdict'],
     'instructions':'Open in first person with the exact names of the confirmed starters that catch your eye, one from each side. Follow with each latest result, then explain your verdict and any verified FIFA strength context. Do not invent player abilities. If starters are unavailable, open with a concrete supplied team-form comparison instead, without discussing missing data.'},
    {'index':3,'name':'The matchday question','order':['question','results','players_verdict'],
     'instructions':'Open with a short football question about this matchup plus your personal reaction. Use a genuine question mark. Contrast the latest results, then bring in the named starters and state where you land. The question is a subjective match opinion, never a claim about injuries, stakes or tactics absent from evidence. Avoid the stock opening "Something has got to give".'},
)


def template_for(prediction):
    index=(prediction.get('narration_template') or {}).get('index',0)
    if type(index) is not int or not 0<=index<len(TEMPLATES):raise ValueError('Invalid narration template.')
    return TEMPLATES[index]


def choose_template(out,channel_id):
    """Encrypted upload receipts already persist across cloud runners; previews don't advance."""
    uploaded=set()
    for path in Path(out).glob('*_prediction_youtube_upload.json'):
        if not re.fullmatch(r'\d+_prediction_youtube_upload\.json',path.name):continue
        try:
            receipt=json.loads(path.read_text())
            video_id=receipt.get('video_id')
            if (receipt.get('state')=='uploaded' and receipt.get('channel_id')==channel_id
                and isinstance(video_id,str) and re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id)):
                uploaded.add(video_id)
        except (OSError,ValueError,AttributeError):continue
    count=len(uploaded)
    return {'version':VERSION,'index':count%4,'name':TEMPLATES[count%4]['name'],'successful_uploads_before_this':count}


def closing_line(prediction):
    score=prediction['forecast']['score_pick'];teams=prediction['teams']
    match=f"{teams['home']['name']} {score['home']}, {teams['away']['name']} {score['away']}"
    return (f"I'm going {match}. That's my pick.",f"I see it finishing {match}.",
            f"Put me down for {match}.",f"So my final call is {match}.")[template_for(prediction)['index']]


def latest_sentence(fact):
    verb={'W':'beat','L':'lost to','D':'drew with'}[fact['result']]
    scope=fact.get('competition') or 'this competition'
    label='friendly' if scope=='Friendly International' else f'{scope} game'
    return f"{fact['team']} {verb} {fact['opponent']}, {fact['goals_for']}–{fact['goals_against']}, in their latest {label}."


def backup_draft(prediction,packet):
    """Different openings AND evidence order, including when the AI writer needs a backup."""
    facts=packet['evidence'];score=prediction['forecast']['score_pick']
    side='home' if score['home']>score['away'] else 'away' if score['away']>score['home'] else 'draw'
    home=prediction['teams']['home']['name'];away=prediction['teams']['away']['name']
    h=prediction['form']['home'];a=prediction['form']['away'];index=template_for(prediction)['index']
    scope='friendlies' if prediction.get('league_id')==1082 else 'games in this competition'
    pick=home if side=='home' else away
    opinion=(f"I fancy {pick} to take this one. That's where I land after looking at both sides."
             if side!='draw' else f"I keep coming back to a draw here. I see {home} and {away} finishing level.")
    people={s:next((p for p in packet['players'] if p['side']==s),None) for s in ('home','away')}
    hp,ap=people['home'],people['away']
    player_ids=[hp['id'],ap['id']] if hp and ap else []
    player_keys=[f'player_{pid}' for pid in player_ids]
    names=(f"{hp['name']} starts for {home}, and {ap['name']} is in {away}'s eleven. Those are my two names to watch."
           if hp and ap else f"For me, this is about how {home} and {away} approach this contest. I want to see which side can make this matchup theirs.")
    form=(f"{home} have scored {h['goals_for']} and conceded {h['goals_against']} in their last {h['sample_size']} {scope}. "
          f"{away} have scored {a['goals_for']} and conceded {a['goals_against']} across their last {a['sample_size']}.")
    latest_keys=[f'{s}_latest' for s in ('home','away') if f'{s}_latest' in facts]
    latest=' '.join(latest_sentence(facts[key]) for key in latest_keys)
    rank_keys=[f'{s}_fifa_rank' for s in ('home','away') if f'{s}_fifa_rank' in facts]
    rank_label='live FIFA rankings' if any(facts[k].get('official') is False for k in rank_keys) else 'official FIFA rankings'
    rank=('In the '+rank_label+', '+'; '.join(f"{facts[k]['team']} are ranked {facts[k]['rank']}" for k in rank_keys)+'.') if rank_keys else ''
    def scene(kind,text,keys):return {'kind':kind,'text':text.strip(),'evidence_ids':list(dict.fromkeys(keys))}
    form_keys=['home_form','away_form'];name_keys=player_keys or form_keys
    def assemble(form_text):
        if index==0:
            hook=(f"My pick is {pick}. I like their side of this matchup, and I'm sticking with that call."
                  if side!='draw' else f"My pick is a draw. For me, neither side gets the edge in this matchup.")
            return [scene('hook',hook,['score_pick']),scene('players',names,name_keys),
                    scene('players',' '.join(filter(None,[latest,form_text,rank])),latest_keys+form_keys+rank_keys)]
        if index==1:
            return [scene('hook',"I can't brush these results aside. "+(latest or form_text),latest_keys or form_keys),
                    scene('players',names+(' '+form_text if latest else ''),name_keys+form_keys),
                    scene('players',' '.join(filter(None,[rank,opinion])),rank_keys+['score_pick'])]
        if index==2:
            hook=(f"For me, this starts with {hp['name']} in {home}'s eleven and {ap['name']} for {away}. Those names catch my eye."
                  if hp and ap else f"What catches my eye is the contrast between {home} and {away}. I want to see who can make this matchup theirs.")
            return [scene('hook',hook,name_keys),scene('players',' '.join(filter(None,[latest,form_text])),latest_keys+form_keys),
                    scene('players',' '.join(filter(None,[rank,opinion])),rank_keys+['score_pick'])]
        question=(f"Can {away if side=='home' else home} make this uncomfortable for {pick}? That's the question I'm taking into this game."
                  if side!='draw' else f"Who gets the edge, {home} or {away}? I keep coming back to how close I see this contest.")
        return [scene('hook',question,['score_pick']),scene('players',' '.join(filter(None,[latest or form_text,rank])),(latest_keys or form_keys)+rank_keys),
                scene('players',' '.join(filter(None,[names,form_text if latest else '',opinion])),name_keys+form_keys+['score_pick'])]
    sections=assemble(form)
    def total():return len((' '.join(s['text'] for s in sections)+' '+closing_line(prediction)).split())
    if total()>150:
        compact=f"In recent {scope}, {home} have scored {h['goals_for']} goals; {away} have scored {a['goals_for']}."
        sections=assemble(compact)
    if total()<95:
        record=(f" {home} have {h['wins']} wins and {h['draws']} draws in that run; "
                f"{away} have {a['wins']} wins and {a['draws']} draws. That adds to the picture behind my call.")
        sections[1]['text']+=record
        sections[1]['evidence_ids']=list(dict.fromkeys(sections[1]['evidence_ids']+form_keys))
    return {'pick_side':side,'featured_player_ids':player_ids,'sections':sections}
