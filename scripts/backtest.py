#!/usr/bin/env python3
"""
Backtest for the Trade Evaluator v2 blend.

Question: does blending Sleeper (Rotowire) projections with recent form,
and schedule-adjusting them, actually predict next-week actual points
better than the raw projection alone?

Design (no leakage):
- Target weeks: 7, 8, 9. For each target week w, only data from weeks
  1..w-1 is used for form and opponent defense.
- Sleeper projections for week w are the pre-game projections served by
  the Sleeper API now (verified: correlation to actuals 0.60-0.63, MAE
  ~4.2, bias -0.2 to -0.7, so they are genuine pre-game forecasts, not
  post-hoc actuals).
- Form PPG = 0.6 * last-3 PPG + 0.4 * season PPG, using prior weeks only.
  If fewer than 2 games in the last 3, form = season PPG (same rule as v2).
- Schedule factor: opponent allowed pts/game to that position, from
  prior-weeks actuals only, divided by league average allowed, capped
  0.85-1.15 (same rule as v2). Opponent comes from the projection row.
- Candidates evaluated per player-week (only players with both a
  projection and an actual that week):
    raw        = Sleeper projection
    sched      = raw * schedule factor
    blend_f    = (1-f) * sched + f * form, for f in 0, 0.2, 0.35, 0.5, 0.65, 1.0
    season_ppg = prior season PPG alone (naive baseline)
    last3_ppg  = prior last-3 PPG alone (naive baseline)
- Metrics: MAE, bias (pred - actual), correlation, pooled over Weeks 7-9,
  overall and by position (QB/RB/WR/TE). Also the same for the top-50
  projected players each week (the fantasy-relevant subset).

Usage: python3 scripts/backtest.py
"""
import json, math, os
from collections import defaultdict

BASE = os.path.expanduser("~/workspace/fantasy-football-model/data/raw")
TARGET_WEEKS = [7, 8, 9]
POSITIONS = ["QB", "RB", "WR", "TE"]

def load(path):
    with open(path) as f:
        return json.load(f)

def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx = sum(xs) / n; my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else float("nan")

def mae(preds, actuals):
    return sum(abs(p - a) for p, a in zip(preds, actuals)) / len(preds)

def bias(preds, actuals):
    return sum(p - a for p, a in zip(preds, actuals)) / len(preds)

players = load(os.path.join(BASE, "players_nfl.json"))

# actuals: pid -> {week: pts}, and opponent defense inputs
actual_by_week = {}   # week -> {pid: pts}
actual_rows = {}      # week -> list of rows (for opponent defense)
for w in range(1, 10):
    rows = load(os.path.join(BASE, f"stats_2026_week{w:02d}.json"))
    actual_by_week[w] = {}
    actual_rows[w] = rows
    for r in rows:
        pts = r.get("stats", {}).get("pts_half_ppr")
        if pts is not None:
            actual_by_week[w][r.get("player_id")] = pts

# projections: week -> {pid: (pts, opponent)}
proj_by_week = {}
for w in range(1, 10):
    rows = load(os.path.join(BASE, f"projections_2026_week{w:02d}.json"))
    proj_by_week[w] = {}
    for r in rows:
        pts = r.get("stats", {}).get("pts_half_ppr")
        if pts is not None:
            proj_by_week[w][r.get("player_id")] = (pts, r.get("opponent"))

def opponent_defense(prior_weeks):
    """team -> pos -> allowed pts per team-game, from prior actuals only.
    Allowed = sum of pts scored against that team at that position, divided
    by number of games that team played (approx: weeks in prior set where
    the team appears in the stats file). We approximate games played as the
    count of distinct weeks where any player on that team has a stat row.
    Simpler and robust: allowed per game = total allowed / number of
    prior weeks in which that team had a game (bye weeks excluded by
    checking if the team appears at all that week)."""
    # team of each player
    team_of = {}
    for pid, p in players.items():
        team_of[pid] = p.get("team")
    # opponent of a player in a given week: from stats rows, opponent field
    allowed = defaultdict(lambda: defaultdict(float))  # team -> pos -> total pts allowed
    games = defaultdict(int)  # team -> games played in prior weeks
    for w in prior_weeks:
        teams_seen = set()
        for r in actual_rows[w]:
            s = r.get("stats", {})
            pts = s.get("pts_half_ppr")
            if pts is None:
                continue
            opp = r.get("opponent")
            pos = r.get("player", {}).get("position")
            if opp and pos in POSITIONS:
                allowed[opp][pos] += pts
            tm = team_of.get(r.get("player_id"))
            if tm:
                teams_seen.add(tm)
        for tm in teams_seen:
            games[tm] += 1
    league_avg = {}
    for pos in POSITIONS:
        totals = [allowed[tm][pos] / games[tm] for tm in games if games[tm] and allowed[tm][pos] > 0]
        league_avg[pos] = sum(totals) / len(totals) if totals else 0
    return allowed, games, league_avg

def sched_factor(opp, pos, allowed, games, league_avg):
    if not opp or pos not in league_avg or not league_avg[pos]:
        return 1.0
    g = games.get(opp, 0)
    if not g:
        return 1.0
    f = (allowed[opp][pos] / g) / league_avg[pos]
    return max(0.85, min(1.15, f))

def form_ppg(pid, prior_weeks, target_week):
    """0.6*last3 + 0.4*season, prior weeks only. last3 = weeks target-3..target-1."""
    season_pts = []
    last3_pts = []
    for w in prior_weeks:
        pts = actual_by_week[w].get(pid)
        if pts is not None:
            season_pts.append(pts)
            if w >= target_week - 3:
                last3_pts.append(pts)
    if not season_pts:
        return None
    season = sum(season_pts) / len(season_pts)
    if len(last3_pts) < 2:
        return season
    last3 = sum(last3_pts) / len(last3_pts)
    return 0.6 * last3 + 0.4 * season

def season_ppg(pid, prior_weeks):
    pts = [actual_by_week[w][pid] for w in prior_weeks if pid in actual_by_week[w]]
    return sum(pts) / len(pts) if pts else None

# collect predictions
methods = ["raw", "sched", "blend_0.20", "blend_0.35", "blend_0.50", "blend_0.65", "form_only", "season_ppg", "last3_ppg"]
records = []  # dicts: week, pid, pos, actual, {method: pred}
for w in TARGET_WEEKS:
    prior = list(range(1, w))
    allowed, games, league_avg = opponent_defense(prior)
    for pid, (proj, opp) in proj_by_week[w].items():
        act = actual_by_week[w].get(pid)
        if act is None:
            continue
        p = players.get(pid, {})
        pos = p.get("position")
        if pos not in POSITIONS:
            continue
        form = form_ppg(pid, prior, w)
        season = season_ppg(pid, prior)
        if form is None:
            continue  # no prior actuals, cannot form-blend; skip for fair comparison
        sf = sched_factor(opp, pos, allowed, games, league_avg)
        sched = proj * sf
        # last3 alone
        last3_pts = [actual_by_week[ww][pid] for ww in range(max(1, w - 3), w) if pid in actual_by_week[ww]]
        last3 = sum(last3_pts) / len(last3_pts) if last3_pts else season
        preds = {
            "raw": proj,
            "sched": sched,
            "blend_0.20": 0.80 * sched + 0.20 * form,
            "blend_0.35": 0.65 * sched + 0.35 * form,
            "blend_0.50": 0.50 * sched + 0.50 * form,
            "blend_0.65": 0.35 * sched + 0.65 * form,
            "form_only": form,
            "season_ppg": season,
            "last3_ppg": last3,
        }
        records.append({"week": w, "pid": pid, "pos": pos, "actual": act, "proj": proj, "preds": preds})

print(f"Backtest: {len(records)} player-weeks, Weeks {TARGET_WEEKS}, positions {POSITIONS}")
print(f"Players with prior actuals only; no target-week data used in any predictor.")
print()

def report(subset, label):
    print(f"--- {label} (n={len(subset)}) ---")
    print(f"{'method':<12} {'MAE':>6} {'bias':>6} {'corr':>6}")
    for m in methods:
        preds = [r["preds"][m] for r in subset]
        acts = [r["actual"] for r in subset]
        print(f"{m:<12} {mae(preds, acts):6.2f} {bias(preds, acts):6.2f} {corr(preds, acts):6.3f}")
    print()

report(records, "All positions, Weeks 7-9 pooled")
for pos in POSITIONS:
    report([r for r in records if r["pos"] == pos], f"{pos} only")
# fantasy-relevant: top 50 projected per week
top = []
for w in TARGET_WEEKS:
    wk = [r for r in records if r["week"] == w]
    wk.sort(key=lambda r: r["proj"], reverse=True)
    top.extend(wk[:50])
report(top, "Top 50 projected per week (fantasy-relevant)")

# Biggest blend vs raw errors: does the blend overreact when form and projection disagree?
print("--- Blend 0.35 vs raw: where they disagree most ---")
rows = []
for r in records:
    gap = abs(r["preds"]["blend_0.35"] - r["preds"]["raw"])
    err_blend = abs(r["preds"]["blend_0.35"] - r["actual"])
    err_raw = abs(r["preds"]["raw"] - r["actual"])
    rows.append((gap, r, err_blend, err_raw))
rows.sort(key=lambda x: x[0], reverse=True)
for gap, r, eb, er in rows[:10]:
    p = players.get(r["pid"], {})
    name = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
    print(f"  {name} ({r['pos']}) W{r['week']}: raw {r['preds']['raw']:.1f} blend {r['preds']['blend_0.35']:.1f} actual {r['actual']:.1f} | err raw {er:.1f} blend {eb:.1f}")
big = [x for x in rows if x[0] >= 3.0]
if big:
    print(f"  n with |blend-raw| >= 3.0: {len(big)}; blend better in {sum(1 for _,_,eb,er in big if eb < er)}, raw better in {sum(1 for _,_,eb,er in big if er < eb)}, tie in {sum(1 for _,_,eb,er in big if eb == er)}")
print()
print("Interpretation: lower MAE is better. Bias near 0 is better. Higher correlation is better.")
print("If blend_0.35 MAE is not clearly below raw MAE, the v2 blend is not earning its keep.")
