"""Animated forecast graphics, with no footer or progress-bar overlay."""
from datetime import datetime
import math
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from backend.video import text_block
from backend.video_layout import social_canvas

INK, CREAM, CORAL, GREEN = '#122a30', '#f4f1e7', '#fc654c', '#c0ff69'
STYLE_VERSION = 16


def section_at(prediction, word):
    first = 0
    for section in prediction['sections']:
        last = first + len(section['text'].split())
        if word < last:
            return section['kind']
        first = last
    return 'caveat'


def badge(draw, center, team, radius=76):
    x, y = center
    r = radius
    draw.ellipse((x-r,y-r,x+r,y+r), fill='white', outline=INK, width=3)
    if team == 'Japan':
        d = r * .46
        draw.ellipse((x-d,y-d,x+d,y+d), fill='#bd2137')
    elif team == 'Brazil':
        d = r * .91
        draw.ellipse((x-d,y-d,x+d,y+d), fill='#168447')
        draw.polygon([(x,y-r*.7),(x+r*.75,y),(x,y+r*.7),(x-r*.75,y)], fill='#f5d34a')
        d = r * .36
        draw.ellipse((x-d,y-d,x+d,y+d), fill='#214e9b')
    else:
        text_block(draw,team[:3].upper(),(x-r+8,y-35,x+r-8,y+35),34,INK,max_lines=1)


def football(draw, center, radius, rotation=0):
    x,y = center
    draw.ellipse((x-radius+8,y-radius+15,x+radius+8,y+radius+15), fill='#091c22')
    draw.ellipse((x-radius,y-radius,x+radius,y+radius), fill=CREAM, outline=INK, width=5)
    points = [(x+radius*.4*math.cos(rotation+i*math.tau/5),
               y+radius*.4*math.sin(rotation+i*math.tau/5)) for i in range(5)]
    draw.polygon(points, fill=INK)
    for px,py in points:
        angle = math.atan2(py-y,px-x)
        edge = (x+radius*.92*math.cos(angle),y+radius*.92*math.sin(angle))
        draw.line(((px,py),edge), fill=INK, width=4)
        draw.ellipse((edge[0]-9,edge[1]-9,edge[0]+9,edge[1]+9), fill=INK)


def pitch(draw, box, color, width=3):
    x0,y0,x1,y1=box
    middle=(y0+y1)/2
    draw.rounded_rectangle(box, radius=12, outline=color, width=width)
    draw.line((x0,middle,x1,middle), fill=color, width=width)
    draw.ellipse(((x0+x1)/2-62,middle-62,(x0+x1)/2+62,middle+62), outline=color,width=width)
    for top in (True,False):
        y=y0 if top else y1-105
        draw.rectangle(((x0+x1)/2-105,y,(x0+x1)/2+105,y+105),outline=color,width=width)


def form_badges(draw, sequence, y, phase):
    count=len(sequence)
    start=540-(count*132-16)//2
    for i,result in enumerate(sequence):
        reveal=min(1,max(0,phase*1.6-i*.12))
        color={'W':GREEN,'D':'#d9d8c9','L':CORAL}[result]
        x=start+i*132
        draw.rounded_rectangle((x,y,x+116,y+84),radius=15,fill=color if reveal>.15 else '#29464a')
        if reveal>.15:
            text_block(draw,result,(x,y,x+116,y+84),43,INK,max_lines=1)


def draw_prediction_frame(prediction, caption, progress, *, animation=1.0,time_seconds=0):
    if prediction.get('context'):
        from backend.personal_video import draw_personal_frame
        return draw_personal_frame(prediction,caption,progress,animation,time_seconds=time_seconds)
    phase=min(1,max(0,animation))
    ease=1-(1-phase)**3
    image=Image.new('RGB',(1080,1920),CREAM)
    draw=ImageDraw.Draw(image)
    draw.polygon([(720,0),(1080,0),(1080,1920),(150,1920)],fill='#e6e9d9')
    pitch(draw,(790,60,1230,640),'#d3dac9',3)
    draw.rectangle((0,0,1080,22),fill=CORAL)
    text_block(draw,'THE PREDICTION ROOM',(72,76,1008,138),36,INK,'left',1)
    text_block(draw,prediction['competition'].upper(),(72,151,1008,202),26,INK,'left',1)
    draw.rounded_rectangle((72,228,1008,285),radius=14,fill=INK)
    text_block(draw,'FORECAST / NOT A RESULT',(94,231,986,280),25,CREAM,'left',1)
    home,away=prediction['teams']['home']['name'],prediction['teams']['away']['name']
    badge(draw,(240,407),home,94)
    badge(draw,(840,407),away,94)
    text_block(draw,'VS',(446,365,634,452),57,INK,max_lines=1)
    text_block(draw,home.upper(),(72,520,472,599),48,INK,max_lines=2)
    text_block(draw,away.upper(),(608,520,1008,599),48,INK,max_lines=2)
    kickoff=datetime.fromisoformat(prediction['kickoff']).astimezone(ZoneInfo('Asia/Singapore'))
    text_block(draw,kickoff.strftime('%d %b / %H:%M SGT').upper(),(72,602,1008,640),24,INK,max_lines=1)
    kind=section_at(prediction,caption['word_start'])
    draw.rounded_rectangle((56,676,1024,1330),radius=38,fill=INK)
    hf,af=prediction['form']['home'],prediction['form']['away']
    if kind=='hook':
        text_block(draw,'FORM VS FIREPOWER',(102,710,978,772),29,GREEN,'left',1)
        text_block(draw,'WHO WINS THIS FRIENDLY?',(102,800,675,1004),72,CREAM,'left',3)
        football(draw,(839,910+int(9*math.sin(progress*math.tau*6))),105,progress*2)
        draw.line((104,1048,976,1048),fill='#365357',width=2)
        text_block(draw,f"{hf['wins']} WINS",(100,1084,494,1175),66,GREEN,max_lines=1)
        text_block(draw,f"{af['goals_for']} GOALS",(556,1084,980,1175),66,CORAL,max_lines=1)
        text_block(draw,f"{home} / last {hf['sample_size']}",(100,1190,494,1264),26,CREAM,max_lines=2)
        text_block(draw,f"{away} / last {af['sample_size']}",(556,1190,980,1264),26,CREAM,max_lines=2)
    elif kind in ('home_form','away_form'):
        form,name=(hf,home) if kind=='home_form' else (af,away)
        text_block(draw,f"{name.upper()} / LAST {form['sample_size']}",(102,708,978,782),34,GREEN,'left',2)
        max_goals=max(hf['goals_for'],af['goals_for'],hf['goals_against'],af['goals_against'],1)
        for i,(field,label,color) in enumerate((('goals_for','GOALS FOR',GREEN),('goals_against','CONCEDED',CORAL))):
            y=816+i*150
            text_block(draw,label,(104,y,704,y+46),27,CREAM,'left',1)
            draw.rounded_rectangle((104,y+68,762,y+112),radius=14,fill='#29464a')
            end=104+int(658*form[field]/max_goals*ease)
            if end>104:
                draw.rounded_rectangle((104,y+68,end,y+112),radius=14,fill=color)
            text_block(draw,str(form[field]),(794,y+16,972,y+128),88,color,max_lines=1)
        form_badges(draw,form['sequence'],1172,phase)
        text_block(draw,'RECENT RESULTS / NEWEST FIRST',(104,1270,976,1311),22,CREAM,max_lines=1)
    elif kind in ('lineup_home', 'lineup_away'):
        side = kind.removeprefix('lineup_')
        name = prediction['teams'][side]['name']
        text_block(draw,f'{name.upper()} / CONFIRMED XI',(100,704,980,770),31,GREEN,'left',1)
        for index, player in enumerate(prediction['lineups'][side]['starters']):
            y = 793 + index * 45
            jersey = str(player['jersey_number']) if type(player['jersey_number']) is int else '·'
            text_block(draw,jersey,(102,y,174,y+42),25,CORAL,max_lines=1)
            text_block(draw,player['name'],(192,y,976,y+42),27,CREAM,'left',1)
    elif kind=='pick':
        text_block(draw,'MY SCORE PREDICTION',(102,714,978,786),36,GREEN,max_lines=1)
        pitch(draw,(124,825,956,1192),'#27494b',3)
        score=prediction['forecast']['score_pick']
        offset=int(35*(1-ease))
        text_block(draw,str(score['home']),(108-offset,884,460-offset,1114),196,CREAM,max_lines=1)
        text_block(draw,'—',(460,922,620,1080),75,CORAL,max_lines=1)
        text_block(draw,str(score['away']),(620+offset,884,972+offset,1114),196,CREAM,max_lines=1)
        text_block(draw,'EXPLORATORY MODEL / NOT CALIBRATED',(102,1230,978,1296),25,GREEN,max_lines=1)
    else:
        text_block(draw,'WHAT COULD CHANGE IT?',(102,714,978,786),34,GREEN,'left',1)
        for i,(name,color) in enumerate((('LINEUPS',CREAM),('ROTATION',GREEN),('OPPONENT STRENGTH',CORAL))):
            y=825+i*145
            draw.ellipse((108,y+14,166,y+72),outline=color,width=4)
            if i==0:
                draw.ellipse((128,y+25,146,y+43),fill=color)
                draw.arc((120,y+43,154,y+67),180,360,fill=color,width=4)
            elif i==1:
                draw.arc((119,y+25,155,y+62),30,320,fill=color,width=4)
            else:
                draw.polygon([(137,y+26),(151,y+55),(123,y+55)],outline=color,width=3)
            text_block(draw,name,(198,y-1,974,y+89),45,color,'left',2)
        text_block(draw,'A PREDICTION. NEVER A PROMISE.',(102,1250,978,1300),26,CREAM,max_lines=1)
    draw.rounded_rectangle((56,1392,1024,1655),radius=30,fill=CORAL)
    text_block(draw,caption['text'],(104,1418,976,1625),59,INK,max_lines=3)
    # No footer text or progress bar: leave platform controls clear.
    return social_canvas(image)
