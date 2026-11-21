"""Shared prediction canvas with space for social platform overlays."""
from PIL import Image, ImageDraw

from backend.video import text_block


def social_canvas(frame, *, match_title=None):
    """Keep all authored content above a blank platform caption area."""
    canvas = Image.new('RGB', (1080, 1920), 'black')
    # Existing prediction artwork ends at y=1750; remove only unused background.
    if match_title:
        # Replace the personal renderer's redundant branding/title header, rather
        # than shrinking the player imagery to make room for the viewing hook.
        content = frame.crop((0, 390, 1080, 1760)).resize(
            (810, 1028), Image.Resampling.LANCZOS)
        canvas.paste(content, (135, 550))
        text_block(ImageDraw.Draw(canvas), match_title,
                   (135, 490, 945, 545), 38, '#ffffff', max_lines=1)
    else:
        content = frame.crop((0, 0, 1080, 1760)).resize(
            (630, 1028), Image.Resampling.LANCZOS)
        canvas.paste(content, (225, 550))
    draw = ImageDraw.Draw(canvas)
    # Leave the status bar, Shorts navigation and topic chips above the hook.
    text_block(draw, 'WATCH TILL THE END',
               (135, 355, 945, 420), 54, '#ffffff', max_lines=1)
    text_block(draw, 'FOR MY PREDICTION',
               (135, 420, 945, 485), 54, '#ffffff', max_lines=1)
    return canvas
