"""Real player images with identity/source metadata; no invented player likenesses."""
from functools import lru_cache
from pathlib import Path
import re
import time
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
    return {**candidates[0],'_alternatives':candidates[1:4]} if candidates else None


def collect_player_media(prediction,out,session=None):
    load_player_image.cache_clear()
    out=Path(out)
    folder=out/'player_assets';folder.mkdir(exist_ok=True)
    session=session or requests.Session()
    assets=[]
    deadline=time.monotonic()+120
    diagnostics=[]
    for side in ('home','away'):
        side_deadline=min(deadline,time.monotonic()+55)
        players=prediction.get('featured_players',{}).get(side,[])[:2]
        starters=prediction.get('lineups',{}).get(side,{}).get('starters',[])
        archive=prediction.get('archive_players',{}).get(side,[])
        seen=set();pool=[]
        for player in players+sorted(starters,key=lambda p:p.get('position_id')!=27)+archive:
            if player['player_id'] not in seen:
                seen.add(player['player_id']);pool.append(player)
        for player in pool[:12]:
            if time.monotonic()>=side_deadline or sum(a['side']==side for a in assets)>=2:break
            from backend.action_media import catalog_candidates,fetch_media,save_asset
            record={'player_id':player['player_id'],'name':player['name'],'side':side}
            candidates=catalog_candidates(player['player_id'])
            photo=commons_photo(player['name'],session)
            if photo:
                alternatives=photo.pop('_alternatives',[])
                candidates.extend([photo]+alternatives)
            if not candidates:diagnostics.append({'side':side,'player_id':player['player_id'],'status':'no_eligible_action_media'})
            for candidate in candidates:
                if time.monotonic()>=side_deadline:break
                try:
                    data=fetch_media(candidate,session)
                    from backend.media_review import is_action_photo
                    if candidate.get('kind')!='video' and not is_action_photo(data,session,timeout=min(15,max(1,side_deadline-time.monotonic()))):
                        diagnostics.append({'side':side,'player_id':player['player_id'],'status':'not_verified_action_photo'})
                        continue
                    saved=save_asset(candidate,data,folder,player['player_id'])
                    assets.append({**record,**candidate,**saved})
                    break
                except (requests.RequestException,OSError,ValueError,MediaError,Image.DecompressionBombError):continue
    prediction['media_diagnostics']=diagnostics
    return assets


@lru_cache(maxsize=48)
def load_player_image(path):
    return Image.open(path).convert('RGBA')


def media_frame(asset,time_seconds=0):
    if asset.get('kind')=='video':
        number=int(max(0,time_seconds)*asset['fps'])%asset['frame_count']+1
        return load_player_image(str(Path(asset['frames_path'])/f'frame_{number:04d}.jpg'))
    return load_player_image(asset['path'])
