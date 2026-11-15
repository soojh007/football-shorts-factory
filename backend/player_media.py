"""Real player images with identity/source metadata; no invented player likenesses."""
from functools import lru_cache
from pathlib import Path
import re
import unicodedata

from PIL import Image
import requests

class MediaError(ValueError): pass

HEADERS={'User-Agent':'FootballShortsFactory/1.0 (https://github.com/soojh007/football-shorts-factory)'}


def normalized(value):
    return re.findall(r'[a-z0-9]+',unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower())


def commons_photo(name,session):
    from backend.action_media import commons_candidates
    candidates=commons_candidates(name,session)
    candidates=[candidate for candidate in candidates if candidate['visual_type']=='action']
    return candidates[0] if candidates else None


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
            from backend.action_media import catalog_candidates,fetch_media,save_asset
            record={'player_id':player['player_id'],'name':player['name'],'side':side}
            candidates=catalog_candidates(player['player_id'])
            photo=commons_photo(player['name'],session)
            if photo:candidates.append(photo)
            for candidate in candidates:
                try:
                    data=fetch_media(candidate,session)
                    saved=save_asset(candidate,data,folder,player['player_id'])
                    assets.append({**record,**candidate,**saved})
                    break
                except (requests.RequestException,OSError,ValueError,MediaError,Image.DecompressionBombError):continue
    return assets


@lru_cache(maxsize=48)
def load_player_image(path):
    return Image.open(path).convert('RGBA')


def media_frame(asset,time_seconds=0):
    if asset.get('kind')=='video':
        number=int(max(0,time_seconds)*asset['fps'])%asset['frame_count']+1
        return load_player_image(str(Path(asset['frames_path'])/f'frame_{number:04d}.jpg'))
    return load_player_image(asset['path'])
