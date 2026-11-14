"""Real player images with identity/source metadata; no invented player likenesses."""
from functools import lru_cache
import io
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlparse

from PIL import Image,ImageOps
import requests

class MediaError(ValueError): pass

MAX_BYTES=8*1024*1024
HEADERS={'User-Agent':'FootballShortsFactory/1.0 (https://github.com/soojh007/football-shorts-factory)'}


def normalized(value):
    return re.findall(r'[a-z0-9]+',unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower())


def commons_photo(name,session):
    """Only named football portraits/action photographs with clear reuse metadata."""
    parts=normalized(name)
    if len(parts)<2 or len(parts[-1])<4: return None
    try:
        response=session.get('https://commons.wikimedia.org/w/api.php',params={
            'action':'query','format':'json','generator':'search','gsrsearch':f'"{name}" football',
            'gsrnamespace':6,'gsrlimit':5,'prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':720},headers=HEADERS,timeout=15)
        if response.status_code!=200:return None
        for page in (response.json().get('query') or {}).get('pages',{}).values():
            title=' '.join(normalized(page.get('title','')))
            if not all(part in title.split() for part in parts): continue
            info=(page.get('imageinfo') or [{}])[0]
            meta=info.get('extmetadata') or {}
            license_name=(meta.get('LicenseShortName') or {}).get('value','')
            if license_name not in ('CC0','Public domain','CC BY 2.0','CC BY 3.0','CC BY 4.0'):continue
            url=info.get('thumburl') or info.get('url')
            if urlparse(url or '').hostname!='upload.wikimedia.org':continue
            return {'url':url,'source_url':info.get('descriptionurl'),'license':license_name,
                    'artist':re.sub('<[^>]+>','',(meta.get('Artist') or {}).get('value','')),'identity_match':'full player name in file title'}
    except (requests.RequestException,ValueError,TypeError,AttributeError):
        pass
    return None


def collect_player_media(prediction,out,session=None):
    load_player_image.cache_clear()
    out=Path(out)
    folder=out/'player_assets';folder.mkdir(exist_ok=True)
    session=session or requests.Session()
    assets=[]
    for side in ('home','away'):
        players=prediction.get('featured_players',{}).get(side,[])[:2]
        if not players:players=prediction.get('lineups',{}).get(side,{}).get('starters',[])[:2]
        for player in players:
            path=folder/f"{player['player_id']}.png"
            record={'player_id':player['player_id'],'name':player['name'],'side':side,'path':str(path.resolve())}
            # Official CDN images provide an identity-linked fallback when Commons
            # cannot establish an unambiguous name match/reuse license.
            photo=commons_photo(player['name'],session)
            candidates=[photo] if photo else []
            official=player.get('image_url')
            if official and urlparse(official).scheme=='https' and urlparse(official).hostname=='cdn.sportmonks.com':
                candidates.append({'url':official,'source_url':official,'license':'provider asset; review subscription media terms','artist':'Sportmonks supplied player image','identity_match':'Sportmonks player ID'})
            for candidate in candidates:
                try:
                    response=session.get(candidate['url'],headers=HEADERS,timeout=20)
                    if response.status_code!=200 or len(response.content)>MAX_BYTES:continue
                    image=Image.open(io.BytesIO(response.content))
                    if image.width*image.height>20_000_000:continue
                    image=ImageOps.exif_transpose(image).convert('RGBA')
                    image.thumbnail((960,1200))
                    image.save(path)
                    import hashlib
                    assets.append({**record,**candidate,'width':image.width,'height':image.height,'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
                    break
                except (requests.RequestException,OSError,ValueError,Image.DecompressionBombError):continue
    for side in ('home','away'):
        if not any(asset['side']==side for asset in assets):
            raise MediaError('No verified player visual is available for one team; a generic or invented player will not be substituted.')
    return assets


@lru_cache(maxsize=48)
def load_player_image(path):
    return Image.open(path).convert('RGBA')
