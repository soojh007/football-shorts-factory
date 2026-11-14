"""Pillow match graphics and FFmpeg vertical video encoding."""
import json
from fractions import Fraction
import os
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT, FPS = 1080, 1920, 30
STYLE_VERSION = 1
BG, PANEL, WHITE, MUTED, GREEN, BLUE = '#0b121c', '#142233', '#f4f7fa', '#93a8ba', '#b6ff52', '#65d9ef'


class VideoError(ValueError):
    """Safe rendering failure."""


def font_path():
    configured = os.getenv('VIDEO_FONT')
    candidates = [configured] if configured else [
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
        'C:/Windows/Fonts/arialbd.ttf',
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return Path(path)
    raise VideoError('No usable font found; set VIDEO_FONT to a TrueType font file.')


def wrap(draw, text, font, width):
    lines, current = [], ''
    for word in text.split():
        candidate = f'{current} {word}'.strip()
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def text_block(draw, text, box, size, color=WHITE, align='center', max_lines=3):
    x0, y0, x1, y1 = box
    path = font_path()
    for actual in range(size, 19, -2):
        font = ImageFont.truetype(str(path), actual)
        lines = wrap(draw, text, font, x1 - x0)
        if (len(lines) <= max_lines and len(lines) * actual * 1.3 <= y1 - y0
                and all(draw.textlength(line, font=font) <= x1 - x0 for line in lines)):
            break
    else:
        raise VideoError('Text cannot fit safely in the video layout.')
    height = actual * 1.3
    start = y0 + (y1 - y0 - len(lines) * height) / 2
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        x = x0 if align == 'left' else (x0 + x1 - width) / 2
        draw.text((x, start + i * height), line, font=font, fill=color)


def active_metric(analysis, word_index):
    active = 'score'
    for point in analysis['key_points']:
        offset = analysis['script'].find(point['sentence'])
        if offset >= 0 and len(analysis['script'][:offset].split()) <= word_index:
            active = point['id']
    return active


def draw_frame(fixture, analysis, caption, progress):
    image = Image.new('RGB', (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    # Graphic pitch markings provide depth without licensed match imagery.
    for x in range(0, WIDTH, 108):
        draw.line((x, 0, x, HEIGHT), fill='#101b27', width=1)
    draw.ellipse((-400, 900, 1480, 2780), outline='#1c3240', width=3)
    draw.ellipse((-120, 1180, 1200, 2500), outline='#1c3240', width=2)
    draw.rectangle((72, 105, 82, 145), fill=GREEN)
    text_block(draw, 'FOOTBALL / MATCH FILE', (104, 94, 920, 154), 32, MUTED, 'left', 1)
    text_block(draw, 'PREMIER LEAGUE', (72, 192, 1008, 264), 49, GREEN, 'left', 1)
    date = fixture['match_date'][:10]
    text_block(draw, f'{date}   /   FULL TIME', (72, 274, 1008, 330), 27, MUTED, 'left', 1)
    draw.rounded_rectangle((72, 372, 1008, 690), radius=28, fill=PANEL)
    text_block(draw, fixture['home_team']['name'], (96, 388, 465, 492), 43, WHITE, max_lines=2)
    text_block(draw, fixture['away_team']['name'], (615, 388, 984, 492), 43, WHITE, max_lines=2)
    score = fixture['final_score']
    text_block(draw, str(score['home']), (96, 500, 465, 656), 128, GREEN, max_lines=1)
    text_block(draw, '—', (476, 510, 604, 640), 66, MUTED, max_lines=1)
    text_block(draw, str(score['away']), (615, 500, 984, 656), 128, BLUE, max_lines=1)
    metric = active_metric(analysis, caption['word_start'])
    labels = {'possession': 'POSSESSION', 'total_shots': 'TOTAL SHOTS', 'shots_on_target': 'SHOTS ON TARGET',
              'expected_goals': 'EXPECTED GOALS', 'corners': 'CORNERS', 'yellow_cards': 'YELLOW CARDS', 'red_cards': 'STRAIGHT RED CARDS'}
    draw.rounded_rectangle((72, 742, 1008, 1118), radius=28, fill=PANEL)
    if metric in labels:
        pair = fixture['statistics'][metric]
        text_block(draw, labels[metric], (110, 770, 970, 838), 37, MUTED, max_lines=1)
        values = [f"{pair[side]:g}" + ('%' if metric == 'possession' else '') if pair[side] is not None else 'N/A' for side in ('home', 'away')]
        text_block(draw, values[0], (108, 866, 474, 1010), 104, GREEN, max_lines=1)
        text_block(draw, values[1], (606, 866, 972, 1010), 104, BLUE, max_lines=1)
        left, right = pair['home'], pair['away']
        share = left / (left + right) if left is not None and right is not None and left + right > 0 else 0.5
        draw.rounded_rectangle((126, 1054, 954, 1074), radius=10, fill=BLUE)
        if left is None or right is None:
            draw.rectangle((126, 1054, 954, 1074), fill=PANEL)
        elif share > 0:
            draw.rectangle((126, 1054, 126 + int(828 * share), 1074), fill=GREEN)
    else:
        text_block(draw, 'THE MATCH, BY THE NUMBERS', (126, 794, 954, 944), 57, WHITE, max_lines=2)
        text_block(draw, 'Final score. Recorded statistics.', (126, 966, 954, 1052), 30, MUTED, max_lines=2)
    text_block(draw, 'MATCH RECAP', (72, 1180, 1008, 1232), 26, GREEN, 'left', 1)
    draw.rounded_rectangle((72, 1260, 1008, 1518), radius=25, fill='#1b2d40')
    text_block(draw, caption['text'], (116, 1285, 964, 1490), 60, WHITE, max_lines=3)
    draw.rounded_rectangle((72, 1590, 1008, 1598), radius=4, fill='#294052')
    draw.rectangle((72, 1590, 72 + int(936 * progress), 1598), fill=GREEN)
    text_block(draw, 'AI-GENERATED VOICE', (72, 1644, 1008, 1700), 27, MUTED, 'left', 1)
    text_block(draw, 'Match data: Sportmonks  /  Statistical recap', (72, 1704, 1008, 1752), 22, MUTED, 'left', 1)
    return image


def require_tools():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise VideoError('Install FFmpeg and ffprobe, then retry rendering.')
    font_path()


def encode_video(frames, captions, audio_path, destination, duration, workdir):
    manifest = workdir / 'frames.ffconcat'
    lines = ['ffconcat version 1.0']
    for frame, caption in zip(frames, captions, strict=True):
        frames_in_scene = max(1, round(caption['end'] * FPS) - round(caption['start'] * FPS))
        lines.extend([f"file '{frame.name}'", f"option framerate {FPS}", f"duration {frames_in_scene / FPS:.9f}"])
    lines.extend([f"file '{frames[-1].name}'", f"option framerate {FPS}"])
    manifest.write_text('\n'.join(lines) + '\n')
    # safe=0 permits per-image framerate options; all manifest filenames above
    # are controlled generated basenames, never source text or external URLs.
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
               '-i', str(manifest), '-i', str(audio_path.resolve()), '-map', '0:v:0', '-map', '1:a:0',
               '-vf', 'fps=30,tpad=stop_mode=clone:stop_duration=1', '-r', str(FPS), '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'stillimage',
               '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
               '-threads', '2', str(destination)]
    try:
        subprocess.run(command, cwd=workdir, capture_output=True, check=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise VideoError('FFmpeg encoding failed; check codec availability, output permissions and disk space.') from None


def probe_video(path, duration):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                                capture_output=True, check=True, timeout=30)
        payload = json.loads(result.stdout)
        video = next(stream for stream in payload['streams'] if stream['codec_type'] == 'video')
        audio = next(stream for stream in payload['streams'] if stream['codec_type'] == 'audio')
        length = float(payload['format']['duration'])
        if (video['width'] != WIDTH or video['height'] != HEIGHT or video['codec_name'] != 'h264'
                or video.get('pix_fmt') != 'yuv420p' or audio['codec_name'] != 'aac'
                or Fraction(video['r_frame_rate']) != FPS
                or abs(float(video['duration']) - duration) > 1 / FPS + 0.015
                or abs(length - duration) > 0.3):
            raise VideoError('Rendered video failed dimension, codec, or duration checks.')
        return {'width': WIDTH, 'height': HEIGHT, 'fps': FPS, 'duration_seconds': length,
                'video_codec': video['codec_name'], 'audio_codec': audio['codec_name']}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration, TypeError):
        raise VideoError('Unable to verify rendered MP4.') from None
