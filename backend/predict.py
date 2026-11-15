"""Collect pre-match facts, forecast and optionally make a private local video."""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import tempfile

from dotenv import load_dotenv

from backend.analyze import save_text
from backend.captions import CaptionError,TranscriptionClient,align_captions,srt_text
from backend.main import ROOT,positive_int,save_json
from backend.narrate import save_audio
from backend.prediction import PredictionError,make_prediction,teams_for_preview,prediction_content_hash
from backend.prediction_video import STYLE_VERSION,draw_prediction_frame,section_at
from backend.prematch import PrematchClient
from backend.render import load_words
from backend.speech import SpeechClient,SpeechError,sha256,wav_metadata
from backend.sportmonks import SportmonksError
from backend.video import VideoError,require_tools,encode_video,probe_video


def collect(client,fixture_id,league_id,as_of,fixture=None):
    fixture=fixture if fixture is not None else client.upcoming_fixture(fixture_id)['data']
    teams=teams_for_preview(fixture,as_of,league_id)
    if league_id is None: league_id=fixture['league_id']
    if set(teams)!={'home','away'}:
        raise PredictionError('Missing pre-match teams.')
    histories={}
    for side,team in teams.items():
        rows=[]
        start=as_of.date()-timedelta(days=365)
        while start<=as_of.date():
            end=min(start+timedelta(days=99),as_of.date())
            rows.extend(client.fixture_window(start,end,team_id=team['id'],league_id=league_id))
            start=end+timedelta(days=1)
        histories[side]=rows
    return {'fixture':fixture,'histories':histories,'as_of':as_of.isoformat()}


def render_prediction(prediction,out):
    require_tools()
    prefix=f"{prediction['fixture_id']}_prediction"
    audio_path=out/f'{prefix}_narration.wav'
    audio_metadata=out/f'{prefix}_narration.json'
    settings={'script_sha256':sha256(prediction['script'].encode()),'model':'gpt-4o-mini-tts','voice':'coral','speed':1.1}
    if prediction.get('context'):
        settings['delivery']='personal-analyst-v4'
        settings['speed']=1.0
        settings['instructions']='Read the script exactly. Sound like a thoughtful football fan giving my own take to one friend: conversational, warm, with natural emphasis and pauses. Do not use a newsreader or broadcast-announcer voice. Do not add words.'
    audio=None
    if audio_path.exists() and audio_metadata.exists():
        cached=json.loads(audio_metadata.read_text())
        if all(cached.get(k)==v for k,v in settings.items()):
            candidate=audio_path.read_bytes()
            if sha256(candidate)==cached.get('audio_sha256'):
                wav_metadata(candidate)
                audio=candidate
    if audio is None:
        print('Generating prediction narration...',flush=True)
        client=SpeechClient(model=settings['model'],voice=settings['voice'],speed=settings['speed'],instructions=settings.get('instructions'))
        with client.session:
            audio=client.generate(prediction['script'])
        save_audio(audio_path,audio)
        save_json(audio_metadata,{**settings,**wav_metadata(audio),'audio_sha256':sha256(audio)})
    measured=wav_metadata(audio)
    if not measured['within_target_duration']:
        raise PredictionError('Prediction narration is outside 30–60 seconds; review script or delivery before rendering.')
    expected={'audio_sha256':sha256(audio),'script_sha256':settings['script_sha256'],'model':'whisper-1'}
    cache_path=out/f'{prefix}_captions.json'
    words=load_words(cache_path,expected)
    if words is None:
        print('Aligning prediction captions...',flush=True)
        client=TranscriptionClient()
        with client.session:
            words=client.transcribe(audio_path)
    aligned=align_captions(prediction['script'],words,measured['duration_seconds'])
    save_json(cache_path,{**expected,'words':words,**aligned})
    with tempfile.TemporaryDirectory(prefix='.prediction-',dir=out) as folder:
        workdir=Path(folder)
        frames=[]
        captions=aligned['captions']
        # Render original graphic motion at 8 fps; FFmpeg outputs CFR at 30 fps.
        # Include every caption boundary so words remain synchronized.
        duration=measured['duration_seconds']
        ticks={0.0,duration}
        ticks.update(min(duration,index/8) for index in range(int(duration*8)+1))
        ticks.update(caption['start'] for caption in captions)
        ticks.update(caption['end'] for caption in captions)
        ticks=sorted(ticks)
        # Remove sub-frame intervals: they cannot be represented in a 30fps MP4.
        ticks=sorted({round(time*30)/30 for time in ticks if time<duration}|{duration})
        scenes=[]
        caption_index=0
        section_start=0.0
        previous_kind=None
        for i,(start,end) in enumerate(zip(ticks,ticks[1:])):
            if end-start<0.015:
                continue
            while caption_index+1<len(captions) and captions[caption_index+1]['start']<=start+1/60:
                caption_index+=1
            caption=captions[caption_index]
            kind=section_at(prediction,caption['word_start'])
            if kind!=previous_kind:
                section_start=start
                previous_kind=kind
            path=workdir/f'frame_{i:04}.png'
            draw_prediction_frame(prediction,caption,start/duration,
                                  animation=min(1,(start-section_start)/0.85)).save(path)
            frames.append(path)
            scenes.append({'start':start,'end':end})
        staged=workdir/'video.mp4'
        encode_video(frames,scenes,audio_path,staged,measured['duration_seconds'],workdir)
        verification=probe_video(staged,measured['duration_seconds'])
        staged.replace(out/f'{prefix}.mp4')
        frames[0].replace(out/f'{prefix}_poster.png')
    save_text(out/f'{prefix}_captions.srt',srt_text(aligned['captions']))
    save_json(out/f'{prefix}_render.json',{'content_type':'prediction','fixture_id':prediction['fixture_id'],
        'league_id':prediction['league_id'],'as_of':prediction['as_of'],
        'style_version':STYLE_VERSION,'graphics_motion_fps':8,'footer_visible':False,
        'prediction_sha256':prediction_content_hash(prediction),'script_sha256':settings['script_sha256'],
        'audio_sha256':sha256(audio),
        'video_sha256':sha256((out/f'{prefix}.mp4').read_bytes()),'alignment_coverage':aligned['alignment_coverage'],
        'forecast_model':prediction['forecast']['model'],'calibrated':False,'requires_editorial_review':True,**verification})
    return verification


def main(argv=None):
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(description='Create an exploratory prediction from recent competition results.')
    parser.add_argument('--fixture',required=True,type=positive_int)
    parser.add_argument('--league-id',type=positive_int,default=None,help='Optional competition check; defaults to the fixture competition')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'generated')
    parser.add_argument('--reuse-source',action='store_true',help='Reuse saved match facts; still reject a fixture that has already started')
    parser.add_argument('--render',action='store_true',help='Generate speech, aligned captions and local MP4; makes paid OpenAI calls if uncached')
    args=parser.parse_args(argv)
    try:
        out=args.output_dir.resolve()
        out.mkdir(parents=True,exist_ok=True)
        source_path=out/f'{args.fixture}_prediction_source.json'
        now=datetime.now(timezone.utc)
        if args.reuse_source:
            source=json.loads(source_path.read_text())
            if source['fixture'].get('id')!=args.fixture:
                raise PredictionError('Saved source fixture ID does not match requested fixture.')
            # Current check rejects stale previews after kickoff; the evidence cutoff
            # remains the original retrieval time, avoiding post-cutoff match leakage.
            teams_for_preview(source['fixture'],now,args.league_id)
            cutoff=datetime.fromisoformat(source['as_of'])
            if cutoff>now:
                raise PredictionError('Saved evidence cutoff is in the future.')
        else:
            client=PrematchClient()
            with client.session:
                source=collect(client,args.fixture,args.league_id,now)
            cutoff=now
        prediction=make_prediction(source['fixture'],source['histories'],as_of=cutoff,league_id=args.league_id if args.league_id is not None else source['fixture']['league_id'])
        if not 75<=prediction['word_count']<=150:
            raise PredictionError('Prediction narration must contain 75–150 words.')
        save_json(source_path,source)
        save_json(out/f'{args.fixture}_prediction.json',prediction)
        save_text(out/f'{args.fixture}_prediction_script.txt',prediction['script'])
        print(prediction['title'],flush=True)
        print('Exploratory recent-form forecast; not calibrated. No paid Predictions add-on used.',flush=True)
        if args.render:
            video=render_prediction(prediction,out)
            print(f"Saved {out/f'{args.fixture}_prediction.mp4'} ({video['duration_seconds']:.2f}s)")
        print('No upload performed. Review the draft before using it.')
    except (PredictionError,SportmonksError,SpeechError,CaptionError,VideoError) as exc:
        print(f'Error: {exc}',file=sys.stderr)
        return 1
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        print('Error: Invalid prediction source or unable to save output.',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
