---
name: football-league-prediction
description: Build and review club football score forecasts using league-relative attack and defensive weakness, home/away expected goal rates, and an independent Poisson score matrix. Use for Football Shorts Factory prediction changes or explanations; preserve its separate FIFA national-team model.
---

# League score prediction

Use the repository's deterministic Python model rather than asking a language
model to invent numeric predictions. In Football Shorts Factory, read
`backend/league_poisson.py` and the relevant caller in
`backend/contextual_prediction.py` when changing a forecast. Read
`docs/league-poisson.md` for the data contract, matrix interpretation and limits.

For a worked probability example, run from that repository:

```bash
.venv/bin/python -m backend.league_poisson --home-rate 1.5 --away-rate 1.0
```

To estimate match rates, collect completed results from the target competition,
current season, and before the forecast cutoff. Use verified participant
home/away metadata and CURRENT final scores; exclude extra-time matches from the
90-minute scoring sample. Never use the target match's live or final score, a
future result, an unrelated competition baseline, or national FIFA rankings for
clubs. Deduplicate fixture IDs, excluding conflicting score duplicates.

Let mu_H and mu_A be measured league home and away goals per match. Divide the
home club's home scoring by mu_H and the away club's away conceding by mu_H.
Their product times mu_H is lambda_H. Divide away scoring and home conceding by
mu_A; their product times mu_A is lambda_A. A defence weakness greater than one
means more conceded, not better defending. Shrink small team samples toward the
matching measured baseline, and retain sample counts and source fixture IDs.

Missing venue information does not block a forecast: use designated fixture
home/away roles, without claiming verified physical home advantage. Explicitly
neutral fixtures use pooled team rates and the pooled league baseline. Do not
stack a second country/home multiplier on a league split. Preserve available
lineup evidence and disclose hand-set rating adjustments in model metadata.

Build each score cell as P_H(h) * P_A(a). Sum h>a for a home win, h=a for a draw,
and h<a for an away win. Use adequate adaptive support and report omitted tail
mass. Distinguish the overall modal score from a score selected conditional on
the most likely match outcome. Validate finite nonnegative lambdas, probability
sums, home/away reversal and the worked 1.5/1.0 example.

When measured league data are unavailable or inadequate, record the fallback
reason and use the existing verified recent-form model. Do not fabricate league
averages, block on missing optional data, or claim calibration without actual
chronological evaluation. Keep technical qualifications in evidence/metadata;
narration remains personal and ends with the unchanged selected score.

For retrospective tests, use `python -m backend.backtest` and a saved source
snapshot. Freeze training before the first match of the holdout round and exclude
all holdout fixture IDs. Strip target results and winner flags from model inputs;
do not reconstruct historical lineups or ratings from post-match information.
Compare with league-average and previous recent-form baselines, report every
match and probability metrics, and label reconstructed outputs as retrospective,
not archived pre-kickoff forecasts. Do not tune on the reported holdout.

Creating or reviewing a prediction does not itself authorize uploading or
publishing a video. Preserve existing private-upload and duplicate guards.
