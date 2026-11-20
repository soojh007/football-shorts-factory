"""One-time local GitHub App manifest handshake. Never prints/stores credentials."""
import argparse
import base64
import html
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs,urlparse

import requests


def app_manifest(origin,callback):
    return {'name':'Soo Football Shorts Dashboard','url':origin,
            'description':'Owner-only sign-in and private video workflow launcher for football-shorts-factory.',
            'hook_attributes':{'url':origin+'/webhooks/github','active':False},
            'redirect_url':callback,'callback_urls':[origin+'/auth/callback'],
            'setup_url':origin+'/','public':False,
            'default_permissions':{'actions':'write','metadata':'read'},
            'default_events':[],'request_oauth_on_install':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--port',type=int,default=8977)
    args=parser.parse_args()
    u=urlparse(args.origin)
    if u.scheme!='https' or not u.netloc or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:
        parser.error('Use the deployed dashboard HTTPS origin.')
    origin=args.origin.rstrip('/')
    state=secrets.token_urlsafe(32)
    manifest=app_manifest(origin,f'http://127.0.0.1:{args.port}/callback')
    memory={};lock=threading.Lock();deadline=time.monotonic()+3600
    root=Path(__file__).resolve().parents[1]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass  # Callback URLs contain one-use codes.
        def send(self,text,status=200):
            body=text.encode();self.send_response(status)
            for k,v in {'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action https://github.com; base-uri 'none'; frame-ancestors 'none'",'Content-Length':str(len(body))}.items():self.send_header(k,v)
            self.end_headers();self.wfile.write(body)
        def configure(self):
            if not memory.get('credentials'):return self.send('<h1>No pending setup</h1>',409)
            result=subprocess.run(['npx','--yes','wrangler@4','secret','bulk','--config','auth-worker/wrangler.jsonc'],cwd=root,input=json.dumps(memory['credentials']),capture_output=True,text=True,timeout=180)
            if result.returncode:
                return self.send('<h1>App registered; hosting authorization needs attention</h1><p>Keep this helper running. After signing in to Cloudflare, reload this address to retry credential delivery without creating another app.</p>',503)
            memory['credentials'].clear();memory['complete']=True
            self.send('<h1>GitHub App credentials configured securely</h1><p>No credentials were saved in this page or the repository.</p><p>Next, install the private app on <strong>Only select repositories → football-shorts-factory</strong>.</p><a href="'+html.escape(memory['install_url'],quote=True)+'">Review and install GitHub App</a>')
            print('GitHub App runtime credentials configured. Install URL: '+memory['install_url'],flush=True)
        def do_GET(self):
            if self.headers.get('Host')!=f'127.0.0.1:{args.port}':return self.send('<h1>Invalid host</h1>',403)
            parsed=urlparse(self.path);query=parse_qs(parsed.query)
            if time.monotonic()>deadline:return self.send('<h1>Setup link expired</h1>',410)
            if parsed.path=='/' and secrets.compare_digest(query.get('setup',[''])[0],state):
                if memory.get('credentials'):return self.configure()
                if memory.get('used'):return self.send('<h1>This app setup was already submitted</h1><p>Review the existing app in GitHub settings; do not register a duplicate.</p>',409)
                return self.send('<html><head><title>Set up secure GitHub sign-in</title></head><body style="font:18px system-ui;max-width:720px;margin:60px auto;padding:20px"><h1>Set up secure GitHub sign-in</h1><p>Create a private app owned by your GitHub account. It requests <strong>Actions read/write</strong> and repository metadata only.</p><p>At installation, choose only <strong>football-shorts-factory</strong>. It cannot read your other private repositories or change repository code.</p><form action="https://github.com/settings/apps/new?state='+state+'" method="post"><input type="hidden" name="manifest" value="'+html.escape(json.dumps(manifest),quote=True)+'"><button type="submit">Review private GitHub App</button></form></body></html>')
            if parsed.path!='/callback' or not secrets.compare_digest(query.get('state',[''])[0],state):return self.send('<h1>Invalid setup request</h1>',403)
            code=query.get('code',[''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_-]{10,512}',code):return self.send('<h1>Invalid registration code</h1>',400)
            with lock:
                if memory.get('used'):return self.send('<h1>This registration callback was already consumed</h1>',409)
                memory['used']=True
            try:
                r=requests.post('https://api.github.com/app-manifests/'+code+'/conversions',headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10'},timeout=30,allow_redirects=False)
                r.raise_for_status();data=r.json()
                if not isinstance(data.get('client_id'),str) or not isinstance(data.get('client_secret'),str):raise ValueError()
                if not re.fullmatch(r'https://github\.com/apps/[a-z0-9-]+',data.get('html_url','')):raise ValueError()
                memory['credentials']={'GITHUB_CLIENT_ID':data['client_id'],'GITHUB_CLIENT_SECRET':data['client_secret'],
                    'TOKEN_ENCRYPTION_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')}
                memory['install_url']=data['html_url']+'/installations/new'
                self.configure()
            except Exception:
                self.send('<h1>App registration could not be confirmed</h1><p>No credentials were displayed. Review the existing app in GitHub settings before starting another registration.</p>',503)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Setup URL: http://127.0.0.1:{args.port}/?setup={state}',flush=True)
    print('This helper uses only loopback and keeps returned credentials in memory until delivered to Cloudflare.',flush=True)
    try:server.serve_forever()
    finally:server.server_close();memory.clear()


if __name__=='__main__':main()
