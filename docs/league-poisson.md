# League attack/defence Poisson model

Club predictions now use `league-attack-defence-poisson-v1` when adequate measured
league data are available. Senior national-team predictions retain the separate
FIFA points strength model. No national FIFA ranking is applied to clubs.

## Expected goal rates

The source is Sportmonks results from the **same league and current season** in
the 180 days before the forecast cutoff. Only completed FT matches with valid
CURRENT scores and participant home/away mapping enter the sample; extra-time,
wrong-season, future, target, malformed and conflicting duplicate results are
excluded. Repeated identical fixture IDs count once. The measured baseline needs
at least 10 usable fixtures and positive home/away scoring averages. These limits
and shrinkage are explicit engineering assumptions, not fitted hyperparameters.

Let `mu_H` be total home goals / league matches and `mu_A` be total away goals /
league matches. Each team's observed goal rate is shrunk toward its matching
baseline using three pseudo-matches:

```text
shrunk_rate = (weighted_goals + 3 * matching_baseline) / (effective_matches + 3)

home_attack   = home club's home scoring rate / mu_H
away_defence  = away club's away conceding rate / mu_H
away_attack   = away club's away scoring rate / mu_A
home_defence  = home club's home conceding rate / mu_A

lambda_home = mu_H * home_attack * away_defence
lambda_away = mu_A * away_attack * home_defence
```

A defensive weakness above one means **more conceded** than the league baseline.
Notice that away conceding is divided by `mu_H`, while home conceding is divided
by `mu_A`. Zero observations in a particular team role produce strength one by
shrinkage, not an invented zero scoring rate. The existing verified recent-form
requirement still applies to the overall prediction.

Available lineup continuity weights are used only for matching observations in
this sample; other observations have weight one. The existing bounded player
rating factor can modify the resulting lambdas. Those overlays remain hand-set
and are reported separately. Source fixture IDs, sample counts, effective counts,
weighted goals, baseline averages and unadjusted lambdas are recorded in
`forecast.assumptions.league_strength_model`.

Missing stadium data does not block this model. It uses statistical designated
home/away fixture roles without claiming verified physical home-ground advantage.
An explicitly neutral fixture pools each team's home and away results and uses
`(mu_H + mu_A) / 2` for both baselines. No additional country/home multiplier is
stacked on top of the league home/away split. Conflicting venue research excludes
that venue context, as before.

## Score matrix and match outcomes

For goal count `k`, `P(k) = exp(-lambda) * lambda**k / factorial(k)`. Assuming
independent team goal counts, each matrix cell is `P_H(h) * P_A(a)`.
Rows are home goals; columns are away goals.

- Home win: sum cells where `h > a`.
- Draw: sum cells where `h == a`.
- Away win: sum cells where `h < a`.

The grid expands until each marginal retains at least `1 - 1e-12` probability,
with at least 0–15 goals represented. Cell probabilities remain unconditional;
outcome probabilities and displayed score probabilities are normalized by retained
mass. Retained and omitted tail mass are recorded. Invalid/non-finite lambdas or
rates above the implementation's numerical bound of 100 fail explicitly rather
than being silently capped.

The overall modal score is reported separately from `score_pick`. For consistency
with existing narration, `score_pick` is the most likely exact score **conditional
on the most likely match outcome**. Those two scores need not be identical.

For `lambda_home=1.5` and `lambda_away=1.0`:

| Quantity | Probability |
|---|---:|
| 0–0 | 8.2085% |
| Home win | 48.7946% |
| Draw | 25.9847% |
| Away win | 25.2207% |

Reproduce without any token or network:

```bash
python -m backend.league_poisson --home-rate 1.5 --away-rate 1.0
python -m backend.league_poisson --home-rate 1.5 --away-rate 1.0 --output generated/example_matrix.json
```

## Availability, skill and limits

The pipeline retrieves the league sample through the same authenticated API
client with bounded transient retries. An unavailable/inadequate optional league
sample uses the existing recent-form fallback and records the reason. Authentication
and fixture identity errors still fail explicitly. Neither a missing venue nor
missing confirmed lineups blocks generation.

This model has formula/regression tests and live data-access checks; it is **not
chronologically backtested or calibrated**. Goal independence misses low-score
correlation, and small or promoted-team samples remain uncertain. There is no
fitted opponent-quality, travel or weather model. Do not imply model goal rates
are measured xG statistics. Technical limitations belong in evidence/description,
not repetitive spoken disclaimers.

The reusable Codex skill is versioned at
`skills/football-league-prediction/SKILL.md` and installed locally at
`~/.codex/skills/football-league-prediction/SKILL.md`. The cloud workflow executes
the tested Python model directly; numerical results are not invented by an LLM.
