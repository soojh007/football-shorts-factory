from PIL import Image
import pytest

from backend.video_layout import social_canvas


@pytest.mark.parametrize('title', [None, 'Manchester City × Fulham'])
def test_social_layout_preserves_content_and_reserves_overlay_space(title):
    artwork = Image.new('RGB', (1080, 1920), 'red')
    frame = social_canvas(artwork, match_title=title)
    assert frame.size == (1080, 1920)
    assert frame.crop((0, 1578, 1080, 1920)).getbbox() is None
    assert frame.getpixel((540, 550)) == (255, 0, 0)
    assert frame.getpixel((540, 1577)) == (255, 0, 0)
    assert frame.crop((0, 0, 1080, 355)).getbbox() is None
    assert frame.crop((135, 355, 945, 420)).getbbox() is not None
    assert frame.crop((135, 420, 945, 485)).getbbox() is not None
