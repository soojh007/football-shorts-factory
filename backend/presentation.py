"""Versioned visual and narrator identities, selected before writing or rendering."""
VERSION = 'four-palettes-personalities-v1'
NARRATION_SPEED = 1.3
PALETTES = (
    dict(name='Stadium green', bg='#101814', text='#faf5e8', accent='#c2ff67', secondary='#ff8055',
         surface='#263a2c', orb='#193124', outline='#547660', pitch='#8eaf7d', shirt='#385c40', shadow='#050a07'),
    dict(name='Electric blue', bg='#071627', text='#f2f8ff', accent='#57e2ff', secondary='#ffc569',
         surface='#193650', orb='#102b45', outline='#477796', pitch='#8bbdd6', shirt='#245277', shadow='#030b14'),
    dict(name='Sunset cream', bg='#f5ecd9', text='#242337', accent='#73351c', secondary='#633f9c',
         surface='#e4d5bb', orb='#eadfc9', outline='#a78b67', pitch='#786347', shirt='#c4a780', shadow='#cdbb9e'),
    dict(name='Midnight violet', bg='#1a1029', text='#fff3fa', accent='#ffade0', secondary='#a5e7ff',
         surface='#382341', orb='#2c193d', outline='#87638e', pitch='#c6a0d1', shirt='#60396f', shadow='#0c0614'),
)
PERSONALITIES = (
    dict(name='The composed fan', gender='male', voice='cedar',
         writing='A composed, quietly assured male fan. Warm and direct; short personal observations, measured conviction, no hype or analytical boilerplate.',
         delivery='Use an adult male voice, warm mid-low register, relaxed confidence and deliberate emphasis. Sound like a thoughtful fan talking to one friend.'),
    dict(name='The lively supporter', gender='female', voice='coral',
         writing='A lively, sharp female football supporter. Bright and conversational, quick reactions and punchy sentences. Express excitement without shouting, invented drama or unsupported claims.',
         delivery='Use an adult female voice with bright, lively warmth, crisp emphasis and an upbeat conversational rhythm. No shouting or sportscaster cadence.'),
    dict(name='The wry matchday mate', gender='male', voice='ash',
         writing='A wry, down-to-earth male matchday mate. Dry, understated wit and compact conversational phrasing. No ridicule, invented anecdotes, cliches or forced jokes.',
         delivery='Use an adult male voice with a slightly textured register, dry understated warmth, easy pacing and small expressive pauses. No exaggerated comedy.'),
    dict(name='The assured challenger', gender='female', voice='marin',
         writing='An assured, incisive female football fan. Decisive personal opinions, thoughtful contrasts and a strong final verdict. Challenge the obvious only when the supplied evidence supports it; never force an upset.',
         delivery='Use an adult female voice with composed authority, clear articulation and confident conversational energy. Emphasize the football argument and finish decisively.'),
)


def selection(prediction):
    value=prediction.get('presentation') or {}
    indices=[value.get('palette_index',0),value.get('personality_index',0)]
    if any(type(i) is not int or not 0<=i<4 for i in indices):
        raise ValueError('Invalid video presentation identity.')
    return indices


def palette_for(prediction):
    return PALETTES[selection(prediction)[0]]


def personality_for(prediction):
    return PERSONALITIES[selection(prediction)[1]]


def choose_presentation(successful_uploads):
    if type(successful_uploads) is not int or successful_uploads<0:
        raise ValueError('Invalid successful upload count.')
    # Shift the voice pairing every four uploads: 16 combinations before repeating.
    p=successful_uploads%4
    v=(successful_uploads+successful_uploads//4)%4
    return dict(version=VERSION,palette_index=p,palette_name=PALETTES[p]['name'],
                personality_index=v,personality_name=PERSONALITIES[v]['name'])


def speech_settings(prediction):
    persona=personality_for(prediction)
    return dict(delivery=VERSION,voice=persona['voice'],speed=NARRATION_SPEED,
        instructions=('Read the supplied script exactly in English. Use a light, natural Singaporean English accent, '
        'clear to international listeners, consistent without exaggeration or caricature. '
        'Do not change words, add Singlish particles or use a newsreader tone. '+persona['delivery']))
