"""Local match workflow UI, served on loopback with CSRF-protected actions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlparse
import uuid

from dotenv import load_dotenv

from backend.main import ROOT, save_json
from backend.lineups import LineupsNotReady, confirmed_lineups
from backend.prematch import PrematchClient
from backend.workflow import find_matches, lineup_fixture, run_workflow


class JobStore:
    def __init__(self,out):
        self.out=Path(out).resolve()
        self.jobs={}
        self.lock=threading.Lock()
        self.executor=ThreadPoolExecutor(max_workers=1)

    def update(self,job_id,**fields):
        with self.lock:
            self.jobs[job_id].update(fields)
            record=dict(self.jobs[job_id])
        folder=self.out/'workflow_jobs'
        folder.mkdir(parents=True,exist_ok=True)
        save_json(folder/f'{job_id}.json',record)

    def submit(self,fixture_id,upload):
        with self.lock:
            for job in self.jobs.values():
                if job['fixture_id']==fixture_id and job['state'] in ('queued','running'):
                    return job['id']
            job_id=uuid.uuid4().hex
            self.jobs[job_id]={'id':job_id,'fixture_id':fixture_id,'state':'queued','message':'Queued',
                               'upload':upload,'created_at':datetime.now(timezone.utc).isoformat()}
        self.executor.submit(self.work,job_id)
        return job_id

    def work(self,job_id):
        job=self.jobs[job_id]
        try:
            self.update(job_id,state='running',message='Starting')
            result=run_workflow(job['fixture_id'],out=self.out,upload=job['upload'],
                                report=lambda message:self.update(job_id,message=message))
            self.update(job_id,state='complete',message='Ready',result=result)
        except LineupsNotReady as exc:
            self.update(job_id,state='waiting',message=str(exc))
        except Exception as exc:
            from backend.prediction import PredictionError
            from backend.sportmonks import SportmonksError
            from backend.youtube_auth import YouTubeError
            from backend.speech import SpeechError
            from backend.captions import CaptionError
            from backend.video import VideoError
            from backend.research import ResearchError
            from backend.editorial import EditorialError
            from backend.player_media import MediaError
            safe=(PredictionError,SportmonksError,YouTubeError,SpeechError,CaptionError,VideoError,ResearchError,MediaError,EditorialError)
            self.update(job_id,state='failed',message=str(exc) if isinstance(exc,safe) else 'The workflow could not finish. Check setup and retry.')


HTML='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Football Shorts Factory</title><style>
:root{font-family:Arial,sans-serif;color:#142d32;background:#f4f1e7}*{box-sizing:border-box}body{margin:0;border-top:8px solid #fc654c}main{max-width:940px;margin:55px auto;padding:0 24px 60px}.eyebrow{font-size:12px;letter-spacing:2px;font-weight:bold;color:#6b7973}h1{font-size:46px;letter-spacing:-2px;margin:16px 0}p{line-height:1.6;color:#52635d}.pill{background:#dfeecb;border-radius:30px;padding:9px 15px;font-size:12px;display:inline-block}section{background:white;border:1px solid #dde2d8;border-radius:20px;padding:26px;margin-top:25px}label{display:block;font-weight:bold;margin-bottom:12px}input,select{font:inherit;padding:15px;border:1px solid #cbd4c9;border-radius:10px;width:100%;background:#fff}button{font:inherit;font-weight:bold;background:#142d32;color:white;padding:15px 20px;border:0;border-radius:10px;cursor:pointer}button:disabled{opacity:.45;cursor:default}.row{display:flex;gap:12px}.row input{flex:1}.row button{flex:none}.muted{font-size:13px;color:#6b7973}h2{font-size:20px;margin-top:0}.hidden{display:none}#message{padding:18px;background:#e9eee2;border-radius:12px;line-height:1.6;margin-top:18px}.teams{display:grid;grid-template-columns:1fr 1fr;gap:20px}li{font-size:14px;line-height:1.7}.primary{background:#fc654c;color:#142d32;width:100%;margin-top:20px}video{width:100%;max-height:640px;background:#142d32;border-radius:12px}a{color:#254f41}.steps{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;margin:25px 0}.steps span{background:#e5e8dc;padding:10px 14px;border-radius:30px}@media(max-width:600px){h1{font-size:35px}.row{flex-direction:column}.teams{grid-template-columns:1fr}main{margin-top:30px}}
</style><main><div class="eyebrow">FOOTBALL SHORTS FACTORY</div><h1>Your match. Your next Short.</h1><p>Select a match from your subscribed competitions in the final hour before kickoff. Once the official starting elevens are confirmed, create the video and upload it privately.</p><div class="pill">Private YouTube uploads · All subscribed competitions</div><div class="steps"><span>Match facts + confirmed XI</span><span>Prediction + narration</span><span>Animated video</span><span>Private upload</span></div>
<section><h2>0. Matches starting soon</h2><div class="row"><select id="hours" aria-label="Hours ahead"><option value="1">Next 1 hour</option><option value="2" selected>Next 2 hours</option><option value="6">Next 6 hours</option><option value="24">Next 24 hours</option></select><button id="soonButton">Pull available matches</button></div></section><section><h2>1. Find your match</h2><form id="searchForm"><label for="query">Teams or fixture ID</label><div class="row"><input id="query" placeholder="Japan vs Brazil" maxlength="120" required><button id="searchButton">Find match</button></div></form><p class="muted">Search a team, both teams, or a Sportmonks fixture ID. Times are shown in Singapore time.</p><div id="choice" class="hidden"><label for="matches">Choose the fixture</label><select id="matches"></select><button id="checkButton" class="primary">Check official lineups</button></div></section>
<section id="details" class="hidden"><h2>2. Confirmed team sheets</h2><p id="kickoff"></p><div class="teams" id="teams"></div><button id="createButton" class="primary" disabled>Create video & upload privately</button><button id="localButton" class="primary" disabled>Create video only</button><p class="muted">Uses your existing API accounts. Narration and caption requests may incur API charges. The forecast considers confirmed lineups, available player ratings, venue context and sourced internet research. It remains experimental.</p></section>
<div id="message" class="hidden" role="status" aria-live="polite"></div><section id="result" class="hidden"><h2>Your video is ready</h2><video id="video" controls></video><p id="uploadLink"></p><p class="muted">Review in YouTube Studio before making anything public. YouTube may still be processing a newly uploaded video.</p></section></main>
<script nonce="__TOKEN__">
const token='__TOKEN__';let fixtureId=null;const $=id=>document.getElementById(id);function message(t){$('message').textContent=t;$('message').classList.remove('hidden')}async function api(path,options={}){const r=await fetch(path,options);const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed.');return d}function disable(v){$('createButton').disabled=v;$('localButton').disabled=v}
$('searchForm').addEventListener('submit',async e=>{e.preventDefault();$('searchButton').disabled=true;disable(true);$('details').classList.add('hidden');$('result').classList.add('hidden');try{message('Finding upcoming matches…');const d=await api('/api/search?q='+encodeURIComponent($('query').value));$('matches').replaceChildren();for(const m of d.matches){const o=document.createElement('option');o.value=m.id;o.textContent=m.name+' · '+new Date(m.kickoff).toLocaleString('en-SG',{timeZone:'Asia/Singapore'})+' SGT';$('matches').appendChild(o)}$('choice').classList.toggle('hidden',!d.matches.length);message(d.matches.length?'Choose the match, then check its team sheets.':'No matching upcoming matches were found in the next 21 days.')}catch(e){message(e.message)}finally{$('searchButton').disabled=false}});
$('soonButton').addEventListener('click',async()=>{try{message('Checking the next kickoff window…');const d=await api('/api/available?hours='+$('hours').value);$('matches').replaceChildren();for(const m of d.matches){const o=document.createElement('option');o.value=m.fixture_id;o.textContent=m.home+' vs '+m.away+' · '+m.kickoff_singapore;$('matches').appendChild(o)}$('choice').classList.toggle('hidden',!d.matches.length);message(d.matches.length?'Choose a match from the list below.':'No upcoming matches in this window.')}catch(e){message(e.message)}});
$('matches').addEventListener('change',()=>{fixtureId=null;disable(true);$('details').classList.add('hidden')});
$('checkButton').addEventListener('click',async()=>{disable(true);$('checkButton').disabled=true;try{const d=await api('/api/check?fixture='+$('matches').value);fixtureId=d.fixture_id;$('details').classList.remove('hidden');$('kickoff').textContent=d.name+' · '+new Date(d.kickoff).toLocaleString('en-SG',{timeZone:'Asia/Singapore'})+' SGT';$('teams').replaceChildren();if(d.ready){for(const side of ['home','away']){const box=document.createElement('div'),h=document.createElement('h3'),ul=document.createElement('ul');h.textContent=d.teams[side].name;for(const p of d.lineups[side].starters){const li=document.createElement('li');li.textContent=(Number.isInteger(p.jersey_number)?p.jersey_number+' · ':'')+p.name;ul.appendChild(li)}box.append(h,ul);$('teams').appendChild(box)}disable(false)}message(d.message)}catch(e){message(e.message)}finally{$('checkButton').disabled=false}});
async function create(upload){disable(true);try{const job=await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify({fixture_id:fixtureId,upload})});let done=false;while(!done){const d=await api('/api/jobs/'+job.id);message(d.message);if(d.state==='complete'){$('video').src='/api/jobs/'+job.id+'/video';$('result').classList.remove('hidden');$('uploadLink').replaceChildren();if(d.result.url){const a=document.createElement('a');a.href=d.result.url;a.target='_blank';a.rel='noopener';a.textContent='Open private YouTube video';$('uploadLink').appendChild(a)}done=true}else if(['waiting','failed'].includes(d.state)){done=true}else{await new Promise(r=>setTimeout(r,1500))}}}catch(e){message(e.message)}finally{disable(false)}}$('createButton').addEventListener('click',()=>create(true));$('localButton').addEventListener('click',()=>create(false));
</script></html>'''


def make_handler(store,token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def allowed(self):
            hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            origin=self.headers.get('Origin')
            return self.headers.get('Host') in hosts and (not origin or origin in {'http://'+host for host in hosts})

        def send(self,status,payload,kind='application/json'):
            data=json.dumps(payload).encode() if kind=='application/json' else payload
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',f"default-src 'self'; script-src 'nonce-{token}'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed():
                return self.send(403,{'error':'Local access only.'})
            parsed=urlparse(self.path)
            params=parse_qs(parsed.query)
            try:
                if parsed.path=='/':
                    return self.send(200,HTML.replace('__TOKEN__',token).encode(),'text/html; charset=utf-8')
                if parsed.path=='/api/available':
                    from backend.discover import available_matches
                    client=PrematchClient()
                    with client.session: result=available_matches(client,hours=int(params.get('hours',['2'])[0]))
                    return self.send(200,result)
                if parsed.path=='/api/search':
                    client=PrematchClient()
                    with client.session:
                        matches=find_matches(params.get('q',[''])[0],client)
                    return self.send(200,{'matches':matches})
                if parsed.path=='/api/check':
                    fixture_id=int(params.get('fixture',['0'])[0])
                    client=PrematchClient()
                    with client.session:
                        fixture=lineup_fixture(client,fixture_id)
                    from backend.prediction import teams_for_preview
                    from backend.prematch import kickoff_utc
                    now=datetime.now(timezone.utc)
                    teams=teams_for_preview(fixture,now,None)
                    result={'fixture_id':fixture_id,'teams':teams,'name':f"{teams['home']['name']} vs {teams['away']['name']}",
                            'kickoff':kickoff_utc(fixture).isoformat()}
                    try:
                        result.update(ready=True,lineups=confirmed_lineups(fixture,now),message='Both starting elevens are confirmed. Ready to create your video.')
                    except LineupsNotReady as exc:
                        result.update(ready=False,message=str(exc))
                    return self.send(200,result)
                parts=parsed.path.strip('/').split('/')
                if len(parts)>=3 and parts[:2]==['api','jobs']:
                    with store.lock:
                        job=dict(store.jobs.get(parts[2],{}))
                    if not job:
                        return self.send(404,{'error':'Job not found.'})
                    if len(parts)==3:
                        return self.send(200,job)
                    if len(parts)==4 and parts[3]=='video' and job['state']=='complete':
                        path=Path(job['result']['video_path']).resolve()
                        if not path.is_relative_to(store.out):
                            return self.send(403,{'error':'Unavailable video.'})
                        return self.send(200,path.read_bytes(),'video/mp4')
                return self.send(404,{'error':'Not found.'})
            except Exception as exc:
                from backend.prediction import PredictionError
                from backend.sportmonks import SportmonksError
                return self.send(400,{'error':str(exc) if isinstance(exc,(PredictionError,SportmonksError,LineupsNotReady)) else 'Unable to load this match. Check the match and local setup.'})

        def do_POST(self):
            if not self.allowed() or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),token):
                return self.send(403,{'error':'Reload the local app before starting a job.'})
            if self.path!='/api/jobs':
                return self.send(404,{'error':'Not found.'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=4096:
                    raise ValueError()
                body=json.loads(self.rfile.read(size))
                fixture_id=body.get('fixture_id')
                upload=body.get('upload',True)
                if type(fixture_id) is not int or fixture_id<=0 or type(upload) is not bool:
                    raise ValueError()
                return self.send(202,{'id':store.submit(fixture_id,upload)})
            except (ValueError,TypeError,AttributeError):
                return self.send(400,{'error':'Select a valid match first.'})
    return Handler


def main():
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(description='Open the local Football Shorts workflow.')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    store=JobStore(ROOT/'generated')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(store,secrets.token_urlsafe(32)))
    print(f'Open http://127.0.0.1:{server.server_port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.executor.shutdown(wait=False,cancel_futures=True)


if __name__=='__main__':
    main()
