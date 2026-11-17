import json
from pathlib import Path

from backend.narration_templates import choose_template,TEMPLATES
from backend.cloud_receipts import pack_receipts,unpack_receipts

CHANNEL='UCw3H9KY5toxOuN7cSDsIKqA'


def receipt(folder,index,**changes):
    data={'state':'uploaded','channel_id':CHANNEL,'video_id':f'{index:011d}'}
    data.update(changes)
    (folder/f'{index}_prediction_youtube_upload.json').write_text(json.dumps(data))


def test_four_formats_cycle_across_successful_uploads(tmp_path):
    selected=[]
    for index in range(8):
        selected.append(choose_template(tmp_path,CHANNEL)['index'])
        receipt(tmp_path,index)
    assert selected==[0,1,2,3,0,1,2,3]
    assert len({tuple(style['order']) for style in TEMPLATES})==4


def test_previews_failures_and_other_channels_do_not_advance_rotation(tmp_path):
    receipt(tmp_path,1,state='uploading')
    receipt(tmp_path,2,channel_id='different-channel')
    receipt(tmp_path,3,video_id='invalid')
    (tmp_path/'4_prediction.json').write_text('{}')
    (tmp_path/'5_prediction_youtube_upload.json').write_text('bad-json')
    assert choose_template(tmp_path,CHANNEL)['index']==0
    assert choose_template(tmp_path,CHANNEL)['index']==0
    receipt(tmp_path,6)
    assert choose_template(tmp_path,CHANNEL)['index']==1


def test_duplicate_video_receipts_count_once(tmp_path):
    receipt(tmp_path,1,video_id='abcdefghijk')
    receipt(tmp_path,2,video_id='abcdefghijk')
    assert choose_template(tmp_path,CHANNEL)['successful_uploads_before_this']==1


def test_rotation_survives_encrypted_cloud_state_restore(tmp_path):
    source=tmp_path/'source';source.mkdir()
    for index in range(3):receipt(source,index)
    oauth=json.dumps({'refresh_token':'synthetic-refresh'})
    archive=pack_receipts(source,oauth)
    target=tmp_path/'fresh-runner';unpack_receipts(archive,target,oauth)
    assert choose_template(target,CHANNEL)['index']==3
    receipt(target,3)
    assert choose_template(target,CHANNEL)['index']==0
