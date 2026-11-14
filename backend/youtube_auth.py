"""Explicit Google Desktop OAuth sign-in and private local credential storage."""
import json
import os
from pathlib import Path
import sys
import tempfile

from dotenv import load_dotenv
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import google_auth_httplib2
from googleapiclient.discovery import build
import httplib2
from oauthlib.oauth2 import OAuth2Error

from backend.main import ROOT

SCOPES = ['https://www.googleapis.com/auth/youtube.upload',
          'https://www.googleapis.com/auth/youtube.readonly']


class YouTubeError(ValueError):
    """Safe-to-display YouTube authentication/upload failure."""


def configured_path(name, default):
    path = Path(os.getenv(name) or default).expanduser()
    return path if path.is_absolute() else ROOT / path


def save_token(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_credentials(*, login=False):
    token_path = configured_path('YOUTUBE_TOKEN_FILE', 'secrets/youtube_token.json')
    client_path = configured_path('YOUTUBE_CLIENT_SECRETS', 'secrets/youtube_client_secret.json')
    try:
        if login:
            if not client_path.is_file():
                raise YouTubeError('Download Google OAuth Desktop app credentials to secrets/youtube_client_secret.json, or set YOUTUBE_CLIENT_SECRETS.')
            config = json.loads(client_path.read_text(encoding='utf-8'))
            if not isinstance(config, dict) or not isinstance(config.get('installed'), dict):
                raise YouTubeError('Google OAuth credentials must use the Desktop app type.')
            flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
            credentials = flow.run_local_server(
                host='localhost', port=0, open_browser=True, timeout_seconds=300,
                authorization_prompt_message='Complete YouTube authorization in your browser.',
                success_message='YouTube authorization complete. You can close this window.',
                access_type='offline', prompt='consent')
        else:
            if not token_path.is_file():
                raise YouTubeError('YouTube is not connected. Run python -m backend.youtube_auth first.')
            credentials = Credentials.from_authorized_user_file(str(token_path))
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
        if not credentials or not credentials.valid or not credentials.has_scopes(SCOPES):
            raise YouTubeError('Google authorization is missing or expired; run python -m backend.youtube_auth again.')
        save_token(token_path, credentials.to_json())
        return credentials
    except YouTubeError:
        raise
    except (GoogleAuthError, OAuth2Error, OSError, ValueError, KeyError, TypeError):
        raise YouTubeError('Unable to authorize YouTube; check OAuth setup, consent and connectivity. No credentials were displayed.') from None


def youtube_service(credentials):
    try:
        transport = google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=60))
        return build('youtube', 'v3', http=transport, cache_discovery=False)
    except Exception:
        raise YouTubeError('Unable to initialize the YouTube API client.') from None


def main():
    load_dotenv(ROOT / '.env')
    try:
        credentials = load_credentials(login=True)
        from backend.youtube import current_channel
        service = youtube_service(credentials)
        try:
            channel = current_channel(service)
        finally:
            service.close()
        expected = os.getenv('YOUTUBE_CHANNEL_ID', '')
        if expected and channel['id'] != expected:
            raise YouTubeError('The authorized channel does not match YOUTUBE_CHANNEL_ID. Sign in to the intended YouTube channel.')
    except YouTubeError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    print(f"Connected YouTube channel: {channel['title']} ({channel['id']})")
    print('OAuth credentials saved locally; no video uploaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
