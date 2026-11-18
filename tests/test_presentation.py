import pytest
from PIL import ImageColor
from backend.presentation import PALETTES, PERSONALITIES, choose_presentation, palette_for, personality_for, speech_settings


def luminance(color):
    rgb=[v/255 for v in ImageColor.getrgb(color)]
    values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return sum(v*w for v,w in zip(values,[.2126,.7152,.0722]))


def contrast(a,b):
    lo,hi=sorted([luminance(a),luminance(b)])
    return (hi+.05)/(lo+.05)


def test_all_pairings_rotate_without_changing_the_forecast():
    pairs=[choose_presentation(n) for n in range(16)]
    assert len({(p['palette_index'],p['personality_index']) for p in pairs})==16
    assert choose_presentation(16)==choose_presentation(0)
    assert [PERSONALITIES[p['personality_index']]['gender'] for p in pairs[:4]]==['male','female','male','female']


def test_palettes_have_readable_titles_accents_and_captions():
    for p in PALETTES:
        assert contrast(p['bg'],p['text'])>=7
        assert contrast(p['bg'],p['accent'])>=4.5
        assert contrast(p['bg'],p['secondary'])>=4.5
        assert contrast(p['surface'],p['text'])>=7


@pytest.mark.parametrize('bad',[-1,4,True,'1'])
def test_bad_identity_is_rejected(bad):
    with pytest.raises(ValueError):palette_for({'presentation':{'palette_index':bad}})


def test_narrator_cache_identity_changes_with_voice_and_personality():
    settings=[speech_settings({'presentation':choose_presentation(n)}) for n in range(4)]
    assert len({s['voice'] for s in settings})==4
    assert len({s['instructions'] for s in settings})==4
    assert all('Singaporean English' in s['instructions'] for s in settings)
    assert personality_for({})['voice']=='cedar'
