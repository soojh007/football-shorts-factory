"""Encrypted receipt state for ephemeral GitHub-hosted runners."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import zipfile

from cryptography.fernet import Fernet,InvalidToken
import requests

RECEIPT_NAME=re.compile(r'[0-9]+_prediction_youtube_upload\.json')
MAX_STATE_BYTES=2*1024*1024


class CloudStateError(ValueError):
    """Safe cloud state error; never print credentials or artifact contents."""


def cipher(oauth_json):
    try:
        refresh=json.loads(oauth_json)['refresh_token']
        if not isinstance(refresh,str) or not refresh:
            raise ValueError()
    except (ValueError,KeyError,TypeError):
        raise CloudStateError('YouTube OAuth secret needs a valid refresh token.') from None
    key=hashlib.sha256(b'football-shorts-factory-receipts-v1\0'+refresh.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def pack_receipts(out,oauth_json):
    receipts={}
    for path in Path(out).glob('*_prediction_youtube_upload.json'):
        if not RECEIPT_NAME.fullmatch(path.name):
            raise CloudStateError('Unexpected receipt filename; refusing to archive it.')
        receipts[path.name]=json.loads(path.read_text(encoding='utf-8'))
    data=json.dumps({'version':1,'receipts':receipts},sort_keys=True).encode()
    if len(data)>MAX_STATE_BYTES:
        raise CloudStateError('Receipt state exceeds the cloud size limit.')
    return cipher(oauth_json).encrypt(data)


def unpack_receipts(encrypted,out,oauth_json):
    try:
        data=json.loads(cipher(oauth_json).decrypt(encrypted))
        if data.get('version')!=1 or not isinstance(data.get('receipts'),dict):
            raise ValueError()
        for name,value in data['receipts'].items():
            if not RECEIPT_NAME.fullmatch(name) or not isinstance(value,dict):
                raise ValueError()
        from backend.main import save_json
        out=Path(out)
        out.mkdir(parents=True,exist_ok=True)
        for name,value in data['receipts'].items():
            save_json(out/name,value)
        return len(data['receipts'])
    except (InvalidToken,ValueError,KeyError,TypeError,AttributeError):
        raise CloudStateError('Saved upload state could not be verified. Check YouTube Studio before running another upload; OAuth rotation may require state recovery.') from None


def restore_latest(out,oauth_json,session=None):
    repository=os.getenv('GITHUB_REPOSITORY','')
    token=os.getenv('GITHUB_TOKEN','')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or not token:
        raise CloudStateError('GitHub runner identity is missing; no upload will be attempted.')
    session=session or requests.Session()
    headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    base=f'https://api.github.com/repos/{repository}/actions/artifacts'
    try:
        response=session.get(base,headers=headers,params={'name':'factory-private-state','per_page':100},timeout=30)
        if response.status_code!=200:
            raise CloudStateError('Cannot read prior upload state from GitHub. Upload stopped to avoid duplicates.')
        artifacts=response.json().get('artifacts')
        if not isinstance(artifacts,list):
            raise CloudStateError('GitHub returned invalid upload state metadata.')
        active=[artifact for artifact in artifacts if not artifact.get('expired')]
        if not active:
            return 0
        latest=max(active,key=lambda item:(item.get('created_at',''),item['id']))
        artifact_id=latest['id']
        if type(artifact_id) is not int or latest.get('size_in_bytes',0)>MAX_STATE_BYTES*2:
            raise CloudStateError('GitHub upload-state artifact is invalid or too large.')
        download=session.get(f'{base}/{artifact_id}/zip',headers=headers,timeout=30)
        if download.status_code!=200 or len(download.content)>MAX_STATE_BYTES*2:
            raise CloudStateError('Could not download prior upload state; no new upload will be attempted.')
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            names=archive.namelist()
            if names!=['receipts.enc'] or archive.getinfo('receipts.enc').file_size>MAX_STATE_BYTES*2:
                raise CloudStateError('Unexpected upload-state archive; refusing to restore it.')
            return unpack_receipts(archive.read('receipts.enc'),out,oauth_json)
    except CloudStateError:
        raise
    except Exception:
        raise CloudStateError('Unable to verify previous cloud upload state; no new upload will be attempted.') from None
