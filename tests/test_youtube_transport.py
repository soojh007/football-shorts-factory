"""Exercise real Google/httplib2 resumable protocol against a local HTTP server."""
import io
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread

from googleapiclient.http import HttpRequest,MediaIoBaseUpload

from backend.youtube_auth import youtube_http


def test_real_multichunk_upload_accepts_308_without_location():
    received=[];initiations=[]
    data=b'video-data-'*30000
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            initiations.append(self.path)
            self.send_response(200)
            self.send_header('Location',f'http://127.0.0.1:{self.server.server_port}/session')
            self.send_header('Content-Length','0');self.end_headers()
        def do_PUT(self):
            chunk=self.rfile.read(int(self.headers['Content-Length']))
            received.append((self.headers['Content-Range'],chunk))
            total=sum(len(c) for _,c in received)
            if total<len(data):
                self.send_response(308)
                self.send_header('Range',f'bytes=0-{total-1}')
                self.send_header('Content-Length','0');self.end_headers()
            else:
                body=json.dumps({'id':'abcdefghijk','status':{'privacyStatus':'private'}}).encode()
                self.send_response(201);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    transport=youtube_http();transport.proxy_info=None
    try:
        assert 308 not in transport.redirect_codes
        assert {301,302,307}<=transport.redirect_codes
        assert transport.timeout==60
        media=MediaIoBaseUpload(io.BytesIO(data),mimetype='video/mp4',chunksize=256*1024,resumable=True)
        request=HttpRequest(transport,lambda r,c:json.loads(c),f'http://127.0.0.1:{server.server_port}/upload',
                            method='POST',body='{}',headers={'Content-Type':'application/json'},resumable=media)
        progress,result=request.next_chunk()
        assert result is None and progress.resumable_progress==256*1024
        _,result=request.next_chunk()
        assert result['id']=='abcdefghijk'
        assert len(initiations)==1 and len(received)==2
        assert b''.join(c for _,c in received)==data
        assert received[0][0]==f'bytes 0-262143/{len(data)}'
        assert received[1][0]==f'bytes 262144-{len(data)-1}/{len(data)}'
    finally:
        transport.close();server.shutdown();server.server_close();thread.join()
