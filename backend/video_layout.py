"""Shared prediction canvas with space for social platform overlays."""
from PIL import Image, ImageDraw

from backend.video import text_block


def social_canvas(frame):
    """Keep all authored content above a blank platform caption area."""
    canvas = Image.new('RGB', (1080, 1920), 'black')
    # Existing prediction artwork ends at y=1750; remove only unused background.
    content = frame.crop((0, 0, 1080, 1760)).resize(
        (864, 1408), Image.Resampling.LANCZOS)
    canvas.paste(content, (108, 170))
    text_block(ImageDraw.Draw(canvas),
               'WATCH TILL THE END FOR MY PREDICTION',
               (108, 55, 972, 145), 38, '#ffffff', max_lines=2)
    return canvas
