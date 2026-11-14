"""Small, credential-safe Sportmonks Football API v3 client."""
import os

import requests


class SportmonksError(Exception):
    """Safe-to-display API/configuration failure."""


class SportmonksClient:
    BASE_URL = "https://api.sportmonks.com/v3/football/fixtures"
    INCLUDES = "participants;scores;state;statistics.type;events.type"

    def __init__(self, token=None, session=None, timeout=30, include_xg=False):
        self._token = token if token is not None else os.getenv("SPORTMONKS_API_TOKEN", "")
        if not self._token.strip():
            raise SportmonksError("Set SPORTMONKS_API_TOKEN in the environment or .env.")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.include_xg = include_xg

    def get_fixture(self, fixture_id):
        if type(fixture_id) is not int or fixture_id <= 0:
            raise SportmonksError("Fixture ID must be a positive integer.")
        includes = self.INCLUDES + (";xGFixture.type" if self.include_xg else "")
        try:
            response = self.session.get(
                f"{self.BASE_URL}/{fixture_id}",
                headers={"Authorization": self._token, "Accept": "application/json"},
                params={"include": includes}, timeout=self.timeout,
            )
        except requests.Timeout:
            raise SportmonksError("Sportmonks request timed out; try again.") from None
        except requests.RequestException:
            # Requests exceptions can contain authenticated URLs/headers. Never expose them.
            raise SportmonksError("Unable to connect to Sportmonks.") from None
        status = response.status_code
        if status in (401, 403):
            raise SportmonksError("Sportmonks authentication/access denied; check token and subscription.")
        if status == 429:
            raise SportmonksError("Sportmonks rate limit reached; wait before retrying.")
        if status == 404:
            raise SportmonksError("Fixture not found or not available on your subscription.")
        if not 200 <= status < 300:
            raise SportmonksError(f"Sportmonks API failed (HTTP {status}).")
        try:
            payload = response.json()
        except ValueError:
            raise SportmonksError("Sportmonks returned invalid JSON.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise SportmonksError("Sportmonks response is missing fixture data.")
        if payload["data"].get("id") != fixture_id:
            raise SportmonksError("Sportmonks returned a different fixture ID.")
        return self._redact(payload)

    def _redact(self, value):
        """Redact any unexpected credential echo before persistence or display."""
        if isinstance(value, str):
            return value.replace(self._token, "[REDACTED]")
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            return {self._redact(key): self._redact(item) for key, item in value.items()}
        return value
