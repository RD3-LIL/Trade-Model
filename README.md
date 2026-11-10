# Fantasy Trade Evaluator

Live site (GitHub Pages, after enabling Pages in Settings, main branch, root): https://rd3-lil.github.io/Trade-Model/

Build trade scenarios on the site: search and add players to Side A and Side B, pick league size 10 / 12 / 14 teams, see raw Sleeper ROS totals (v3, backtested), VOR, verdict and grades.

Half-PPR, redraft. Public Sleeper data only, no ESPN login.

## Data pulled (Nov 9-10, 2026)
Folder: `data/raw/`, about 43 MB total after Weeks 11-17 projections.
- `state_nfl.json`: Week 10, season 2026, display_week 9
- `players_nfl.json`: 12,229 players, 9,422 active
- `stats_2026_week01.json` to `stats_2026_week09.json`: 681 to 780 rows per week, actuals
- `stats_2026_season.json`: 3,306 rows
- `projections_2026_week10.json` to `projections_2026_week17.json`: about 3,300 rows per week, 411 to 511 with a half-PPR projection per week (only relevant fantasy players get one)
- `projections_2026_season.json`: 3,306 rows, with ADP half-PPR
- `trending_add.json`, `trending_drop.json`: 25 each

Scripts: `scripts/pull_sleeper.py`, `scripts/pull_ros_projections.py`
Re-pull with: `python3 scripts/pull_sleeper.py` then `python3 scripts/pull_ros_projections.py`

## Trade Evaluator v1
Script: `scripts/trade_evaluator.py`

Method:
- ROS window Weeks 10-17, half-PPR.
- ROS total = sum of Sleeper (Rotowire) `pts_half_ppr`, Weeks 10-17.
- Bye weeks = no opponent / no projection, counted as 0. Games = weeks with a projection.
- ROS PPG = ROS total / games.
- Actuals shown for context: Weeks 1-9 total, PPG, and last-3 (Weeks 7-9) PPG.
- Value over replacement (VOR) = (ROS PPG - replacement PPG) * games.
  Replacement is ROS PPG at the starter cutoff for a 12-team league: QB12, RB24, WR24, TE12, K12, DEF12.
  Computed from the data: QB 19.08 (Bryce Young), RB 10.11 (Braelon Allen), WR 10.98 (DeVonta Smith), TE 8.88 (Brenton Strange).
- Verdict is on VOR, not raw points, so a QB does not win a trade just by scoring a lot in 1QB.
- Grades on VOR diff: 40+ A, 25+ B+, 15+ B, 8+ C+, 3+ C, under 3 wash.

Usage:
```
python3 scripts/trade_evaluator.py "Player One" --vs "Player Two"
python3 scripts/trade_evaluator.py "Player One, Player Two" --vs "Player Three, Player Four"
python3 scripts/trade_evaluator.py --top RB 15
```


## Trade Evaluator v3.1 (Nov 10, 2026, 1 FLEX)

Default league has 1 FLEX (RB/WR/TE). Replacement fills positional starters first, then fills the 12 flex spots greedily with the best remaining RB/WR/TE. At 12 teams the flex fills are 8 WR + 4 RB, 0 TE.

12-team replacement, v3.1: QB 19.08 (Bryce Young, rank 12, unchanged), RB 9.48 (Travis Etienne Jr., rank 28, was 10.11 rank 24), WR 9.47 (Tre Tucker, rank 32, was 10.98 rank 24), TE 8.88 (Brenton Strange, rank 12, unchanged).


Note on negative VOR: most of the 519 players are negative, by design. Only the top 12 QBs, 28 RBs, 32 WRs, and 12 TEs are positive. A negative VOR means bench or waiver level, not worthless, and a trade can still be a win if your side is less negative.

## Trade Evaluator v3 (Nov 10, 2026, backtested)

Backtest: `scripts/backtest.py`, rolling predictions for Weeks 7-9, 692 player-weeks, no leakage (form and opponent defense use only prior weeks, projections are the pre-game Sleeper/Rotowire numbers, verified: corr 0.60-0.63 to actuals, not post-hoc).

| Method | MAE | Correlation |
|---|---|---|
| Raw Sleeper (v3) | 4.36 | 0.631 |
| Schedule-adjusted | 4.47 | 0.610 |
| Blend 35% form (old v2) | 4.38 | 0.619 |
| Blend 50% form | 4.40 | 0.614 |
| Form only | 4.67 | 0.566 |
| Season PPG only | 4.61 | 0.576 |

By position, raw MAE: QB 6.03, RB 4.74, WR 4.15, TE 3.38. Schedule adjustment was worse in every position, and crushed QB correlation (0.452 to 0.293). Top-50 projected per week: raw MAE 6.10, corr 0.315. Where blend and raw disagreed by 3+ pts, raw was better in 11 of 15 cases.

Conclusion: the v2 blend does not earn its keep, and the schedule factor hurts. v3 is raw Sleeper ROS, with form and schedule-adjusted totals kept in the data for transparency. Old blend is still available with `--blend` in `trade_evaluator_v2.py`.


Caveat: this backtest is only 3 weeks. The raw vs blend gap is small (0.02 MAE), so do not over-claim it. The schedule-factor harm is the more consistent signal, it lost in all 4 positions.

## Trade Evaluator v2 (Nov 10, 2026, no league data needed)
Script: `scripts/trade_evaluator_v2.py`

What v2 adds:
1. Configurable league: `--teams 10/12/14`, `--qb`, `--rb`, `--wr`, `--te`. Replacement rank = teams * starters. Default 12 teams, 1 QB / 2 RB / 2 WR / 1 TE. Replacement moves sensibly: RB24 is 11.14/g at 12 teams, 11.52/g at 10 teams (Chase Brown), 9.54/g at 14 teams (Cam Skattebo).
2. Blended ROS: 65% schedule-adjusted Sleeper + 35% form, where form = 60% last-3 PPG (Weeks 7-9) + 40% season PPG (Weeks 1-9). If fewer than 2 games in Weeks 7-9, form falls back to season PPG.
3. Schedule adjustment: each weekly projection multiplied by opp_allowed / league_avg_allowed for that position, capped 0.85 to 1.15. Opponent defense from actuals Weeks 1-9, in `data/derived/opponent_defense_vs_pos.json`. League averages allowed per team-game: QB 17.16, RB 19.6, WR 25.88, TE 11.13. Easiest RB defenses: NO 25.56, CAR 25.24, LV 24.13. Toughest RB: TB 13.44, JAX 15.24, DET 15.81.
4. Usage shown for context, not double-counted: touches/g = rush_att + rec, targets/g = rec_tgt, snap share = off_snp / tm_off_snp. Sleeper fields are sparse, missing counts as 0, so treat as directional.


## Honest limits
- Projections are Rotowire via Sleeper, not a backtested model yet. Blend weights (65/35, 60/40, cap 0.85-1.15) are starting points, not backtested.
- No injury, role change, or schedule strength adjustment beyond what Rotowire already bakes in, plus the v2 schedule factor above.
- No ESPN league data yet. That would need league ID plus espn_s2 and SWID cookies, copied by hand, never committed.
- League size and starting lineup are assumed 12-team, 1QB / 2RB / 2WR / 1TE / 1 FLEX by default in v2, configurable with --teams / --qb / --rb / --wr / --te.

## Next tailoring choices
- League size / lineup (10 vs 12 team, superflex, TE premium)
- Blend Sleeper projections with actuals (last-3, usage, snap share from nflverse)
- Add schedule strength / opponent defense vs position
- Weekly matchup win probability
- Waiver wire / start-sit view
- GitHub repo, public, code and method only, no private league data
