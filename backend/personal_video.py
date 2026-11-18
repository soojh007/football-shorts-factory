"""Player-led first-person commentary visuals instead of a broadcast report."""
from PIL import Image,ImageDraw,ImageOps,ImageChops
import math
from backend.player_media import media_frame
from backend.video import text_block
from backend.prediction_video import pitch

from backend.presentation import palette_for


def photo(image,draw,asset,box,phase,time_seconds=0,*,palette=None):
    palette=palette or palette_for({})
    BG,WHITE,LIME=palette['bg'],palette['text'],palette['accent']
    x0,y0,x1,y1=box
    draw.rounded_rectangle((x0+9,y0+13,x1+9,y1+13),radius=25,fill=palette['shadow'])
    draw.rounded_rectangle(box,radius=25,fill=palette['surface'])
    if asset and asset.get('kind')=='team':
        pitch(draw,(x0+35,y0+80,x1-35,y1-155),palette['pitch'],3)
        text_block(draw,asset['name'],(x0+18,y1-135,x1-18,y1-18),36,WHITE,max_lines=3)
    elif asset and asset.get('kind')=='graphic':
        center=(x0+x1)//2;top=y0+75
        draw.polygon([(center-80,top),(center-145,top+45),(center-110,top+100),(center-80,top+82),(center-80,top+245),(center+80,top+245),(center+80,top+82),(center+110,top+100),(center+145,top+45),(center+80,top)],fill=palette['shirt'],outline=LIME,width=4)
        text_block(draw,str(asset.get('jersey_number') or 'XI'),(center-65,top+55,center+65,top+195),70,WHITE,max_lines=1)
        text_block(draw,asset['name'],(x0+18,y1-110,x1-18,y1-18),34,WHITE,max_lines=2)
    elif asset:
        source=media_frame(asset,time_seconds)
        if min(source.size)<300 and asset.get('kind')!='video':
            # Keep tiny provider cutouts in a deliberately smaller portrait area.
            fitted=Image.new('RGBA',(x1-x0,y1-y0),palette['surface'])
            portrait=ImageOps.contain(source,(280,min(340,y1-y0-135)),method=Image.Resampling.LANCZOS)
            fitted.alpha_composite(portrait,((fitted.width-portrait.width)//2,(fitted.height-portrait.height-100)//2))
        else:
            zoom=1+.07*(.5+.5*math.sin(time_seconds*.35)) if asset.get('kind')!='video' else 1
            wide=ImageOps.fit(source,(round((x1-x0)*zoom),round((y1-y0)*zoom)),method=Image.Resampling.LANCZOS,centering=(.5,.40))
            pan=(math.sin(time_seconds*.25)+1)/2
            left=round((wide.width-(x1-x0))*pan);top=round((wide.height-(y1-y0))*(1-pan))
            fitted=wide.crop((left,top,left+x1-x0,top+y1-y0))
        mask=Image.new('L',fitted.size,0);ImageDraw.Draw(mask).rounded_rectangle((0,0,fitted.width,fitted.height),radius=25,fill=255)
        mask=ImageChops.multiply(mask,fitted.getchannel('A'))
        image.paste(fitted,(x0,y0),mask)
        draw.rounded_rectangle((x0,y1-105,x1,y1),radius=18,fill=BG)
        text_block(draw,asset['name'],(x0+18,y1-94,x1-18,y1-12),34,WHITE,max_lines=2)


def draw_personal_frame(prediction,caption,progress,animation,*,time_seconds=0):
    from backend.prediction_video import section_at,pitch
    palette=palette_for(prediction)
    BG,WHITE,LIME,ORANGE=(palette[k] for k in ('bg','text','accent','secondary'))
    image=Image.new('RGB',(1080,1920),BG);draw=ImageDraw.Draw(image)
    draw.ellipse((-280,-440,1120,1050),fill=palette['orb'])
    draw.ellipse((480,1060,1560,2140),outline=palette['outline'],width=3)
    draw.line((60,88,1020,88),fill=LIME,width=8)
    label='DESIGN PREVIEW' if prediction.get('design_preview') else 'MY MATCHDAY TAKE'
    text_block(draw,label,(66,118,1014,182),34,LIME,'left',1)
    home,away=prediction['teams']['home']['name'],prediction['teams']['away']['name']
    text_block(draw,f'{home} × {away}',(64,205,1016,330),64,WHITE,'left',2)
    text_block(draw,'MY MATCHDAY PICK',(66,340,1014,390),25,ORANGE,'left',1)
    assets=prediction.get('media_assets') or []
    kind=section_at(prediction,caption['word_start'])
    first=0;scene_text='';scene_index=0
    for scene_index,section in enumerate(prediction['sections']):
        first+=len(section['text'].split())
        if caption['word_start']<first:
            scene_text=section['text'].casefold();break
    selected={}
    for side in ('home','away'):
        candidates=[asset for asset in assets if asset['side']==side]
        mentioned=[asset for asset in candidates if asset['name'].casefold() in scene_text]
        pool=mentioned or candidates
        selected[side]=pool[(int(time_seconds/3.5)+scene_index)%len(pool)] if pool else None
        if selected[side] is None:
            starters=prediction.get('featured_players',{}).get(side) or prediction.get('lineups',{}).get(side,{}).get('starters') or []
            if starters:
                player=starters[0]
                selected[side]={'kind':'graphic','name':player['name'],'jersey_number':player.get('jersey_number')}
            else:
                selected[side]={'kind':'team','name':prediction['teams'][side]['name']}
    offset=int(10*math.sin(progress*math.tau*2))
    if kind in ('hook','players','lineup_home','lineup_away','research'):
        action=[selected[side] for side in ('home','away') if selected[side] and selected[side].get('visual_type')=='action']
        if action and int(time_seconds/3.5)%3!=2:
            hero=action[int(time_seconds/3.5)%len(action)]
            photo(image,draw,hero,(64,430,1016,1035),animation,time_seconds,palette=palette)
        else:
            photo(image,draw,selected['home'],(64,444+offset,506,1010+offset),animation,time_seconds,palette=palette)
            photo(image,draw,selected['away'],(574,444-offset,1016,1010-offset),animation,time_seconds,palette=palette)
        if kind=='hook':
            text_block(draw,"HERE'S MY TAKE",(66,1080,1014,1210),78,LIME,'left',2)
            ranks=prediction.get('context',{}).get('fifa_rankings',{})
            if len(ranks)==2:
                label='FIFA LIVE RANK' if any(r.get('official') is False for r in ranks.values()) else 'FIFA RANK'
                text=f"{label}: #{ranks['home']['rank']} vs #{ranks['away']['rank']}\nAs of {ranks['home']['ranking_date']} / {ranks['away']['ranking_date']}"
            elif ranks:
                side,row=next(iter(ranks.items()))
                label='FIFA live' if row.get('official') is False else 'FIFA ranking'
                text=f"{label}: {prediction['teams'][side]['name']} #{row['rank']}\nAs of {row['ranking_date']}"
            else:text='The players. The matchup. My call.'
            text_block(draw,text,(66,1230,1014,1370),30,WHITE,'left',3)
        elif kind=='research':
            text_block(draw,"THE MATCHUP",(66,1074,1014,1180),67,LIME,'left',2)
            research=prediction.get('context',{}).get('web_research',{})
            claim=next((claim for claim in research.get('claims',[]) if claim['status']=='confirmed'),None)
            text_block(draw,claim['summary'] if claim else 'The detail behind my pick.',(66,1190,1014,1380),36,WHITE,'left',4)
        else:
            profiles=prediction.get('context',{}).get('lineup_profiles',{})
            for i,side in enumerate(('home','away')):
                latest=prediction.get('context',{}).get('latest_matches',{}).get(side)
                if not latest:
                    matches=prediction.get('form',{}).get(side,{}).get('matches',[])
                    latest=matches[0] if matches else None
                if latest:
                    result={'W':'BEAT','L':'LOST TO','D':'DREW WITH'}[latest['result']]
                    text=f"{result} {latest['opponent'].upper()}\n{latest['goals_for']}–{latest['goals_against']}"
                else:
                    retained=profiles.get(side,{}).get('latest_starters_retained')
                    text=f"{retained}/11 RETAINED" if retained is not None else f"{prediction['form'][side]['goals_for']} GOALS"
                text_block(draw,text,(66+i*510,1070,506+i*510,1230),38,LIME,max_lines=3)
            text_block(draw,'LATEST COMPLETED RESULTS',(66,1270,1014,1350),30,WHITE,'left',2)
    elif kind=='venue':
        venue=prediction.get('context',{}).get('venue') or {}
        pitch(draw,(130,490,950,1080),palette['pitch'],5)
        draw.ellipse((465,705,615,855),fill=ORANGE)
        draw.polygon([(488,805),(592,805),(540,930)],fill=ORANGE)
        text_block(draw,'THE GROUND MATTERS',(66,1120,1014,1230),66,LIME,'left',2)
        text_block(draw,venue.get('name') or venue.get('city') or 'Venue information unavailable',(66,1250,1014,1380),43,WHITE,'left',3)
        status='Neutral venue' if venue.get('neutral') is True else (venue.get('city') or ('Venue country checked' if venue.get('country_id') is not None else 'Venue advantage not assumed'))
        text_block(draw,status,(66,420,1014,485),31,WHITE,'left',1)
    elif kind=='pick':
        photo(image,draw,selected['home'],(64,450,506,920),animation,time_seconds,palette=palette)
        photo(image,draw,selected['away'],(574,450,1016,920),animation,time_seconds,palette=palette)
        score=prediction['forecast']['score_pick']
        text=f"{score['home']} : {score['away']}"
        text_block(draw,'MY PICK',(66,977,1014,1057),39,LIME,'left',1)
        text_block(draw,text,(64,1070,1016,1350),235,WHITE,max_lines=1)
    else:
        text_block(draw,"WHAT COULD CHANGE MY MIND?",(66,480,1014,765),91,LIME,'left',3)
        for i,text in enumerate(('LATE CHANGES','OPPONENT QUALITY','UNCERTAINTY')):
            y=830+i*168
            draw.rounded_rectangle((66,y,1014,y+122),radius=20,fill=palette['surface'])
            text_block(draw,text,(92,y+14,988,y+110),47,WHITE,'left',2)
    draw.rounded_rectangle((48,1470,1032,1750),radius=28,fill=WHITE)
    text_block(draw,caption['text'],(93,1492,987,1722),60,BG,max_lines=3)
    return image
