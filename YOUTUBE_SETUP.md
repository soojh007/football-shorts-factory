# Connect your YouTube channel

The finished video and private upload preview are ready locally. The application needs Google OAuth authorization to upload to your channel; your OpenAI and Sportmonks keys cannot provide that access.

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. In **APIs & Services → Library**, enable **YouTube Data API v3** for that project.
3. Configure the OAuth consent screen (Google Auth Platform). Set the app name and required contact details. If the app is in Testing, add the Google account that owns/manages your channel as a test user. Google may require additional consent configuration for the requested scopes.
4. Create an OAuth client ID with application type **Desktop app**. Download its JSON file.
5. Save that file on your Mac at:

   ```text
   /Users/soojh007/football shorts/secrets/youtube_client_secret.json
   ```

   Keep it private. Do not paste its contents into chat or commit it to GitHub. The secrets folder is already ignored.

6. In Terminal, run:

   ```sh
   cd "/Users/soojh007/football shorts"
   source .venv/bin/activate
   python -m backend.youtube_auth
   ```

   Sign in with the Google account for your intended YouTube channel and select that channel if prompted. The configured target is `UCw3H9KY5toxOuN7cSDsIKqA`. The app checks the authorized channel against this ID. If it differs, sign in again with the intended channel; do not change the target merely to bypass the check. Readonly permission is used to identify the channel; upload permission is used to upload video.

7. Prepare/review the local metadata:

   ```sh
   python -m backend.publish --fixture 19427552
   open -e generated/19427552_youtube_plan.json
   ```

8. After reviewing the video and metadata, upload privately:

   ```sh
   python -m backend.publish --fixture 19427552 --upload
   ```

   The command prints the accepted video URL and saves a receipt. Check processing and playback in [YouTube Studio](https://studio.youtube.com/). Public publishing is a separate explicit choice; the default upload stays private.

Troubleshooting:

- **No client file**: verify the Desktop app JSON filename and location, or set `YOUTUBE_CLIENT_SECRETS` in `.env`.
- **Access blocked/test user**: verify consent-screen setup, test-user membership, enabled API and Google project settings. Do not bypass Google restrictions.
- **Wrong channel**: run the auth command again and select the intended channel/account. Brand channels may require selecting the correct identity during Google sign-in.
- **Expired authorization**: run the auth command again. Refresh-token lifetime depends on Google's consent/project/account configuration.
- **Quota/access/processing error**: check the Cloud console and YouTube Studio. No live upload is assumed successful until a valid video ID is returned; acceptance still does not prove processing/playback.
- **Pending/uncertain upload record**: inspect Studio before any retry. A request can finish remotely even when its response is lost. Do not delete a reservation just to force another upload.

The default paths for OAuth secrets and refresh tokens are excluded from Git. If you override them, keep the chosen files private and ignored too. Follow the [official Google upload setup](https://developers.google.com/youtube/data/guides/uploading_a_video) if console labels change.
