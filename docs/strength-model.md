# International strength model v1

The previous production model clipped the FIFA-points contribution at ±0.35 in log goal rate. That understated large international mismatches. A preview with only one verified ranking did not apply even that modifier. The new fitted path requires comparable points for both teams; it never converts an ordinal rank difference into a goal difference or invents missing points.

For senior men's national teams, the fitted model is:

```
log(goal_rate) = intercept
              + beta_points * (own_FIFA_points - opponent_FIFA_points) / 600
              + beta_home * known_home_soil
              + beta_friendly * is_friendly
              + beta_form * log(shrunk_recent_goal_rate)
```

The fitted coefficients and full validation results are in `backend/models/fifa_strength_v1.json`. `known_home_soil` is +0.5 for the team in its own country, -0.5 for its opponent, and zero for neutral or unverified venue context. Runtime individual-rating factors remain separate heuristic overlays. Their accuracy is not established by the strength-model backtest.

## Data and time boundaries

Sources: [Mart Jürisoo's international results](https://github.com/martj42/international_results) and [Dato-Futbol's archived FIFA rankings](https://github.com/Dato-Futbol/fifa-ranking). Rankings are historical FIFA points scraped by the archive maintainer, not independently audited official snapshots. Source-file SHA-256 hashes are recorded in the artifact. Raw datasets are not redistributed in this repository.

Only the post-August-2018 FIFA point system is used. Each match joins the last ranking release **strictly before** its date, no older than 90 days. Same-day and future releases are excluded. Recent-form features use only prior matches in the same tournament, within 365 days, with the same three-match/1.4-goal shrinkage used by production. Missing ranking joins are excluded rather than fabricated. Results after 19 September 2024 never enter fitting or evaluation. No Singapore–Brazil 2026 outcome, including its halftime score, is used.

- Fit: 3,815 matches, 18 August 2018–30 December 2022.
- Chronological holdout: 1,468 matches, 2023–19 September 2024.
- Holdout friendlies: 378.
- Holdout gaps of at least 500 points: 91.

## Comparison with the previous capped-FIFA core

| Holdout group | Fixtures | Old margin MAE | New margin MAE | Old goals NLL | New goals NLL |
| --- | ---: | ---: | ---: | ---: | ---: |
| All | 1,468 | 1.367 | 1.345 | 2.910 | 2.825 |
| Friendlies | 378 | 1.357 | 1.322 | 2.916 | 2.836 |
| FIFA-point gap ≥500 | 91 | 2.184 | 1.881 | 3.272 | 2.837 |
| Gap <100 | 436 | 1.318 | 1.316 | 2.920 | 2.898 |

MAE measures expected goal-difference error; NLL measures the negative log likelihood of both actual goal counts. Lower is better. These comparisons cover the numerical core, without historical player ratings or lineup overlays. Large-gap margin MAE improved by approximately 14% versus the old cap. The large-gap group is still overestimated on average: predicted stronger-team margin 4.25 versus observed 3.23. This is a limitation, not a guarantee of correct wide-score calls.

This is retrospective chronological validation, not prospective proof, a calibrated betting probability, or a promise that a 140-place rank gap means a fixed score. The forecast keeps `calibrated: false`; fitted strength application and validation provenance are recorded separately. Snapshot dates/types must match, source observations must precede the forecast cutoff, and the entire validation period must precede that cutoff. Club fixtures and missing/incompatible rankings retain the available-information fallback. Beyond the historical point-gap range, a symmetric training-domain guard prevents uncontrolled extrapolation. The Poisson score grid expands for larger expected scores instead of truncating at 15.

## Reproduce

Download `results.csv` from the first source and `ranking_fifa_historical.csv` from the second, then run with Python 3.12:

```bash
python -m backend.calibrate_strength \
  --results /absolute/path/results.csv \
  --rankings /absolute/path/ranking_fifa_historical.csv \
  --output backend/models/fifa_strength_v1.json
```

The CLI records input hashes, date ranges, coefficients, missing-join counts and holdout metrics. It fails if the holdout is too small or the fitted model does not improve overall and large-gap goal NLL over the capped baseline. Production loads the bundled artifact locally; it does not retrain or download historical datasets for each video.

Media source/archive metadata and required attribution remain in the description and private evidence. The on-screen “Action photo · Archive” banner has been removed.
