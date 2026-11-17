import io
import json
from unittest.mock import Mock

from PIL import Image
import pytest
from backend.media_review import is_action_photo


@pytest.mark.parametrize('accepted',[True,False])
def test_visual_review_checks_action_without_identifying_faces(monkeypatch,accepted):
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key')
    data=io.BytesIO();Image.new('RGB',(100,100),'green').save(data,format='PNG')
    session=Mock();session.post.return_value.status_code=200
    session.post.return_value.json.return_value={'status':'completed','output':[{'type':'message','content':[
        {'type':'output_text','text':json.dumps({'action':accepted})}]}]}
    assert is_action_photo(data.getvalue(),session) is accepted
    body=session.post.call_args.kwargs['json']
    assert body['store'] is False
    assert body['input'][0]['content'][0]['image_url'].startswith('data:image/jpeg;base64,')
    assert 'never identify people' in body['instructions']


def test_failed_visual_review_omits_image_without_blocking(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key')
    data=io.BytesIO();Image.new('RGB',(100,100)).save(data,format='PNG')
    session=Mock();session.post.return_value.status_code=503
    assert is_action_photo(data.getvalue(),session) is False
