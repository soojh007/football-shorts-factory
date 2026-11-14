"""Confirmed starting XIs, never inferred from expected lineup presence."""
from backend.prediction import teams_for_preview
from backend.prematch import kickoff_utc


class LineupsNotReady(ValueError):
    """The user can refresh when official teams become available."""


def confirmed_lineups(fixture, now, league_id=1082):
    teams = teams_for_preview(fixture, now, league_id)
    minutes = (kickoff_utc(fixture) - now).total_seconds() / 60
    if minutes > 60:
        raise LineupsNotReady('This match starts more than an hour from now. Return within the final hour before kickoff.')
    metadata = fixture.get('metadata') or []
    flags = []
    for entry in metadata:
        kind = entry.get('type') or {}
        if kind.get('code') == 'lineup-confirmed' or entry.get('type_id') == 572:
            values = entry.get('values') or {}
            flags.append(values.get('confirmed') if isinstance(values, dict) else None)
    if not flags or any(flag is not True for flag in flags):
        raise LineupsNotReady('Starting lineups are not confirmed yet. Refresh after the official teams are announced.')
    result = {'confirmed': True, 'fixture_id': fixture['id'], 'checked_at': now.isoformat()}
    all_players = set()
    for side, team in teams.items():
        starters = []
        for entry in fixture.get('lineups') or []:
            if entry.get('team_id') != team['id'] or entry.get('type_id') != 11:
                continue
            player_id, name = entry.get('player_id'), entry.get('player_name')
            if type(player_id) is not int or player_id <= 0 or not isinstance(name, str) or not name.strip() or player_id in all_players:
                raise LineupsNotReady('Official team sheets are incomplete or inconsistent. Refresh before creating the video.')
            all_players.add(player_id)
            starters.append({'player_id': player_id, 'name': name.strip(), 'jersey_number': entry.get('jersey_number'),
                             'image_url': (entry.get('player') or {}).get('image_path'),
                             'position_id': entry.get('position_id')})
        if len(starters) != 11:
            raise LineupsNotReady('Both teams need exactly 11 confirmed starters. Refresh when the complete team sheets are available.')
        result[side] = {'team_id': team['id'], 'starters': starters}
    return result


def add_lineup_sections(prediction, lineups):
    import copy
    result = copy.deepcopy(prediction)
    result['lineups'] = lineups
    result['forecast']['limitations'] = [note for note in result['forecast']['limitations'] if not note.startswith('Lineups,')]
    result['forecast']['limitations'].append('Confirmed team sheets are displayed; individual player strength, injuries, rest and transfers are not modeled.')
    sections = result['sections']
    extra = [{'kind': f'lineup_{side}', 'text': f"{result['teams'][side]['name']}'s official starting eleven is confirmed. Here is the team sheet for this match."}
             for side in ('home', 'away')]
    sections[1:1] = extra
    sections[-1]['text'] = ('This remains an exploratory form forecast. The confirmed lineups are shown, '
        'but player strength and opponent quality are not modeled. In a friendly, changes in personnel can matter.')
    result['script'] = ' '.join(section['text'] for section in sections)
    result['word_count'] = len(result['script'].split())
    return result
