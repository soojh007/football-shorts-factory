"""Distinct editorial graphics for forecasts, never presented as final scores."""
from PIL import Image, ImageDraw
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.video import text_block

INK, CREAM, CORAL, GREEN = '#122a30', '#f4f1e7', '#fc654c', '#c0ff69'


def section_at(prediction, word):
    first = 0
    for section in prediction['sections']:
        last = first + len(section['text'].split())
        if word < last:
            return section['kind']
        first = last
    return 'caveat'


def badge(draw, center, team):
    x,y = center
    draw.ellipse((x-76,y-76,x+76,y+76),fill='white',outline=INK,width=3)
    if team == 'Japan':
        draw.ellipse((x-35,y-35,x+35,y+35),fill='#bd2137')
    elif team == 'Brazil':
        draw.ellipse((x-69,y-69,x+69,y+69),fill='#168447')
        draw.polygon([(x,y-53),(x+57,y),(x,y+53),(x-57,y)],fill='#f5d34a')
        draw.ellipse((x-27,y-27,x+27,y+27),fill='#214e9b')
    else:
        text_block(draw,team[:3].upper(),(x-62,y-35,x+62,y+35),34,INK,max_lines=1)


def draw_prediction_frame(prediction, caption, progress):
    image=Image.new('RGB',(1080,1920),CREAM)
    draw=ImageDraw.Draw(image)
    draw.polygon([(690,0),(1080,0),(1080,1090),(280,1530)],fill='#e8e8d8')
    draw.rectangle((0,0,1080,30),fill=CORAL)
    text_block(draw,'THE PREDICTION ROOM',(74,96,1006,165),39,INK,'left',1)
    text_block(draw,prediction['competition'].upper(),(74,180,1006,230),27,INK,'left',1)
    text_block(draw,'FORECAST / NOT A RESULT',(74,252,1006,300),25,CORAL,'left',1)
    home,away=prediction['teams']['home']['name'],prediction['teams']['away']['name']
    badge(draw,(240,410),home)
    badge(draw,(840,410),away)
    text_block(draw,'VS',(440,362,640,456),55,INK,max_lines=1)
    text_block(draw,home.upper(),(72,506,472,595),49,INK,max_lines=2)
    text_block(draw,away.upper(),(608,506,1008,595),49,INK,max_lines=2)
    kickoff=datetime.fromisoformat(prediction['kickoff']).astimezone(ZoneInfo('Asia/Singapore'))
    text_block(draw,kickoff.strftime('%d %b %Y / %H:%M SGT').upper(),(72,600,1008,638),24,INK,max_lines=1)
    kind=section_at(prediction,caption['word_start'])
    draw.rounded_rectangle((72,650,1008,1200),radius=36,fill=INK)
    hf,af=prediction['form']['home'],prediction['form']['away']
    if kind=='hook':
        text_block(draw,'FORM VS FIREPOWER',(118,702,962,768),29,GREEN,max_lines=1)
        text_block(draw,'WHO WINS\nTHIS FRIENDLY?',(118,812,962,1050),90,CREAM,max_lines=3)
        text_block(draw,'Evidence first. Then the score pick.',(118,1090,962,1144),28,CREAM,max_lines=2)
    elif kind in ('home_form','away_form'):
        form,name=(hf,home) if kind=='home_form' else (af,away)
        text_block(draw,f'{name.upper()} / LAST {form["sample_size"]}',(118,690,962,763),32,GREEN,max_lines=2)
        text_block(draw,str(form['goals_for']),(118,786,515,950),136,CREAM,max_lines=1)
        text_block(draw,str(form['goals_against']),(565,786,962,950),136,CORAL,max_lines=1)
        text_block(draw,'GOALS FOR',(118,955,515,1015),27,CREAM,max_lines=1)
        text_block(draw,'CONCEDED',(565,955,962,1015),27,CREAM,max_lines=1)
        colors={'W':GREEN,'D':'#d9d8c9','L':CORAL}
        count=len(form['sequence'])
        start=540-(count*118-14)//2
        for i,result in enumerate(form['sequence']):
            x=start+i*118
            draw.rounded_rectangle((x,1066,x+104,1140),radius=12,fill=colors[result])
            text_block(draw,result,(x,1066,x+104,1140),37,INK,max_lines=1)
    elif kind=='pick':
        pick=prediction['forecast']['score_pick']
        text_block(draw,'MY SCORE PICK',(118,700,962,770),37,GREEN,max_lines=1)
        text_block(draw,f'{pick["home"]} — {pick["away"]}',(118,810,962,1022),166,CREAM,max_lines=1)
        text_block(draw,'Exploratory form model / not calibrated',(118,1082,962,1145),28,CREAM,max_lines=2)
    else:
        text_block(draw,'WHAT COULD CHANGE IT?',(118,700,962,770),32,GREEN,max_lines=1)
        text_block(draw,'LINEUPS.\nROTATION.\nUNCERTAINTY.',(118,804,962,1070),75,CREAM,max_lines=3)
        text_block(draw,'Opponent strength is not adjusted.',(118,1090,962,1150),27,CREAM,max_lines=2)
    draw.rounded_rectangle((72,1280,1008,1525),radius=26,fill=CORAL)
    text_block(draw,caption['text'],(114,1302,966,1498),57,INK,max_lines=3)
    draw.rectangle((72,1590,1008,1600),fill='#d4d8cd')
    draw.rectangle((72,1590,72+int(936*progress),1600),fill=INK)
    text_block(draw,'AI VOICE / SPECULATIVE PREDICTION',(72,1640,1008,1692),26,INK,'left',1)
    text_block(draw,'Source: Sportmonks match results / recent friendlies',(72,1700,1008,1750),22,INK,'left',2)
    return image
