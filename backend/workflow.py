"""One-match workflow: official XIs → forecast → video → private YouTube upload."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import unicodedata

from dotenv import load_dotenv

from backend.analyze import save_text
from backend.lineups import LineupsNotReady, add_lineup_sections, confirmed_lineups, available_lineups
from backend.contextual_prediction import contextual_prediction,venue_context,venue_changed
from backend.research import ResearchClient
from backend.editorial import EditorialClient,EditorialError
from backend.player_media import collect_player_media
from backend.main import ROOT, positive_int, save_json
from backend.predict import collect, render_prediction,prediction_duration
from backend.prediction import PredictionError, make_prediction, prediction_content_hash, teams_for_preview
from backend.prediction_video import STYLE_VERSION
from backend.prematch import PrematchClient, kickoff_utc
from backend.speech import DISCLOSURE, sha256, wav_metadata
from backend.video import probe_video, require_tools
from backend.youtube import CHANNEL_PATTERN, current_channel, existing_upload, upload_video
from backend.youtube_auth import YouTubeError, load_credentials, youtube_service

def fixture_league_id(fixture):
    league_id=fixture.get('league_id')
    if type(league_id) is not int or league_id<=0:
        raise PredictionError('Fixture competition identity is missing.')
    return league_id


def lineup_fixture(client, fixture_id):
    payload = client.fixture_request(str(fixture_id), includes='participants;state;league;lineups.type;lineups.player;metadata.type;formations;venue')
    fixture = payload.get('data')
    if not isinstance(fixture, dict) or fixture.get('id') != fixture_id:
        raise PredictionError('The requested fixture is unavailable.')
    return fixture


def find_matches(query, client, now=None):
    now = now or datetime.now(timezone.utc)
    query = query.strip()
    if not query or len(query) > 120:
        raise PredictionError('Enter a team, a match, or a fixture ID.')
    if query.isdecimal():
        fixtures = [client.upcoming_fixture(int(query))['data']]
        words = []
    else:
        fixtures = client.fixture_window(now.date(), (now + timedelta(days=21)).date(), league_id=None)
        cleaned = unicodedata.normalize('NFKD', query).encode('ascii', 'ignore').decode().lower()
        words = [word for word in re.findall(r'[a-z0-9]+', cleaned) if word not in ('v','vs','versus')]
        if not words:
            raise PredictionError('Enter at least one team name.')
    matches = []
    for fixture in fixtures:
        try:
            teams = teams_for_preview(fixture, now, None)
        except (ValueError, TypeError, AttributeError):
            continue
        name = f"{teams['home']['name']} vs {teams['away']['name']}"
        normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
        if all(word in normalized for word in words):
            matches.append({'id': fixture['id'], 'name': name, 'kickoff': kickoff_utc(fixture).isoformat(), 'league_id':fixture['league_id'], 'competition':(fixture.get('league') or {}).get('name') or f"Competition {fixture['league_id']}"})
    return sorted(matches, key=lambda item: item['kickoff'])


def prediction_upload_body(prediction):
    h,a = prediction['teams']['home']['name'],prediction['teams']['away']['name']
    score=prediction['forecast']['score_pick']
    title=f'{h} vs {a} prediction | {prediction["kickoff"][:10]}'
    competition=prediction.get('competition') or f"Competition {prediction['league_id']}"
    description=(f"{competition} prediction: {h} {score['home']}–{score['away']} {a}.\n" +
        ('Both official starting elevens were confirmed when this video was created.\n\n' if prediction.get('lineups',{}).get('confirmed') else 'Confirmed starting elevens were unavailable; this prediction uses other available information.\n\n') +
        f"{prediction['script']}\n\n{DISCLOSURE}\n"
        'Outcome probabilities are not calibrated prospectively. FIFA-points strength coefficients are fitted and chronologically tested; lineup overlays and missing-data fallbacks remain experimental.\n'
        'Match facts and lineups: Sportmonks.\n\n#Shorts #Football #Prediction')
    research=(prediction.get('context') or {}).get('web_research') or {}
    rank_urls=[row[key] for row in research.get('fifa_rankings',[]) for key in ('source_url','release_source_url')]
    urls=list(dict.fromkeys(rank_urls+[claim['source_url'] for claim in research.get('claims',[])]))[:5]
    credits=[f"{asset['name']}: {asset.get('title','Player action media')} / {asset.get('artist','')} / {asset.get('license','')} {asset.get('license_url','')} / {asset.get('source_url','')} (cropped/animated; clips excerpted and muted)" for asset in prediction.get('media_assets',[])]
    if urls: description+='\n\nResearch sources:\n'+'\n'.join(urls)
    if any(asset.get('license')=='CC BY-SA 4.0' for asset in prediction.get('media_assets',[])):
        description+='\n\nThis video adaptation is licensed under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/ . Original works retain their credited licences. Changes: cropped, animated, captions and narration added.'
    if credits: description+='\n\nPlayer photo/video credits:\n'+'\n'.join(credits)
    if not title or len(title)>100 or any(char in title+description for char in '<>') or len(description.encode())>5000:
        raise YouTubeError('The generated upload metadata exceeds YouTube limits; review the match names.')
    return {'snippet':{'title':title,'description':description,'categoryId':'17','defaultLanguage':'en',
                       'tags':['football',competition[:80],'prediction','Shorts']},
            'status':{'privacyStatus':'private','selfDeclaredMadeForKids':False,'containsSyntheticMedia':True}}


def reusable_video(prediction, out):
    prefix=f"{prediction['fixture_id']}_prediction"
    try:
        metadata=json.loads((out/f'{prefix}_render.json').read_text())
        audio=(out/f'{prefix}_narration.wav').read_bytes()
        video=out/f'{prefix}.mp4'
        if (metadata.get('prediction_sha256') != prediction_content_hash(prediction)
                or metadata.get('style_version') != STYLE_VERSION
                or metadata.get('video_sha256') != sha256(video.read_bytes())
                or metadata.get('script_sha256') != sha256(prediction['script'].encode())
                or metadata.get('audio_sha256') != sha256(audio)):
            return False
        probe_video(video,prediction_duration(wav_metadata(audio)['duration_seconds']))
        return True
    except (OSError,ValueError,KeyError,TypeError):
        return False



def enrich_history(source,now):
    base=make_prediction(source['fixture'],source['histories'],as_of=now,league_id=fixture_league_id(source['fixture']),min_matches=1)
    needed={m['fixture_id'] for form in base['form'].values() for m in form['matches']}
    enriched={}
    client=PrematchClient()
    with client.session:
        for match_id in needed:
            data=client.fixture_request(str(match_id),includes='participants;scores;state;lineups.details.type;venue;metadata.type').get('data')
            if not isinstance(data,dict) or data.get('id')!=match_id:
                raise PredictionError('Historical lineup facts are missing or mismatched.')
            enriched[match_id]=data
    source['histories']={side:[enriched.get(match['id'],match) for match in rows] for side,rows in source['histories'].items()}
    return source

def _run_workflow(fixture_id, *, out=None, upload=True, report=None):
    out=Path(out or ROOT/'generated').resolve()
    out.mkdir(parents=True,exist_ok=True)
    report=report or (lambda message: print(message,flush=True))
    require_tools()
    report('Checking kickoff and available starting elevens')
    client=PrematchClient()
    with client.session:
        fixture=lineup_fixture(client,fixture_id)
        now=datetime.now(timezone.utc)
        league_id=fixture_league_id(fixture)
        lineups=available_lineups(fixture,now,league_id)
        # Fail before paid generation if upload authorization is unavailable.
        if upload:
            report('Checking your connected YouTube channel')
            channel_id=os.getenv('YOUTUBE_CHANNEL_ID','')
            if not CHANNEL_PATTERN.fullmatch(channel_id):
                raise YouTubeError('Configure the intended YouTube channel before uploading.')
            service=youtube_service(load_credentials())
            try:
                if current_channel(service)['id']!=channel_id:
                    raise YouTubeError('The connected YouTube channel does not match the configured channel.')
            finally:
                service.close()
        report('Retrieving recent results in the selected competition')
        source=collect(client,fixture_id,league_id,now,fixture=fixture)
        report('Checking historical lineups, player ratings and venue context')
        source=enrich_history(source,now)
    # Validate data sufficiency before paying for web research.
    contextual_prediction(source['fixture'],source['histories'],lineups,now,league_id=league_id)
    from backend.freshness import latest_completed
    from backend.prediction import teams_for_preview
    report('Checking latest completed matches across accessible competitions')
    client=PrematchClient()
    with client.session:
        latest=latest_completed(client,teams_for_preview(source['fixture'],now,league_id),now)
    source['latest_matches']=latest
    from backend.fifa_rankings import fetch_rankings
    report('Reading available FIFA rankings from the official table')
    fifa=fetch_rankings(source['fixture'])
    report('Researching official announcements and credible reports on the internet')
    researcher=ResearchClient()
    with researcher.session:
        research=researcher.brief({**source['fixture'],'recent_results':latest})
        national=[p for p in source['fixture'].get('participants',[]) if p.get('type')=='national' and p.get('gender')=='male']
        if not fifa and len(national)==2 and len(research.get('fifa_rankings',[]))<2:
            report('Looking up the official FIFA ranking release and national-team entries')
            ranking_brief=researcher.brief(source['fixture'],ranking_only=True)
            merged={row['team_id']:row for row in research.get('fifa_rankings',[])}
            for row in ranking_brief.get('fifa_rankings',[]):
                if row['team_id'] not in merged or row['ranking_date']>=merged[row['team_id']]['ranking_date']:merged[row['team_id']]=row
            research['fifa_rankings']=list(merged.values())
            research['sources'].extend(ranking_brief.get('sources',[]))
    if fifa:research['fifa_rankings']=fifa
    report(f"Verified FIFA rankings available: {len(research.get('fifa_rankings',[]))}")
    research['provider_latest']=latest
    # Timestamp the forecast after source retrieval, and recheck that kickoff is still in the future.
    forecast_at=datetime.now(timezone.utc)
    prediction=contextual_prediction(source['fixture'],source['histories'],lineups,forecast_at,league_id=league_id,research=research)
    save_json(out/f'{fixture_id}_web_research.json',research)
    report('Writing a personal football take with the editorial agent')
    editor=EditorialClient()
    with editor.session:
        prediction=editor.write(prediction)
    editorial=prediction.get('editorial') or {}
    for diagnostic in editorial.get('attempt_diagnostics',[]):
        report(f"Narration attempt {diagnostic['attempt']}: {diagnostic['code']}")
    if editorial.get('mode')=='grounded_backup':
        report('AI draft did not pass checks; using an evidence-checked personal backup narration')
    else:
        report('Personal narration and factual review passed')
    report('Preparing real player visuals and first-person narration')
    prediction['media_assets']=collect_player_media(prediction,out)
    counts={kind:sum(asset.get('kind','image')==kind for asset in prediction['media_assets']) for kind in ('video','image')}
    report(f"Player media ready: {counts['video']} clips, {counts['image']} photos")
    if not 75<=prediction['word_count']<=150:
        raise PredictionError('The narration is outside the video word budget; review the team names.')
    report('Preparing the prediction with available match evidence')
    save_json(out/f'{fixture_id}_prediction_source.json',source)
    save_json(out/f'{fixture_id}_prediction.json',prediction)
    save_text(out/f'{fixture_id}_prediction_script.txt',prediction['script'])
    if reusable_video(prediction,out):
        report('Reusing the matching finished video')
    else:
        report('Creating narration, captions and animated video')
        render_prediction(prediction,out)
    video_path=out/f'{fixture_id}_prediction.mp4'
    result={'fixture_id':fixture_id,'video_path':str(video_path),'uploaded':False}
    if upload:
        report('Rechecking kickoff and available lineups before the private upload')
        client=PrematchClient()
        with client.session:
            current=lineup_fixture(client,fixture_id)
        latest=available_lineups(current,datetime.now(timezone.utc),league_id)
        # Player substitutions or rescheduling during production require a refresh.
        for side in ('home','away'):
            if lineups.get('confirmed') and latest.get('confirmed') and latest[side]!=lineups[side]:
                raise LineupsNotReady('The official lineup changed during production. Run again to rebuild the video before upload.')
        if venue_changed((prediction.get('context') or {}).get('venue',{}),venue_context(current,prediction['teams']['home']['id'])):
            raise LineupsNotReady('The venue changed during production. Run again before uploading.')
        if kickoff_utc(current)!=kickoff_utc(fixture):
            raise LineupsNotReady('Kickoff changed during production. Run again with the updated schedule.')
        body=prediction_upload_body(prediction)
        receipt_path=out/f'{fixture_id}_prediction_youtube_upload.json'
        expected={'channel_id':channel_id,'video_sha256':sha256(video_path.read_bytes()),'body':body}
        receipt=existing_upload(receipt_path,expected)
        reused=receipt is not None
        if not reused:
            report('Uploading privately to YouTube')
            service=youtube_service(load_credentials())
            try:
                receipt,reused=upload_video(service,video_path,body,channel_id,expected['video_sha256'],receipt_path)
            finally:
                service.close()
        result.update(uploaded=True,url=receipt['url'],upload_reused=reused,
                      requested_privacy='private',returned_privacy=receipt.get('returned_privacy'))
        report('Private upload accepted. YouTube may still be processing it.')
    else:
        report('Video ready. No upload requested.')
    save_json(out/f'{fixture_id}_workflow_result.json',result)
    return result



def run_workflow(fixture_id, *, out=None, upload=True, report=None):
    if type(fixture_id) is not int or fixture_id <= 0:
        raise PredictionError('Select a valid fixture ID.')
    directory = Path(out or ROOT/'generated').resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory/f'.{fixture_id}_workflow.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise PredictionError('This match already has a workflow running. Wait for it to finish before trying again.') from None
    try:
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(str(os.getpid()))
        return _run_workflow(fixture_id, out=directory, upload=upload, report=report)
    finally:
        lock.unlink(missing_ok=True)

def main(argv=None):
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(description='Create and privately upload a match prediction with confirmed lineups.')
    parser.add_argument('--fixture',type=positive_int,required=True)
    parser.add_argument('--no-upload',action='store_true',help='Create the video locally only')
    args=parser.parse_args(argv)
    try:
        result=run_workflow(args.fixture,upload=not args.no_upload)
        print(result.get('url') or result['video_path'])
        return 0
    except LineupsNotReady as exc:
        print(str(exc),file=sys.stderr)
        return 2
    except Exception as exc:
        # Only show known safe domain messages; never arbitrary credential errors.
        from backend.sportmonks import SportmonksError
        from backend.speech import SpeechError
        from backend.captions import CaptionError
        from backend.video import VideoError
        from backend.research import ResearchError
        from backend.player_media import MediaError
        safe=(PredictionError,YouTubeError,SportmonksError,SpeechError,CaptionError,VideoError,ResearchError,MediaError,EditorialError)
        print(str(exc) if isinstance(exc,safe) else 'The workflow could not finish. Check the local setup and retry.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
