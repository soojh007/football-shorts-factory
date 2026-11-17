import io
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

from PIL import Image,ImageChops
import pytest

from backend.action_media import commons_candidates,catalog_candidates,fetch_media,save_asset
from backend.player_media import MediaError,media_frame


def commons_response(title='File:Named Player match.jpg',license='CC BY 4.0',description='Named Player playing in a match.',categories=None):
    return {'query':{'pages':{'1':{'title':title,'categories':categories or [],'imageinfo':[{
        'width':1000,'height':700,'mime':'image/jpeg','thumburl':'https://thumb.wikimedia.org/example.jpg',
        'descriptionurl':'https://commons.wikimedia.org/wiki/File:Named_Player.jpg','extmetadata':{
            'LicenseShortName':{'value':license},'ImageDescription':{'value':description},'Artist':{'value':'Photographer'}}}]}}}}


def session_for(payload):
    session=Mock();session.get.return_value.status_code=200;session.get.return_value.json.return_value=payload
    return session


def test_action_photo_has_identity_license_and_attribution():
    assets=commons_candidates('Named Player',session_for(commons_response()))
    assert len(assets)==1 and assets[0]['visual_type']=='action'
    assert assets[0]['license_url']=='https://creativecommons.org/licenses/by/4.0/'
    assert assets[0]['archive'] is True


@pytest.mark.parametrize('payload',[
    commons_response(title='File:Different Player match.jpg',description='An unrelated player playing.'),
    commons_response(license='All rights reserved'),
    commons_response(license='CC BY-NC 4.0'),
    commons_response(description='A footballer attending a prime minister meeting.'),
    commons_response(title='File:Named Player profile.jpg',description='Named Player is a footballer.')])
def test_unsupported_or_nonaction_images_are_not_used(payload):
    assert commons_candidates('Named Player',session_for(payload))==[]


def test_bulk_match_categories_do_not_prove_subject_identity():
    payload=commons_response(title='File:Match.jpg',description='Playing a match.',categories=[{'title':'Category:Named Player'}]+[{'title':f'Category:Person {i}'} for i in range(10)])
    assert commons_candidates('Named Player',session_for(payload))==[]


def test_catalog_only_accepts_confirmed_free_action_assets(monkeypatch):
    monkeypatch.setenv('PLAYER_MEDIA_CATALOG_JSON',json.dumps([{'player_id':1,'kind':'video','license':'All rights reserved','identity_verified':True,'action':True}]))
    with pytest.raises(MediaError,match='free-reuse'):catalog_candidates(1)


def test_download_is_bounded_and_response_closed():
    session=Mock();response=session.get.return_value;response.status_code=200
    response.iter_content.return_value=[b'x'*(8*1024*1024),b'overflow']
    with pytest.raises(MediaError,match='limit'):fetch_media({'kind':'image','url':'https://example.org/a'},session)
    response.close.assert_called_once()


def test_clip_decodes_motion_without_original_audio(tmp_path):
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=30',
        '-f','lavfi','-i','sine=frequency=1000','-t','1.2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True,timeout=20)
    asset=save_asset({'kind':'video'},source.read_bytes(),tmp_path,1)
    assert asset['kind']=='video' and asset['fps']==30 and asset['frame_count']>=30
    assert asset['audio_used'] is False
    first=media_frame(asset,0);later=media_frame(asset,.6)
    assert ImageChops.difference(first,later).convert('RGB').getbbox() is not None


def test_photo_crop_changes_with_time(tmp_path):
    from backend.personal_video import photo
    from PIL import ImageDraw
    original=Image.new('RGB',(1000,700));draw=ImageDraw.Draw(original)
    for x in range(0,1000,25):draw.rectangle((x,0,x+12,700),fill=(x%255,50,150))
    path=tmp_path/'photo.png';original.save(path)
    asset={'kind':'image','visual_type':'action','name':'Named Player','path':str(path)}
    images=[]
    for second in (0,5):
        image=Image.new('RGB',(1080,1920));photo(image,ImageDraw.Draw(image),asset,(64,430,1016,1035),1,time_seconds=second);images.append(image)
    assert ImageChops.difference(*images).getbbox() is not None


def test_missing_action_media_renders_named_graphics():
    from backend.prediction_video import draw_prediction_frame
    p={'context':{'venue':{}},'media_assets':[],'teams':{'home':{'name':'Home'},'away':{'name':'Away'}},
       'sections':[{'kind':'hook','text':'My pick.'}],'featured_players':{'home':[{'name':'Home Starter','player_id':1,'jersey_number':9}],
                                                                  'away':[{'name':'Away Starter','player_id':2,'jersey_number':10}]}}
    assert draw_prediction_frame(p,{'word_start':0,'text':'My pick.'},0,time_seconds=1).size==(1080,1920)


def test_sharealike_action_images_are_allowed_with_canonical_terms():
    assets=commons_candidates('Named Player',session_for(commons_response(license='CC BY-SA 4.0')))
    assert assets[0]['share_alike'] is True
    assert assets[0]['license_url']=='https://creativecommons.org/licenses/by-sa/4.0/'


def test_search_continues_beyond_featured_players(tmp_path,monkeypatch):
    from backend.player_media import collect_player_media
    calls=[]
    def photo(name,session):
        calls.append(name)
        return None if name=='Featured Player' else {'kind':'image','license':'CC BY 4.0'}
    monkeypatch.setattr('backend.player_media.commons_photo',photo)
    monkeypatch.setattr('backend.action_media.catalog_candidates',lambda *args:[])
    monkeypatch.setattr('backend.action_media.fetch_media',lambda *args:b'image')
    monkeypatch.setattr('backend.media_review.is_action_photo',lambda *args,**kwargs:True)
    monkeypatch.setattr('backend.action_media.save_asset',lambda *args:{'path':'/tmp/photo.png'})
    p={'featured_players':{'home':[{'player_id':1,'name':'Featured Player'}]},
       'lineups':{'home':{'starters':[{'player_id':2,'name':'Other Starter'}]}}}
    assets=collect_player_media(p,tmp_path,session=Mock())
    assert calls==['Featured Player','Other Starter']
    assert assets[0]['name']=='Other Starter'
    assert p['media_diagnostics'][0]['status']=='no_eligible_action_media'
