"""Pre-match evidence collection without paid prediction add-ons."""
from datetime import datetime, timezone

from backend.sportmonks import SportmonksClient, SportmonksError


class PrematchClient(SportmonksClient):
    """Use only documented fixture endpoints; never infer unavailable predictions."""

    def fixture_request(self, suffix, *, includes, page=1, league_id=8, resource="fixtures"):
        if resource not in ('fixtures','leagues'): raise SportmonksError('Unsupported football resource.')
        params = {'page': page, 'per_page': 50}
        if includes: params['include']=includes
        base=self.BASE_URL.rsplit('/',1)[0]+'/'+resource
        if suffix.startswith('between/') and league_id is not None:
            params['filters'] = f'fixtureLeagues:{league_id}'
        try:
            response = self.session.get(f'{base}/{suffix}'.rstrip('/'),
                headers={'Authorization': self._token, 'Accept': 'application/json'},
                params=params, timeout=self.timeout)
        except Exception:
            raise SportmonksError('Unable to retrieve pre-match data from Sportmonks.') from None
        if response.status_code in (401, 403):
            raise SportmonksError('Sportmonks access denied for pre-match data; check subscription coverage.')
        if response.status_code == 429:
            raise SportmonksError('Sportmonks rate limit reached; wait before retrying.')
        if response.status_code != 200:
            raise SportmonksError(f'Sportmonks pre-match request failed (HTTP {response.status_code}).')
        try:
            payload = response.json()
        except ValueError:
            raise SportmonksError('Sportmonks returned invalid pre-match JSON.') from None
        if not isinstance(payload, dict):
            raise SportmonksError('Sportmonks returned invalid pre-match data.')
        return self._redact(payload)

    def subscribed_leagues(self):
        leagues={}
        for page in range(1,201):
            payload=self.fixture_request('',includes='country',page=page,league_id=None,resource='leagues')
            rows=payload.get('data')
            if not isinstance(rows,list): raise SportmonksError('Sportmonks returned no usable competition list.')
            for row in rows:
                if not isinstance(row,dict) or type(row.get('id')) is not int or not row.get('name'):
                    raise SportmonksError('Sportmonks returned an invalid competition.')
                leagues[row['id']]={'id':row['id'],'name':row['name'],'country':(row.get('country') or {}).get('name')}
            if not (payload.get('pagination') or {}).get('has_more'):
                return sorted(leagues.values(),key=lambda row:(row['name'],row['id']))
            if not rows: break
        raise SportmonksError('Competition pagination did not finish.')

    def upcoming_fixture(self, fixture_id):
        if type(fixture_id) is not int or fixture_id <= 0:
            raise SportmonksError('Fixture ID must be a positive integer.')
        payload = self.fixture_request(str(fixture_id), includes='participants;state;league')
        if not isinstance(payload.get('data'), dict) or payload['data'].get('id') != fixture_id:
            raise SportmonksError('Pre-match fixture is missing or has a different ID.')
        return payload

    def fixture_window(self, start, end, *, team_id=None, league_id=8):
        if start > end or (end - start).days > 99:
            raise SportmonksError('Fixture date window must be ordered and at most 100 days.')
        if team_id is not None and (type(team_id) is not int or team_id <= 0):
            raise SportmonksError('Team ID must be a positive integer.')
        suffix = f'between/{start.isoformat()}/{end.isoformat()}'
        if team_id is not None:
            suffix += f'/{team_id}'
        fixtures, seen = [], set()
        page = 1
        while True:
            previous_count=len(seen)
            payload = self.fixture_request(suffix, includes='participants;scores;state;league', page=page, league_id=league_id)
            data = payload.get('data')
            if not isinstance(data, list):
                raise SportmonksError('Sportmonks returned no usable fixture list.')
            for fixture in data:
                if not isinstance(fixture, dict) or type(fixture.get('id')) is not int:
                    raise SportmonksError('Sportmonks returned invalid fixture list entries.')
                if fixture['id'] not in seen:
                    fixtures.append(fixture)
                    seen.add(fixture['id'])
            more = (payload.get('pagination') or {}).get('has_more', False)
            if not more:
                break
            if not data or len(seen)==previous_count or page >= 200:
                raise SportmonksError('Fixture pagination did not finish; no incomplete form sample will be used.')
            page += 1
        return fixtures


def kickoff_utc(fixture):
    stamp = fixture.get('starting_at_timestamp')
    if type(stamp) in (int, float):
        try:
            return datetime.fromtimestamp(stamp, timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    value = fixture.get('starting_at')
    try:
        date = datetime.fromisoformat(value)
        return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise SportmonksError('Fixture kickoff time is missing or invalid.') from None
