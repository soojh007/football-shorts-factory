# Football Shorts Factory — Milestones 1–5

Python 3.12 CLI to retrieve a completed English Premier League fixture from Sportmonks Football API v3, validate it, and save raw and normalized JSON for downstream production. Milestone 1 retrieves and normalizes match data. Milestone 2 adds AI editorial selection, evidence-backed statistical analysis, and narration scripts. Milestone 3 generates WAV voice narration. Milestone 4 renders a captioned vertical MP4. Milestone 5 prepares YouTube metadata and provides an explicit OAuth-authorized upload command, private by default.

## Installation

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `SPORTMONKS_API_TOKEN` in `.env` or export it in your shell. Obtain a token with access to EPL fixture data from Sportmonks. No token is needed for tests. Existing environment variables take precedence over `.env`.

`EPL_LEAGUE_ID` defaults to **8**, the [documented Sportmonks Premier League ID](https://docs.sportmonks.com/v3/endpoints-and-entities/endpoints/leagues). `SPORTMONKS_INCLUDE_XG=false` is the default; set it to `true` only when your subscription includes expected goals. The `.env` file, fixture outputs, generated files, virtual environment, and Python caches are excluded from Git. Keep credentials out of command arguments, source, and logs.

## Usage

From the repository root:

```sh
python -m backend.main --fixture 19427552
```

The ID is illustrative; it must identify an accessible, completed EPL fixture. Use two ASCII hyphens in `--fixture`.

Options:

```sh
python -m backend.main --fixture 19427552 --epl-league-id 8 --include-xg
python -m backend.main --fixture 19427552 --output-dir data/fixtures
```

After successful retrieval and validation:

- `data/fixtures/19427552_raw.json` contains the response envelope, with any unexpected credential echo redacted.
- `data/fixtures/19427552_normalized.json` contains the stable schema below.

Each file is written through an atomic replacement. Re-running overwrites these files. Invalid fixtures produce no new output. The two replacements are not a single filesystem transaction; an I/O failure can leave only one updated file. Output defaults to the repository's data directory even when invoked elsewhere.

Illustrative console output (mock data, not a live API result):

```text
19427552: Home FC 2–1 Away FC (FT)
Available statistics: possession, total_shots
Saved raw and normalized JSON to .../data/fixtures
```

Illustrative normalized JSON:

```json
{
  "schema_version": 1,
  "fixture_id": 19427552,
  "league_id": 8,
  "season_id": 25583,
  "match_date": "2025-08-16T14:00:00",
  "home_team": {"id": 10, "name": "Home FC"},
  "away_team": {"id": 20, "name": "Away FC"},
  "final_score": {"home": 2, "away": 1},
  "match_status": "FT",
  "statistics": {
    "possession": {"home": 60.0, "away": 40.0},
    "total_shots": {"home": 12.0, "away": null},
    "shots_on_target": {"home": null, "away": null},
    "expected_goals": {"home": null, "away": null},
    "corners": {"home": null, "away": null},
    "yellow_cards": {"home": null, "away": null},
    "red_cards": {"home": null, "away": null}
  },
  "goal_events": [{"id": 1, "participant_id": 10, "side": "home", "type": "goal", "minute": 50, "extra_minute": null, "player_name": "A Player", "result": "1-0"}]
}
```

## API semantics and schema

The client requests `participants;scores;state;statistics.type;events.type`, plus `xGFixture.type` when opted in. Authentication uses the Sportmonks `Authorization` header and a 30-second timeout. No automatic retries consume additional quota. HTTP errors, rate limits, network failures, malformed JSON, missing data, and mismatched fixture IDs produce safe errors without response bodies or request exception details.

- [States](https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/includes/states): accept completion IDs 5 (`FT`), 7 (`AET`), and 8 (`FT_PEN`); reject breaks, live, postponed, abandoned, awarded, and walkover fixtures. Reject inconsistent included state metadata. EPL normally ends at FT; the other completion states follow v3 semantics.
- [Scores](https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/includes/scores): require two `CURRENT` entries. Map each by `participant_id` to participants' `meta.location`, cross-check `score.participant`, and reject missing/conflicting/duplicate scores. Never use half-only scores as final scores. `CURRENT` represents the match score; no separate penalty shootout score is modeled.
- [Statistics](https://docs.sportmonks.com/v3/definitions/types/statistics): use returned `type.code` (or developer name) to identify `ball-possession`, `shots-total`, `shots-on-target`, `expected-goals`, `corners`, `yellowcards`, and `redcards`. Numeric statistic IDs alone are never interpreted. Unknown types are ignored. Missing values remain `null`, including missing card counts; zero is retained when explicitly supplied. `red_cards` means the provider's straight red cards statistic, not second-yellow dismissals. Counts are validated as integral values but serialized as JSON numbers via the common float schema.
- [xG](https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/expected/includes): read `expected` from `xGFixture.type` and xG present in ordinary statistics. Missing subscription/coverage data remains `null` when omitted; explicit access errors fail clearly. Disable the option if the include is denied.
- [Events](https://docs.sportmonks.com/v3/definitions/types/events): retain `goal`, `owngoal`, and scored `penalty` types, excluding missed penalties and other types. Preserve provider attribution, source order, player, minute, stoppage minute, and result. Own-goal `side` is the provider's participant attribution, not an inferred scoring beneficiary. Events are not reconstructed from the score; absent events are `null`, an explicitly empty list is `[]`.

`match_date` preserves Sportmonks' kickoff timestamp in ISO format. No local timezone is invented for timestamps without an offset. Pydantic validates required IDs, date, teams, scores, statistics, and event shape. Provider data can be corrected later; rerun to refresh.

## Architecture

- `backend/sportmonks.py`: HTTP access and safe errors.
- `backend/validate.py`: source validation and Pydantic schema.
- `backend/normalize.py`: stable participant-based transformation.
- `backend/main.py`: environment, CLI, atomic JSON output, summary.
- `backend/__init__.py`: Python package marker; `backend/init.py` reserved as requested.
- `tests/`: mocked normalization, validation, API, and CLI/file-output tests.
- `data/fixtures/`, `generated/`: ignored output directories with tracked placeholders.

## Tests

```sh
source .venv/bin/activate
python -m pytest -q
```

Tests mock all HTTP requests and use synthetic credentials only. They cover completed matches, absent statistics, invalid fixture IDs, authentication/access failure, rate limiting, API/network failures, non-completed/non-EPL matches, participant/score mapping, goal events, xG, and CLI JSON output. A passing suite does not establish live API access.

## Troubleshooting

- Missing token: populate `.env` at the repository root, or export `SPORTMONKS_API_TOKEN`.
- Authentication/access denied: check the token and EPL/statistics/xG entitlements; turn off xG if unavailable.
- Fixture not found: verify the fixture ID and subscription coverage.
- Rate limited: wait for quota reset before retrying; the CLI does not loop automatically.
- Timeout/connectivity/API failure: check connectivity and Sportmonks service status, then retry.
- Not completed: select a finished fixture; scheduled/live/postponed fixtures are rejected.
- Not EPL: check the fixture's league; override `EPL_LEAGUE_ID` only for a deliberate configuration change.
- Missing optional metrics: `null` is expected when metadata/coverage is unavailable. No values are fabricated.
- Missing/invalid scores or teams: verify the fixture is fully populated upstream; normalization fails rather than guessing.
- Save failure: check output directory permissions and disk space. Exit status is 1 for runtime failures, 2 for invalid CLI arguments, and 0 on success.


## Milestone 2: analysis and narration

Generate a match summary and a narration script from the saved normalized JSON:

```sh
python -m backend.analyze --fixture 19427552
# Or supply an existing normalized JSON directly:
python -m backend.analyze --input data/fixtures/19427552_normalized.json
```

Add these entries to your existing `.env` (do not replace your Sportmonks token):

```dotenv
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

The OpenAI API credential is separate from your Sportmonks credential. Live analysis sends a verified fact inventory, including team names and match statistics, to OpenAI and may incur API charges. `--model` overrides `OPENAI_MODEL`; use a model supporting the Responses API and Structured Outputs. The configured default is `gpt-4o-mini`, not a claim about the newest available model. Authentication, access, quota, HTTP, timeout, refusal, incomplete-response, and invalid-output errors fail without logging response bodies or credentials. No automatic paid retries occur.

Outputs are written to the ignored `generated/` directory:

- `19427552_analysis.json`: summary, key points and source paths/values, limitations, narration, word count, timing estimate, model, and SHA-256 of the validated canonical source.
- `19427552_analysis_script.txt`: narration ready for editorial review.

Use `--output-dir` to change the destination. Repeated runs replace the corresponding files atomically per file, not as a two-file transaction. A failed API/validation run creates no new artifacts, but existing successful output is retained; an I/O failure can leave only one updated artifact.

To try the pipeline without an OpenAI key or any network call:

```sh
python -m backend.analyze --fixture 19427552 --offline-preview
```

This uses deterministic ordering and writes `19427552_preview.json` and `19427552_preview_script.txt`. It is labeled `offline_preview`, never `ai`, and does not overwrite AI artifacts. The saved Nottingham Forest–Manchester United fixture produced a 144-word preview, estimated at 57.6 seconds. This is an offline preview of live Sportmonks data, not a live OpenAI test.

### Factual controls and scope

The model's role is editorial: choose a hook style and rank up to four verified statistical facts. It does not write arbitrary publishable prose. The application always includes the final score, rejects duplicate/unknown/score-as-statistic selections, and renders the selected facts through fixed sentences. This produces a constrained statistical analysis rather than free-form tactical commentary. The integration follows the official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) and [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create).

Each match-specific sentence has exact evidence paths and values in `key_points`. Team attribution comes from normalized home/away identities. Missing values stay unavailable, explicit zero remains zero, and comparisons require both values. No scorers, goal chronology, momentum, formations, causal explanations, or league-table implications are inferred. Goal events remain in the source but are not used for analysis until event reconciliation is implemented. Straight red cards retain their Milestone 1 meaning.

The input is revalidated for schema, completion status, configured EPL league, distinct teams, statistic ranges and integral counts. The source hash covers the validated canonical JSON, not the original file bytes. The script targets 75–150 whitespace-separated words, estimated as 30–60 seconds at 150 words per minute. Actual speech timing varies; no audio has been generated or measured. Lower-ranked facts may be dropped to fit the budget, and only retained facts appear in `key_points`. Sparse data produces a score recap with explicit scope caveats, without filling missing statistics. All results require editorial review; correctness also depends on upstream data accuracy.

New modules: `backend/analysis.py` builds/verifies facts and assembles narration; `backend/openai_client.py` handles API selection; `backend/analyze.py` handles CLI and output. The Milestone 1 command remains unchanged. Run the full suite with `python -m pytest -q`; API tests are mocked and do not require either credential.

Troubleshooting: if `OPENAI_API_KEY` is missing, add it to `.env` or use `--offline-preview`. Check OpenAI API access/billing for authentication or quota failures. Invalid/unknown fact IDs or incomplete output are rejected rather than silently replaced by an offline result. If input validation fails, rerun the fixture ingestion command. Review limitations before using the script in production.

Live verification on 14 November 2026: the configured OpenAI API successfully generated analysis for fixture `19427552`. The saved script contained 145 words (estimated 58 seconds at 150 words/minute); schema, source evidence, script consistency, and credential checks passed. Actual audio duration remains unmeasured. The strict selection schema now constrains fact IDs and selection count in addition to application-side validation.


## Milestone 3: voice narration

Generate speech from the saved AI analysis (reuses `OPENAI_API_KEY`):

```sh
python -m backend.narrate --fixture 19427552
# Alternative source and voice:
python -m backend.narrate --input generated/19427552_analysis.json --voice coral --speed 1.0
```

Optional `.env` settings:

```dotenv
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=coral
OPENAI_TTS_SPEED=1.1
```

This sends the existing script to OpenAI's [Speech API](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create). It makes no new match analysis request, does not modify the script, and does not render or publish video. API usage may incur charges. The script must come from valid `ai` analysis JSON, contain at most 4096 characters, and agree with its word count and evidence sentences. Offline previews are not accepted for this command. No new dependencies beyond the existing requirements are needed.

Outputs in the ignored `generated/` directory:

- `19427552_narration.wav`: PCM WAV audio, suitable for later video rendering.
- `19427552_narration.json`: voice, speech model, speed, script/source/audio hashes, timestamp, actual sample count and duration, sample rate, channels, timing flag, and AI voice disclosure.

The script is spoken with an instructed British football presenter tone when using `gpt-4o-mini-tts`. This is a style instruction, not a guarantee of accent or verbatim delivery. Listen for pronunciation, omissions, additions, pacing and overall quality before production. Automated transcription/alignment is not part of this milestone.

The pipeline measures actual WAV PCM samples, not the earlier words-per-minute estimate. A duration outside 30–60 seconds is flagged for timing review; valid audio is retained without automatic paid retries, rewriting, or time stretching. Adjust `--speed` (0.25–4.0) or regenerate/review a shorter script explicitly. Supported Speech API models are `gpt-4o-mini-tts`, `tts-1`, and `tts-1-hd`; `instructions` are not sent for the latter two. Model and voice defaults are independently configurable from the analysis model.

Repeated runs reuse existing audio only when generation settings, script/source hashes, audio hash and measured metadata agree. Use `--force` to request regeneration even when matching audio exists. Changing speed or voice generates a replacement. Each file is atomically replaced individually; audio and metadata are not a single transaction. If a write fails, the next run will reject mismatched cache files. A failed API request leaves previous artifacts untouched.

The metadata and console include **“This narration uses an AI-generated voice.”** Carry this disclosure into the eventual video/player/publication as required by the [OpenAI speech guide](https://developers.openai.com/api/docs/guides/text-to-speech); metadata alone is not a disclosure to the eventual viewer.

**API lifecycle:** documentation checked on 14 November 2026 marks the Speech API models deprecated with shutdown scheduled for 6 January 2027 and recommends the Realtime API replacement. This milestone implements the currently supported Speech API workflow; its separate `SpeechClient` will need migration before shutdown. A Realtime model cannot simply be substituted into `OPENAI_TTS_MODEL` because it uses a different API workflow.

`backend/speech.py` contains API access, input checks, hashes and WAV inspection; `backend/narrate.py` contains CLI, caching and atomic output. Mock tests cover request bodies, credentials, HTTP/network errors, malformed/truncated WAV data, duration measurement, invalid settings, preview rejection, and cache reuse/force/corruption. Run `python -m pytest -q` without real credentials. For errors, check OpenAI billing/model access, input analysis JSON, voice and speed configuration, output permissions and connectivity. Error messages do not expose API bodies, keys or request exception details.

Live verification on 14 November 2026: fixture `19427552` generated a WAV with the `coral` voice. At speed 1.0 it measured 61.2 seconds and was flagged for timing review; at speed 1.1 the regenerated WAV measured 55.87 seconds, within target. The default CLI speed is 1.1. A repeat run reused the audio without another speech request. These are measured audio durations; pronunciation and delivery still require listening review. All 156 tests pass.


## Milestone 4: vertical video rendering

Install the updated Python requirements and FFmpeg (including `ffprobe` and the `libx264` encoder):

```sh
python -m pip install -r requirements.txt
# macOS, if FFmpeg is not installed:
brew install ffmpeg
python -m backend.render --fixture 19427552
```

This uses the existing normalized fixture, AI analysis, narration WAV and narration metadata. It does not regenerate analysis or speech. The first run sends the WAV to OpenAI's [Transcriptions API](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create) using `whisper-1`, `verbose_json` and word timestamps; it uses `OPENAI_API_KEY` and may incur transcription charges. Later renders reuse timestamps when audio/script hashes match. `--refresh-captions` explicitly requests fresh timestamps. No automatic paid retries or approximate whole-script timing fallback are performed.

The video is a graphic statistical recap: a persistent full-time score, team names, match date, home/away color mapping, changing statistic cards, short captions, progress indicator and a visible **AI-GENERATED VOICE** disclosure. Values come from the verified normalized fixture. Missing values display `N/A`, with no comparison bar when either value is missing. No match footage, music, team crests, new factual analysis or publishing is included.

Outputs (all ignored by Git):

- `generated/19427552_short.mp4`: 1080×1920 at 30 fps, H.264/yuv420p video and AAC audio with fast-start metadata.
- `generated/19427552_captions.srt`: timed captions preserving approved script text.
- `generated/19427552_captions.json`: cached transcription word timings, audio/script hashes, alignment coverage and caption scenes.
- `generated/19427552_poster.png`: opening frame.
- `generated/19427552_render.json`: output dimensions/codecs/duration, provenance hashes, caption coverage, cache-use flag, disclosure and editorial-review flag.

Optional directories:

```sh
python -m backend.render --fixture 19427552 --data-dir data/fixtures --artifacts-dir generated --output-dir generated
```

The renderer checks fixture identity, FT completion, configured EPL league, current source hash, exact analysis fact/evidence records, script/audio hashes and measured WAV metadata before a transcription request. Narration must be within 30–60 seconds. Source changes require regeneration of dependent artifacts. The captions preserve the original script instead of publishing transcription errors. Matching normalizes punctuation, case and integer spellings below 100; unmatched script words are interpolated between matching timestamps. Coverage must be at least 90 percent of the larger normalized token sequence. This is an alignment diagnostic, not a promise of perfect synchronization, pronunciation or factual speech accuracy. Caption boundaries are phrase-based and rounded onto the video frame grid. Review the full video before publication.

Pillow draws the frames directly; no browser or subtitle-font FFmpeg extension is required. A usable TrueType font is needed. macOS Arial Bold, common Linux DejaVu/Liberation fonts and Windows Arial Bold are detected. To override, set `VIDEO_FONT` to an installed `.ttf` file. Text wraps and shrinks within fixed margins; extremely long text that cannot fit is rejected. Original team-name glyph support depends on the font.

FFmpeg is invoked with an argument list, never a shell command. The controlled temporary concat manifest uses relative generated filenames; it contains no user-provided file directives. Encoding happens in a temporary directory. ffprobe checks dimensions, pixel format, codecs, frame rate, video stream duration and overall container duration before replacing the MP4. The explicit FPS conversion and final-frame hold prevent the still-image video stream from ending before the audio. Rendering requires a working FFmpeg installation with libx264/AAC; failure messages omit raw process/API content. Temporary files are cleaned up. The MP4, poster, SRT and metadata are replaced separately, not as a multi-file transaction; an I/O failure may leave mixed ancillary artifacts. Re-running uses cached valid timestamps and rebuilds outputs.

The Speech API lifecycle note above still applies. Documentation checked on 14 November 2026 also schedules `whisper-1` transcription shutdown for 26 February 2027. The separate `TranscriptionClient` will need migration to a timestamp-capable replacement before shutdown. It cannot be replaced with an arbitrary model name without checking its response schema and timestamp support.

Tests cover spoken-number alignment, preserved caption text, mismatch rejection, invalid/non-monotonic timestamps, API failures, SRT formatting, stale-source rejection, exact fact validation, cache hashes, graphic dimensions and a real one-second FFmpeg encoding/probing check when tools/fonts are available. The full mocked suite does not require live API credentials. The actual generated match video is a draft for listening and caption-timing review; YouTube publishing remains a separate milestone.

Live verification on 14 November 2026: fixture `19427552` rendered successfully as 1080×1920 H.264/yuv420p video at 30 fps with AAC audio. The container measured 55.87 seconds; the video stream measured 55.866667 seconds and audio 55.869917 seconds. Audio transcription aligned 98.0 percent of normalized tokens into 33 caption scenes. A repeat render reused the timestamp cache. Sample frames at the opening, two statistic cards and final caption were visually inspected for clipping and legibility. All 186 tests pass, including real FFmpeg encoding/probing. Full playback and listening review remain necessary before publishing.


## Milestone 5: YouTube upload

The upload integration is implemented and mocked-tested; a live upload requires authorizing your own YouTube channel. Start with [YOUTUBE_SETUP.md](YOUTUBE_SETUP.md) for the Google Cloud and Desktop OAuth steps. The provided channel ID is stored only in local `.env`.

```sh
python -m pip install -r requirements.txt
# Local preparation only: no Google sign-in or upload.
python -m backend.publish --fixture 19427552
# Explicit browser sign-in, after saving Desktop OAuth client credentials:
python -m backend.youtube_auth
# Upload the prepared video privately:
python -m backend.publish --fixture 19427552 --upload
```

Google OAuth credentials are separate from Sportmonks and OpenAI credentials. An API key alone cannot upload to a YouTube channel. Default local settings:

```dotenv
YOUTUBE_CLIENT_SECRETS=secrets/youtube_client_secret.json
YOUTUBE_TOKEN_FILE=secrets/youtube_token.json
YOUTUBE_CHANNEL_ID=your_UC_channel_identifier
```

The explicit auth command opens a local-loopback Google consent flow with `youtube.upload` and `youtube.readonly` scopes. Upload scope permits insertion; readonly scope allows verifying the exact authorized channel using `channels.list(mine=True)`. Tokens are saved atomically with mode 0600; the new secrets directory is created with mode 0700. Existing parent directory modes are not changed. Token refresh is supported; expired/revoked or insufficient authorization requires signing in again. The uploader never starts an interactive login unexpectedly. OAuth client files and refresh tokens are excluded from Git.

Before preparing metadata or uploading, the CLI verifies the original source chain, exact evidence records, source/script/audio/video hashes, actual MP4 stream properties, timing and recorded disclosure. The title and description are rebuilt from verified team names, final score and fact sentences. The default category is Sports (17), language English, and tags include football/Premier League/Shorts. The description discloses AI narration and identifies the statistics source. YouTube's `containsSyntheticMedia` is explicitly true. Audience defaults to not directed at children; use `--made-for-kids` when that is the correct audience designation.

`--privacy` accepts `private`, `unlisted` or `public`; default is always private. Specifying privacy without `--upload` only changes the local preview. An actual upload uses the explicit `--upload` flag and must match `YOUTUBE_CHANNEL_ID` exactly. Changing privacy or audience on an already-uploaded video is not implemented; use YouTube Studio. The current milestone does not schedule publication, set thumbnails, upload a separate caption track, poll processing status or guarantee YouTube's Shorts classification. Captions are already burned into the MP4; the local SRT remains available for manual use.

Outputs in the ignored artifacts directory:

- `19427552_youtube_plan.json`: concrete title, description, tags, privacy/audience/synthetic-media settings, target channel and verified video metadata. This does not indicate an upload occurred.
- `19427552_youtube_upload.json`: upload reservation or completed receipt, video ID/URL, source video hash, exact request body, requested/returned privacy and upload timestamp. A completed receipt means YouTube accepted the upload, not that processing, playback or public visibility was verified.

Uploads use 8 MB resumable chunks. Transient chunk failures are retried at most three times by the client library on the same in-process request; a new insert request is never started as an automatic retry. A file reservation is created exclusively before insertion so two local processes cannot upload simultaneously. A matching successful receipt returns the existing URL without another upload or Google API call. A receipt for changed media, metadata or channel blocks accidental re-upload. An interrupted/uncertain reservation also blocks a fresh insertion: check YouTube Studio first, because the remote upload might have finished even if the final response was lost. Resumable sessions are not persisted across process restarts. If receipt persistence fails, keep the reservation and reconcile it with Studio manually. Do not remove upload records blindly.

Google/YouTube account configuration, quota, API project status and platform processing can affect upload availability and visibility. The CLI always reports requested and returned visibility when available, suppresses raw API/credential exception text, and avoids subscriber notifications on insertion. Review processing, title, description, privacy, audience, synthetic-content disclosure, captions and playback in Studio before changing public visibility.

References: official [upload guide](https://developers.google.com/youtube/data/guides/uploading_a_video), [videos.insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert), and [channels.list](https://developers.google.com/youtube/data/reference/rest/v3/channels/list).

Validation on 14 November 2026: 206 tests pass, including private defaults, explicit visibility, channel mismatch prevention, resumable chunks, repeat-upload prevention, ambiguous upload failures, token permissions, local preview and missing credentials. The actual 55.87-second MP4 passed local upload preparation for the configured channel, with private visibility. No Google OAuth sign-in or live YouTube upload was performed because client credentials are not configured yet.

## International-friendly prediction videos

A separate forecast workflow now supports the requested **Friendly International competition (Sportmonks league ID 1082)** without requiring Sportmonks' paid Predictions add-on. The completed EPL recap remains unchanged and private on YouTube.

```sh
# Collect current pre-match data, build the forecast and script:
python -m backend.predict --fixture 19878000 --league-id 1082
# Also create speech, aligned captions and a local video:
python -m backend.predict --fixture 19878000 --league-id 1082 --render
# Reuse the saved source snapshot and cached narration/timestamps:
python -m backend.predict --fixture 19878000 --league-id 1082 --reuse-source --render
```

The selected first draft is **Japan vs Brazil**, fixture `19878000`, scheduled for **14 November 2026, 18:15 Singapore time** according to the retrieved Sportmonks fixture. This is a speculative forecast, not an actual final score. It is never uploaded by these commands. The existing completed-match uploader deliberately does not accept prediction artifacts; any future upload integration must preserve the forecast labels and metadata.

The collector retrieves the not-started fixture and participants, then paginates each team's prior 365 days of results in date windows no longer than 100 days. It retains only completed regulation-time results in the selected competition with kickoff strictly before the evidence cutoff, maps scores using participant IDs and `CURRENT` descriptions, deduplicates fixtures, and uses the latest five valid results. At least three results per team are required. The script and graphics state the actual sample size. Future/started/postponed fixtures cannot be presented as new pre-match predictions. With `--reuse-source`, the original evidence cutoff is retained, but the target kickoff is checked against the current clock so old snapshots cannot create retrospective predictions after kickoff.

Forecast method (`recent-form-poisson-v1`): shrink each team's scored/conceded goal average toward an explicitly assumed prior of **1.4 goals per team per game**, weighted as three prior games. This is an illustrative prior, not a measured league average. Average the team's smoothed scoring rate with the other team's smoothed conceding rate. No home boost is assumed (multiplier 1.0). An independent Poisson score grid from 0 to 15 goals per team produces exploratory home/draw/away probabilities, renormalized over retained mass. The outcome with the greatest total probability is selected, then the most probable score **conditional on that outcome** is used as the speculative score pick. The overall modal score can differ. Parameters, retained mass, rates and probabilities are saved for audit, but percentages are not displayed as calibrated confidence in the video.

This model is **not backtested or calibrated**. It does not adjust for opponent strength, venue-specific form, injuries, squad rotation, rest, transfers or confirmed lineups. Friendly-match samples can be sparse and cover many months. Goal-rate estimates are model outputs, not observed xG. An attractive score pick does not establish predictive accuracy; prospective evaluation against later results is needed before making accuracy claims. No betting recommendations or guaranteed outcomes are generated.

The source/results-only narration is assembled from verified counts and model output rather than free-form AI football claims. Speech uses the existing OpenAI configuration and may incur charges. Caption transcription also uses the existing API. Matching script/audio hashes reuse narration and timestamp caches; changed scripts regenerate dependent artifacts. The video has a distinct cream/coral design with country badges, alternating form cards, a clearly labeled prediction reveal, Singapore kickoff time, limitations and visible AI-voice/speculative-prediction disclosure. Unsupported country badges fall back to text. No match footage is used.

Files in ignored `generated/` include:

- `19878000_prediction_source.json`: raw fixture, historical fixture lists and evidence cutoff.
- `19878000_prediction.json`: matched form results, model assumptions, exploratory probabilities, score pick, limitations, sectioned script and review flag.
- `19878000_prediction_script.txt`, `_prediction_narration.wav`, `_prediction_narration.json`.
- `19878000_prediction_captions.json`, `_prediction_captions.srt`.
- `19878000_prediction.mp4`, `_prediction_poster.png`, `_prediction_render.json`.

The rendered prediction must use 30–60 second narration, pass audio-word alignment, and pass the same MP4 codec/dimension/duration checks as recap videos. The CLI does not start an upload. Inspect the draft's spoken team names, timing, current kickoff, evidence dates and speculative labels before use. Refresh data before release; cached source data is not a substitute for current team news.

Tests cover competition mapping, recent-form scores, deduplication, insufficient samples, future-result exclusion, rejection after kickoff, symmetric neutral forecasts, probabilities summing to one, consistency of the selected outcome/score, singular/plural narration, country-card rendering and requests without the paid predictions include. All 224 tests pass under Python 3.12. Live Sportmonks collection returned five recent friendlies per team for this draft: Japan 8 goals for/2 against and Brazil 17 for/6 against. The resulting exploratory pick is Japan 1–2 Brazil. Sample frames were visually inspected; model calibration and full subjective quality are not established by these checks.

Final draft verification: the revised Japan–Brazil forecast renders at **35.50 seconds**, 1080×1920 with H.264/AAC. The final caption transcription matches 100 percent of normalized script words after simplifying ambiguous narration; caption text exactly preserves the script. The score, form cards, Singapore kickoff and closing disclaimer were visually inspected. This checks media consistency, not model accuracy or subjective voice quality. The forecast has not been uploaded, and the earlier recap remains private.

Prediction graphics revision (style version 2): the Japan–Brazil draft now uses an animated football illustration, shared-scale goal bars, staged form badges, pitch graphics behind the score reveal and icon-based uncertainty callouts. Original graphic motion is sampled at 8 fps and encoded at 30 fps; caption boundaries are included in the frame timeline. The requested footer text and progress bar are removed. Narration, forecast, source evidence and caption text are unchanged and reused from cache without new API calls. The revised MP4 remains 35.50 seconds with 100 percent normalized-word caption alignment. Opening, bar-growth, completed-bar, score and caveat frames were visually inspected. All 224 tests pass. The versioned local preview is `generated/19878000_prediction_v2.mp4`; nothing was uploaded to YouTube.

## Match-to-video workflow with confirmed lineups

Start the local interface:

```sh
cd "/Users/soojh007/football shorts"
source .venv/bin/activate
python -m backend.dashboard
```

Open **http://127.0.0.1:8765**. Enter the teams (for example `Japan vs Brazil`) or a fixture ID, choose the fixture, and check its official starting elevens. Times are shown in Singapore time. The first version searches Friendly International (1082) fixtures over the next 21 days. Once ready, choose **Create video & upload privately** or **Create video only**. Keep the app running while the job finishes. The local interface is not an always-on hosted service; your Mac and the app must stay running.

The one-command equivalent is:

```sh
python -m backend.workflow --fixture 19878000
# Local video only:
python -m backend.workflow --fixture 19878000 --no-upload
```

The workflow is deliberately for your final-hour selection process. It requires `0 < time to kickoff <= 60 minutes`, a not-started fixture, an explicit Sportmonks `lineup-confirmed` metadata value of boolean true, and exactly 11 distinct valid starters for each participant. Expected lineups can be returned before the official teams; their mere presence never counts as confirmation. Type 572 (`lineup-confirmed`) and starting-player type 11 follow the verified Sportmonks definitions. If a lineup is missing, predicted, partial or inconsistent, the job stops in a waiting state before any paid generation. Refresh the official lineup check later; it does not automatically poll the provider. References: [lineups and formations](https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/lineups-and-formations), [confirmation metadata](https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/includes/tips-and-tricks).

The steps are kickoff/lineup verification, YouTube account preflight (when uploading), fresh historical match-fact collection, prediction/script assembly, confirmed team-sheet scenes, narration, audio-aligned captions, animated MP4 verification, final lineup/kickoff recheck, and private upload. The forecast weights historical performances by overlap with the confirmed XI, uses available historical player ratings, and applies a small explicit venue adjustment. The player-led video presents a conversational first-person take, with real player photographs, venue graphics, captions and a score reveal.

Cached narration, captions and finished video are reused only when matching content/settings/hashes allow it. Changed starters invalidate the video, while retrieval timestamps alone do not. Before upload, the current official XI and kickoff are fetched again; a lineup change, missing confirmation, elapsed kickoff or rescheduling stops the upload and asks you to rerun. The generated prediction title/description identify the international friendly, score pick, AI voice and model limitations. Upload visibility is fixed to **private** in this workflow. It cannot publish publicly, schedule a public release or silently change an existing video's visibility.

Prediction uploads use a separate `19878000_prediction_youtube_upload.json` receipt, so they cannot collide with the earlier recap receipt. Existing successful uploads are reused rather than duplicated; mismatched/uncertain receipts require Studio reconciliation just like the earlier uploader. A per-fixture file lock prevents simultaneous UI/CLI runs from writing over the same assets. If the process is killed, a stale `generated/.<fixture>_workflow.lock` can remain; confirm no job is still running before removing it. Interrupted remote uploads still require checking Studio before removing any upload receipt.

The interface runs only on loopback, checks the Host/Origin and requires a per-process CSRF token for job creation. Match input is passed to Python functions, not a shell command. Jobs execute serially with progress messages; exceptions shown in the interface are restricted to safe domain errors. Job snapshots are saved in ignored `generated/workflow_jobs/`, with a final `19878000_workflow_result.json` for completed runs. The current UI tracks jobs in memory while the app is running; a server restart does not resume a running job automatically. Rerun through the same workflow after checking any uncertain upload record. Account keys/OAuth credentials remain in the existing ignored local configuration.

Validation: all 243 tests pass, covering explicit lineup confirmation, incomplete/duplicate starting XIs, the final-hour gate, future-result safeguards, content hashes, private prediction metadata, no-upload behavior, account checks, lineup changes before upload and HTTP CSRF protection. Live read-only testing found Japan–Brazil and correctly returned a waiting status because it is more than an hour before kickoff; the provider had also returned 22 lineup rows with confirmation false. A live confirmed-lineup end-to-end upload has not been performed. Existing API, rendering and recap upload steps were live-tested separately in the earlier milestones.


## GitHub hosting

The cloud entry point is the [GitHub-hosted launch page](https://soojh007.github.io/football-shorts-factory/). It links to **Actions → Create prediction video → Run workflow**. Enter both team names or a Sportmonks fixture ID. Only repository writers can dispatch the job. The Pages site is a static launch page, not the Python dashboard; the Python/FFmpeg work runs on an ephemeral GitHub-hosted Ubuntu runner, so your Mac does not need to stay on.

Production runs use the same Friendly International, final-hour and official-XI checks, then create the video and upload privately. If the match is too early or lineups are not confirmed, the summary says Waiting and no generation/upload occurs. Rerun when official XIs are available. Start with enough lead time for GitHub's queue, dependency setup and rendering; the final pre-upload kickoff/lineup checks still apply. `validate_only` checks cloud setup and match readiness without paid generation or upload.

Repository Actions secrets are `SPORTMONKS_API_TOKEN`, `OPENAI_API_KEY` and `YOUTUBE_OAUTH_TOKEN_JSON` (the locally authorized Google credentials including refresh token); repository variable `YOUTUBE_CHANNEL_ID` selects the intended channel. Secrets are encrypted through GitHub's repository public key API and never committed to Git or put in the Pages HTML. OAuth refresh works on the runner; if Google expires/revokes the grant, reconnect locally and update the OAuth secret. This deployment uses existing account authorization, not a browser token pasted into the public site.

Manual production jobs are serialized. The existing upload receipts are encrypted before persistence, using a key derived with domain separation from the OAuth refresh token, and uploaded as a `factory-private-state` artifact retained for 90 days. The next job restores and verifies the newest artifact before starting. The public artifact contains only authenticated ciphertext; videos, scripts, raw snapshots and OAuth files are not published as artifacts. Rotating the OAuth refresh token invalidates the old encrypted state and fails closed until reconciled. Do not delete state/uncertain receipts to force another upload; check Studio first. A hard-cancel or runner loss during remote upload can still require manual reconciliation if state preservation did not finish. The 90-day artifact lifetime is not permanent record storage; new pre-match runs reject past kickoffs regardless.

GitHub logs and summaries omit private video URLs and script bodies; use [YouTube Studio](https://studio.youtube.com/) to review private uploads. The hosted workflow has no public-publishing option. No secrets are exposed to the test workflow or pull-request jobs. Official GitHub actions are pinned to resolved commit SHAs. GitHub Actions access, queueing, storage and quotas depend on the repository/account; OpenAI/Sportmonks usage retains its existing limits and charges.

The local dashboard remains available separately. It is not publicly exposed, tunneled, or served by GitHub Pages. References: [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site), [manual workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow), and [encrypted Actions secrets](https://docs.github.com/en/rest/actions/secrets). All 251 tests pass locally, including encrypted state isolation, token-rotation failure, unsafe archive paths, state-read failure, first-run recovery, and no-upload validation/waiting behavior.


## Match discovery, wider research and personal commentary

Use **Pull available matches** on the hosted launch page before choosing a match. Choose the next one or two hours, then copy the fixture ID into the production workflow. The list covers Friendly International (1082); it is a public schedule snapshot refreshed by GitHub Actions approximately every 15 minutes, subject to runner queues. The page shows its update time and warns about stale data. **Refresh on GitHub** dispatches a fresh snapshot. The local dashboard fetches directly when you press its discovery button. Discovery does not claim that lineups are confirmed; generation still requires official XIs in the final hour.

The production workflow now enriches the last five eligible friendlies with actual historical starting elevens and rating details. It requires at least three usable historical XIs per side. Recent performances are weighted by `0.35 + 0.65 * current-XI overlap / 11`, with a three-match prior at 1.4 goals per game. Historical ratings contribute only when at least six current starters have coverage. Missing ratings remain missing. A venue-country check and explicit neutral-venue metadata distinguish home soil from a neutral ground; unknown neutrality never earns a home bonus. The 6% home-soil and -3% visiting adjustments, rating coefficients, and prior are hand-set heuristics. This is an experimental, uncalibrated model, not demonstrated predictive accuracy. Opponent strength, weather and travel are not numerically modeled.

Sportmonks is no longer the only context source. Before generation, OpenAI Responses performs a required live internet search for the exact fixture, official announcements, team availability, venue and reliable reporting. `OPENAI_RESEARCH_MODEL` defaults to `gpt-4.1-mini`, using the existing OpenAI key. This adds API/search usage. A source ledger is saved alongside the prediction in ignored generated data. Claims must link to a URL returned by the search; future-dated and stale team news is discarded, undated reports remain unconfirmed, and conflicting venue evidence stops the job. Unsupported injuries and absences are never invented. Web reports inform narration and cross-checks rather than arbitrary numerical injury boosts. Empty verified news is explicitly acknowledged; an API/search failure stops generation.

The new video style uses a personal football-fan delivery, actual participating starters, animated player cards, XI continuity, a venue scene and a score reveal. It contains no footer. Real images are selected from matching Wikimedia Commons files with supported reuse metadata, with provider-linked player headshots as a fallback; no AI player likenesses are substituted. Source/artist/license records accompany each asset, and image credits and cited research URLs are included in private-upload descriptions. Provider fallback images depend on subscription media rights and can be low resolution. If no real image can be obtained for either team, rendering stops. All uploads remain private.

A style preview for a completed fixture must be labeled **DESIGN PREVIEW**, suppress its score pick, and must not be treated as a newly generated pre-match prediction. The production workflow always rejects fixtures after kickoff.

Latest validation: 267 automated tests pass locally. Live Sportmonks schedule and rich player/venue/history requests succeeded. A live external web search completed; no additional team-news claims passed the grounding checks in that probe, and the saved ledger records the gaps. A 1080×1920 style preview was rendered separately for the already completed Japan–Brazil fixture, clearly labeled as a design preview. No new prediction upload or public publication was performed for this update.
