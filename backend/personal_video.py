"""Player-led first-person commentary visuals instead of a broadcast report."""
from PIL import Image,ImageDraw,ImageOps,ImageChops
import math
from backend.player_media import load_player_image
from backend.video import text_block

BG,WHITE,LIME,ORANGE='#101814','#faf5e8','#c2ff67','#ff8055'


def photo(image,draw,asset,box,phase):
    x0,y0,x1,y1=box
    draw.rounded_rectangle((x0+9,y0+13,x1+9,y1+13),radius=25,fill='#050a07')
    draw.rounded_rectangle(box,radius=25,fill='#263a2c')
    if asset:
        source=load_player_image(asset['path'])
        if min(source.size)<300:
            # Keep tiny provider cutouts in a deliberately smaller portrait area.
            fitted=Image.new('RGBA',(x1-x0,y1-y0),'#263a2c')
            portrait=ImageOps.contain(source,(280,min(340,y1-y0-135)),method=Image.Resampling.LANCZOS)
            fitted.alpha_composite(portrait,((fitted.width-portrait.width)//2,(fitted.height-portrait.height-100)//2))
        else:
            fitted=ImageOps.fit(source,(x1-x0,y1-y0),method=Image.Resampling.LANCZOS,centering=(.5,.35))
        mask=Image.new('L',fitted.size,0);ImageDraw.Draw(mask).rounded_rectangle((0,0,fitted.width,fitted.height),radius=25,fill=255)
        mask=ImageChops.multiply(mask,fitted.getchannel('A'))
        image.paste(fitted,(x0,y0),mask)
        draw.rounded_rectangle((x0,y1-105,x1,y1),radius=18,fill=BG)
        text_block(draw,asset['name'],(x0+18,y1-94,x1-18,y1-12),34,WHITE,max_lines=2)


def draw_personal_frame(prediction,caption,progress,animation):
    from backend.prediction_video import section_at,pitch
    image=Image.new('RGB',(1080,1920),BG);draw=ImageDraw.Draw(image)
    draw.ellipse((-280,-440,1120,1050),fill='#193124')
    draw.ellipse((480,1060,1560,2140),outline='#294332',width=3)
    draw.line((60,88,1020,88),fill=LIME,width=8)
    label='DESIGN PREVIEW' if prediction.get('design_preview') else 'MY MATCHDAY TAKE'
    text_block(draw,label,(66,118,1014,182),34,LIME,'left',1)
    home,away=prediction['teams']['home']['name'],prediction['teams']['away']['name']
    text_block(draw,f'{home} × {away}',(64,205,1016,330),64,WHITE,'left',2)
    text_block(draw,'MY VIEW. NOT A GUARANTEE.',(66,340,1014,390),25,ORANGE,'left',1)
    assets=prediction.get('media_assets') or []
    selected={side:next((asset for asset in assets if asset['side']==side),None) for side in ('home','away')}
    kind=section_at(prediction,caption['word_start'])
    offset=int(10*math.sin(progress*math.tau*2))
    if kind in ('hook','players','lineup_home','lineup_away','research'):
        photo(image,draw,selected['home'],(64,444+offset,506,1010+offset),animation)
        photo(image,draw,selected['away'],(574,444-offset,1016,1010-offset),animation)
        if kind=='hook':
            text_block(draw,"I'M CHECKING THE XI",(66,1080,1014,1210),78,LIME,'left',2)
            text_block(draw,'Not just the badge. Not just the last score.',(66,1240,1014,1345),35,WHITE,'left',2)
        elif kind=='research':
            text_block(draw,"WHAT I'VE CHECKED",(66,1074,1014,1180),67,LIME,'left',2)
            research=prediction.get('context',{}).get('web_research',{})
            claim=next((claim for claim in research.get('claims',[]) if claim['status']=='confirmed'),None)
            text_block(draw,claim['summary'] if claim else 'No extra team news verified. No invented injury claims.',(66,1190,1014,1380),36,WHITE,'left',4)
        else:
            profiles=prediction.get('context',{}).get('lineup_profiles',{})
            for i,side in enumerate(('home','away')):
                retained=profiles.get(side,{}).get('latest_starters_retained')
                text=f"{retained}/11 RETAINED" if retained is not None else 'CONFIRMED STARTER'
                text_block(draw,text,(66+i*510,1090,506+i*510,1212),47,LIME,max_lines=2)
            text_block(draw,'Compared with the latest sampled friendly',(66,1250,1014,1330),30,WHITE,'left',2)
    elif kind=='venue':
        venue=prediction.get('context',{}).get('venue') or {}
        pitch(draw,(130,490,950,1080),'#44654a',5)
        draw.ellipse((465,705,615,855),fill=ORANGE)
        draw.polygon([(488,805),(592,805),(540,930)],fill=ORANGE)
        text_block(draw,'THE GROUND MATTERS',(66,1120,1014,1230),66,LIME,'left',2)
        text_block(draw,venue.get('name') or venue.get('city') or 'Venue information unavailable',(66,1250,1014,1380),43,WHITE,'left',3)
        status='Neutral venue' if venue.get('neutral') is True else (venue.get('city') or 'Venue country checked')
        text_block(draw,status,(66,420,1014,485),31,WHITE,'left',1)
    elif kind=='pick':
        photo(image,draw,selected['home'],(64,450,506,920),animation)
        photo(image,draw,selected['away'],(574,450,1016,920),animation)
        score=prediction['forecast']['score_pick']
        text='— : —' if prediction.get('design_preview') else f"{score['home']} : {score['away']}"
        text_block(draw,'MY PICK',(66,977,1014,1057),39,LIME,'left',1)
        text_block(draw,text,(64,1070,1016,1350),235,WHITE,max_lines=1)
    else:
        text_block(draw,"WHAT COULD CHANGE MY MIND?",(66,480,1014,765),91,LIME,'left',3)
        for i,text in enumerate(('LATE CHANGES','OPPONENT QUALITY','UNCERTAINTY')):
            y=830+i*168
            draw.rounded_rectangle((66,y,1014,y+122),radius=20,fill='#213a2a')
            text_block(draw,text,(92,y+14,988,y+110),47,WHITE,'left',2)
    draw.rounded_rectangle((48,1470,1032,1750),radius=28,fill=WHITE)
    text_block(draw,caption['text'],(93,1492,987,1722),60,BG,max_lines=3)
    return image
