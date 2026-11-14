"""GitHub Actions entry point. No credentials, private scripts or video URLs in logs."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

from backend.cloud_receipts import CloudStateError,pack_receipts,restore_latest
from backend.lineups import LineupsNotReady,confirmed_lineups
from backend.main import ROOT
from backend.prematch import PrematchClient
from backend.workflow import find_matches,lineup_fixture,run_workflow
from backend.youtube import current_channel
from backend.youtube_auth import save_token,load_credentials,youtube_service


def summary(title,message):
    path=os.getenv('GITHUB_STEP_SUMMARY')
    if path:
        with open(path,'a',encoding='utf-8') as handle:
            handle.write(f'## {title}\n\n{message}\n\n')


def prepare():
    required=('SPORTMONKS_API_TOKEN','OPENAI_API_KEY','YOUTUBE_OAUTH_TOKEN_JSON','YOUTUBE_CHANNEL_ID')
    if any(not os.getenv(key,'').strip() for key in required):
        raise CloudStateError('Required GitHub Actions secrets/channel configuration are missing.')
    secret=os.environ['YOUTUBE_OAUTH_TOKEN_JSON']
    try:
        value=json.loads(secret)
        if any(not value.get(key) for key in ('refresh_token','client_id','client_secret')):
            raise ValueError()
    except (ValueError,AttributeError):
        raise CloudStateError('The encrypted YouTube OAuth secret is incomplete; reconnect your channel locally first.') from None
    save_token(ROOT/'secrets'/'youtube_token.json',secret)
    restored=restore_latest(ROOT/'generated',secret)
    print(f'Cloud credentials prepared. Prior upload records restored: {restored}.',flush=True)
    output=os.getenv('GITHUB_OUTPUT')
    if output:
        with open(output,'a') as handle:
            handle.write('state_ready=true\n')


def run():
    from backend.video import require_tools
    require_tools()
    # Verify refresh/channel access even for a validation-only smoke run.
    service=youtube_service(load_credentials())
    try:
        channel=current_channel(service)
    finally:
        service.close()
    if channel['id']!=os.environ.get('YOUTUBE_CHANNEL_ID'):
        raise CloudStateError('The authorized YouTube channel does not match the configured channel.')
    client=PrematchClient()
    with client.session:
        matches=find_matches(os.getenv('MATCH_INPUT',''),client)
        if len(matches)!=1:
            if not matches:
                raise CloudStateError('No matching upcoming international friendly found. Use a Sportmonks fixture ID or both team names.')
            options=', '.join(f"{match['id']} ({match['name']})" for match in matches[:8])
            raise CloudStateError(f'Multiple fixtures match. Run again using a fixture ID: {options}')
        fixture_id=matches[0]['id']
        fixture=lineup_fixture(client,fixture_id)
    try:
        confirmed_lineups(fixture,datetime.now(timezone.utc))
    except LineupsNotReady as exc:
        print(f'Waiting: {exc}',flush=True)
        summary('Waiting — no video or upload created',str(exc)+' Run the workflow again in the final hour once official starting elevens are confirmed.')
        return
    if os.getenv('CLOUD_VALIDATE_ONLY','false').lower()=='true':
        print('Cloud account, match and confirmed-lineup checks passed. Validation only; no paid generation or upload.',flush=True)
        summary('Validation passed — no upload','The cloud account, match and confirmed lineup checks passed. Disable validation-only mode when you want to create and privately upload the video.')
        return
    run_workflow(fixture_id,upload=True)
    # Public repository logs/summaries intentionally omit the private video URL.
    summary('Private upload accepted','The video was uploaded privately. Open [YouTube Studio](https://studio.youtube.com/) to review processing and playback. Nothing was made public.')


def export():
    folder=ROOT/'.factory-state'
    folder.mkdir(exist_ok=True)
    (folder/'receipts.enc').write_bytes(pack_receipts(ROOT/'generated',os.environ['YOUTUBE_OAUTH_TOKEN_JSON']))
    print('Encrypted upload-state archive prepared; no media or OAuth files are included.',flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('prepare','run','export'))
    args=parser.parse_args(argv)
    try:
        {'prepare':prepare,'run':run,'export':export}[args.command]()
        return 0
    except Exception as exc:
        from backend.prediction import PredictionError
        from backend.sportmonks import SportmonksError
        from backend.youtube_auth import YouTubeError
        from backend.speech import SpeechError
        from backend.captions import CaptionError
        from backend.video import VideoError
        safe=(CloudStateError,PredictionError,SportmonksError,YouTubeError,SpeechError,CaptionError,VideoError)
        message=str(exc) if isinstance(exc,safe) else 'Cloud workflow could not finish. Check setup and YouTube Studio before retrying an uncertain upload.'
        print(message,file=sys.stderr)
        summary('Workflow stopped',message)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
