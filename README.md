# Football Shorts Factory — Milestones 1, 2 and 3

Python 3.12 CLI to retrieve a completed English Premier League fixture from Sportmonks Football API v3, validate it, and save raw and normalized JSON for downstream production. Milestone 1 retrieves and normalizes match data. Milestone 2 adds AI editorial selection, evidence-backed statistical analysis, and narration scripts. Milestone 3 generates WAV voice narration. Video rendering and publishing are not implemented.

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
