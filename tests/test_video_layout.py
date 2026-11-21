from PIL import Image

from backend.video_layout import social_canvas


def test_social_layout_preserves_content_and_reserves_overlay_space():
    artwork = Image.new('RGB', (1080, 1920), 'red')
    frame = social_canvas(artwork)
    assert frame.size == (1080, 1920)
    assert frame.crop((0, 1578, 1080, 1920)).getbbox() is None
    assert frame.getpixel((108, 170)) == (255, 0, 0)
    assert frame.getpixel((971, 1577)) == (255, 0, 0)
    assert frame.crop((108, 55, 972, 145)).getbbox() is not None
