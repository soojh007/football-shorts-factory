"""Shared prediction canvas with space for social platform overlays."""
from PIL import Image, ImageDraw

from backend.video import text_block


def social_canvas(frame, *, match_title=None, palette=None):
    """Keep all authored content above a blank platform caption area."""
    canvas = Image.new('RGB', (1080, 1920), 'black')
    # Existing prediction artwork ends at y=1750; remove only unused background.
    if match_title:
        # Replace the personal renderer's redundant branding/title header, rather
        # than shrinking the player imagery to make room for the viewing hook.
        content = frame.crop((0, 390, 1080, 1760)).resize(
            (712, 903), Image.Resampling.LANCZOS)
        canvas.paste(content, (184, 675))
        colors = palette or {'bg': '#101814', 'text': '#faf5e8', 'accent': '#c2ff67'}
        header = ImageDraw.Draw(canvas)
        header.rectangle((184, 535, 895, 674), fill=colors['bg'])
        header.line((214, 555, 866, 555), fill=colors['accent'], width=5)
        text_block(header, match_title,
                   (214, 580, 866, 660), 38, colors['text'], max_lines=2)
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
