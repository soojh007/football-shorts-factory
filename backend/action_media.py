"""Free-reuse action media discovery and bounded, silent video decoding."""
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

from PIL import Image,ImageOps
import requests

LICENSE_URLS={'CC0':'https://creativecommons.org/publicdomain/zero/1.0/','Public domain':'https://creativecommons.org/publicdomain/mark/1.0/','CC BY 2.0':'https://creativecommons.org/licenses/by/2.0/','CC BY 3.0':'https://creativecommons.org/licenses/by/3.0/','CC BY 4.0':'https://creativecommons.org/licenses/by/4.0/'}
FREE_LICENSES={'CC0','Public domain','CC BY 2.0','CC BY 3.0','CC BY 4.0'}
ACTION_WORDS=('training','match','playing','ball','entrenamiento','partido','jugando','balon','wedstrijd',' vs ')
PORTRAIT_WORDS=('portrait','headshot','press conference','profile','mugshot','signing','prime minister','meeting')


def plain(value): return html.unescape(re.sub('<[^>]+>','',value or ''))


def commons_candidates(name,session):
    from backend.player_media import HEADERS,normalized
    parts=normalized(name)
    if len(parts)<2:return []
    try:
        response=session.get('https://commons.wikimedia.org/w/api.php',params={
            'action':'query','format':'json','generator':'search','gsrsearch':f'"{name}"',
            'gsrnamespace':6,'gsrlimit':12,'prop':'imageinfo|categories','cllimit':50,'iiprop':'url|extmetadata|size|mime','iiurlwidth':1200},headers=HEADERS,timeout=15)
        if response.status_code!=200:return []
        candidates=[]
        for page in (response.json().get('query') or {}).get('pages',{}).values():
            title=' '.join(normalized(page.get('title','')))
            info=(page.get('imageinfo') or [{}])[0];meta=info.get('extmetadata') or {}
            license_name=(meta.get('LicenseShortName') or {}).get('value','')
            if license_name not in FREE_LICENSES:continue
            if any(flag in str(meta).lower() for flag in ('copyright violation','delete this image','copyvio')):continue
            description=plain((meta.get('ImageDescription') or {}).get('value',''))
            category_names=[str(category.get('title','')).removeprefix('Category:') for category in page.get('categories',[])]
            in_title=all(part in title.split() for part in parts)
            in_description=' '.join(parts) in ' '.join(normalized(description))
            in_category=len(category_names)<=8 and any(normalized(category)==parts for category in category_names)
            if not (in_title or in_description or in_category):continue
            content=(page.get('title','')+' '+description).lower()
            action=bool(re.search(r'\b(?:'+'|'.join(re.escape(word.strip()) for word in ACTION_WORDS)+r')\b',content)) and not any(word in content for word in PORTRAIT_WORDS)
            video=str(info.get('mime','')).startswith('video/')
            url=info.get('url') if video else info.get('thumburl') or info.get('url')
            if urlparse(url or '').scheme!='https' or urlparse(url or '').hostname not in ('upload.wikimedia.org','thumb.wikimedia.org'):continue
            if not action:continue
            if not video and (info.get('width',0)<400 or info.get('height',0)<300):continue
            candidates.append({'url':url,'source_url':info.get('descriptionurl'),'license':license_name,
                'license_url':(meta.get('LicenseUrl') or {}).get('value') or LICENSE_URLS[license_name],'artist':plain((meta.get('Artist') or {}).get('value','')),
                'title':plain(page.get('title','')),'description':description,'kind':'video' if video else 'image',
                'visual_type':'action' if action else 'portrait','identity_match':'full player name in file title' if in_title else 'explicit player description' if in_description else 'exact player category','archive':True})
        return sorted(candidates,key=lambda item:(item['kind']=='video',item['visual_type']=='action'),reverse=True)
    except (requests.RequestException,ValueError,TypeError,AttributeError):return []


def catalog_candidates(player_id):
    """Optional curated free-media URLs; no broadcast/paid/unclear licenses."""
    from backend.player_media import MediaError
    raw=os.getenv('PLAYER_MEDIA_CATALOG_JSON','').strip()
    if not raw:return []
    try: rows=json.loads(raw)
    except ValueError:raise MediaError('The free player-media catalog must be valid JSON.') from None
    if not isinstance(rows,list):raise MediaError('The free player-media catalog must be a list.')
    selected=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('player_id')!=player_id:continue
        if row.get('license') not in FREE_LICENSES or row.get('identity_verified') is not True or row.get('action') is not True:
            raise MediaError('Catalog assets require verified player identity, action content and a supported free-reuse license.')
        if row.get('kind') not in ('image','video') or not all(row.get(k) for k in ('url','source_url','artist','license_url')):
            raise MediaError('Catalog assets need their type, source, artist and license link.')
        if urlparse(row['url']).scheme!='https' or not urlparse(row['url']).hostname:
            raise MediaError('Catalog media must use an HTTPS URL.')
        selected.append({**row,'visual_type':'action','identity_match':'curated Sportmonks player ID','archive':True})
    return sorted(selected,key=lambda row:row['kind']=='video',reverse=True)


def fetch_media(candidate,session):
    from backend.player_media import HEADERS,MediaError
    limit=40*1024*1024 if candidate.get('kind')=='video' else 8*1024*1024
    response=session.get(candidate['url'],headers=HEADERS,timeout=25,stream=True,allow_redirects=False)
    try:
        if response.status_code!=200:raise MediaError('Player media download was unavailable.')
        content=bytearray()
        for chunk in response.iter_content(64*1024):
            content.extend(chunk)
            if len(content)>limit:raise MediaError('Player media exceeds the download limit.')
        return bytes(content)
    finally:response.close()


def save_asset(candidate,data,folder,player_id):
    from backend.player_media import MediaError
    digest=hashlib.sha256(data).hexdigest();prefix=f'{player_id}_{digest[:12]}'
    if candidate.get('kind')!='video':
        image=Image.open(io.BytesIO(data))
        if image.width*image.height>20_000_000:raise MediaError('Player photo dimensions are too large.')
        image=ImageOps.exif_transpose(image).convert('RGBA');image.thumbnail((1400,1600))
        path=folder/f'{prefix}.png';image.save(path)
        return {'path':str(path.resolve()),'kind':'image','width':image.width,'height':image.height,'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    path=folder/f'{prefix}.media';path.write_bytes(data)
    try:
        result=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-select_streams','v:0','-show_entries','stream=width,height:format=duration','-of','json',str(path.resolve())],capture_output=True,check=True,timeout=20)
        probe=json.loads(result.stdout);stream=probe['streams'][0];duration=float(probe['format']['duration'])
        if not math.isfinite(duration) or duration<1 or stream['width']*stream['height']>20_000_000:raise ValueError()
        frames=folder/f'{prefix}_frames';frames.mkdir(exist_ok=True)
        seconds=min(4,duration)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-protocol_whitelist','file,pipe','-i',str(path.resolve()),
            '-t',str(seconds),'-an','-vf',"fps=30,scale=w='min(960,iw)':h='min(1200,ih)':force_original_aspect_ratio=decrease",'-q:v','3',str(frames.resolve()/'frame_%04d.jpg')],capture_output=True,check=True,timeout=60)
        count=len(list(frames.glob('frame_*.jpg')))
        if count<1:raise ValueError()
        return {'path':str(path.resolve()),'kind':'video','frames_path':str(frames.resolve()),'frame_count':count,'fps':30,
                'duration_seconds':seconds,'width':stream['width'],'height':stream['height'],'image_sha256':digest,'audio_used':False}
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,IndexError,TypeError):
        raise MediaError('The player clip could not be decoded safely.') from None
