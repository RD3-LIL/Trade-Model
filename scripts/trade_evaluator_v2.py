#!/usr/bin/env python3
"""
Trade Evaluator v2
Half-PPR, Sleeper (Rotowire) projections, ROS Weeks 10-17, 2026.
No ESPN league data needed. Everything below is from public Sleeper data.

What v2 adds over v1:
1. Configurable league: --teams, --qb, --rb, --wr, --te
   Replacement rank = teams * starters at that position.
   Default 12 teams, 1 QB / 2 RB / 2 WR / 1 TE, same as v1.
2. v3 default (Nov 10, 2026 backtest): RAW Sleeper ROS, no blend, no schedule
   adjustment. Backtest Weeks 7-9 (692 player-weeks, no leakage): raw MAE 4.36,
   corr 0.631, best overall. Schedule adjustment hurt in every position
   (MAE 4.47, corr 0.610) and the 35% form blend was a wash at best
   (blend_0.35 MAE 4.38, corr 0.619; where blend and raw disagreed by >=3
   pts, raw was better in 11 of 15 cases). Use --blend to re-enable the
   old v2 blend (65% schedule-adjusted Sleeper + 35% form) for comparison.
   Old v2 blend, for reference:
   - Schedule-adjusted ROS: each weekly projection is multiplied by
     opp_allowed / league_avg_allowed for that position, capped 0.85 to 1.15.
     Opponent defense is from actuals Weeks 1-9, saved in
     data/derived/opponent_defense_vs_pos.json.
   - Form: 0.6 * last-3 PPG (Weeks 7-9) + 0.4 * season PPG (Weeks 1-9).
     If a player has fewer than 2 games in Weeks 7-9, form = season PPG.
   - Blended PPG = 0.65 * schedule-adjusted ROS PPG + 0.35 * form PPG
   - Blended ROS total = blended PPG * games with a projection
   VOR is computed from blended PPG, with replacement recomputed from
   blended PPG rankings at the configured league size.
3. Usage shown for context (not double-counted in the blend):
   touches per game = rush_att + rec, targets per game = rec_tgt,
   snap share = off_snp / tm_off_snp, averaged Weeks 1-9 and last 3.
   Sleeper stat fields are sparse, missing fields count as 0, so treat
   usage as directional, not exact.

Usage:
  python3 trade_evaluator_v2.py "Player One" --vs "Player Two"
  python3 trade_evaluator_v2.py "Player One, Player Two" --vs "Player Three, Player Four" --teams 10
  python3 trade_evaluator_v2.py --top RB 15 --teams 12
  python3 trade_evaluator_v2.py "Player One" --vs "Player Two" --no-blend --no-schedule
    (reproduces v1, pure Sleeper ROS)
"""
import json, os, sys, argparse
from collections import defaultdict

BASE = os.path.expanduser("~/workspace/fantasy-football-model/data/raw")
DERIVED = os.path.expanduser("~/workspace/fantasy-football-model/data/derived")
WEEKS_ROS = list(range(10, 18))
WEEKS_ACTUAL = list(range(1, 10))

def load_json(path):
    with open(path) as f:
        return json.load(f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("side_a", nargs="?", default=None)
    ap.add_argument("--vs", dest="side_b", default=None)
    ap.add_argument("--top", nargs=2, metavar=("POS", "N"), default=None)
    ap.add_argument("--teams", type=int, default=12)
    ap.add_argument("--qb", type=int, default=1)
    ap.add_argument("--rb", type=int, default=2)
    ap.add_argument("--wr", type=int, default=2)
    ap.add_argument("--te", type=int, default=1)
    ap.add_argument("--flex", type=int, default=1, help="flex spots, RB/WR/TE, default 1")
    ap.add_argument("--blend", action="store_true", help="re-enable old v2 blend: 65% schedule-adjusted Sleeper + 35% form")
    ap.add_argument("--no-blend", action="store_true", help="pure Sleeper ROS (now the default)")
    ap.add_argument("--no-schedule", action="store_true", help="skip opponent adjustment")
    args = ap.parse_args()

    players = load_json(os.path.join(BASE, "players_nfl.json"))
    opp_def = load_json(os.path.join(DERIVED, "opponent_defense_vs_pos.json"))
    league_avg = opp_def["league_avg_allowed_per_game"]
    opp_map = opp_def["teams"]

    def sched_factor(opp, pos):
        if args.no_schedule or not opp or pos not in league_avg:
            return 1.0
        d = opp_map.get(opp, {}).get(pos)
        if not d:
            return 1.0
        f = d["allowed_per_game"] / league_avg[pos]
        return max(0.85, min(1.15, f))

    name_to_id = {}
    for pid, p in players.items():
        name = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
        if name:
            name_to_id[name.lower()] = pid
            short = name.replace(" Jr.", "").replace(" Sr.", "").replace(" III", "")
            name_to_id.setdefault(short.lower(), pid)

    # actuals + usage
    actual = defaultdict(list)  # pid -> list of dicts per week
    for w in WEEKS_ACTUAL:
        try:
            rows = load_json(os.path.join(BASE, f"stats_2026_week{w:02d}.json"))
        except FileNotFoundError:
            continue
        for r in rows:
            s = r.get("stats", {})
            pts = s.get("pts_half_ppr")
            if pts is None:
                continue
            touches = (s.get("rush_att") or 0) + (s.get("rec") or 0)
            targets = s.get("rec_tgt") or 0
            # QB passing attempts are in pass_att when present
            if r.get("player", {}).get("position") == "QB":
                targets = s.get("pass_att") or 0
            off = s.get("off_snp") or 0
            tm = s.get("tm_off_snp") or 0
            snap = (off / tm) if tm else None
            actual[r.get("player_id")].append({
                "week": w, "pts": pts, "touches": touches, "targets": targets, "snap": snap,
            })

    ros = defaultdict(list)
    for w in WEEKS_ROS:
        rows = load_json(os.path.join(BASE, f"projections_2026_week{w:02d}.json"))
        for r in rows:
            pts = r.get("stats", {}).get("pts_half_ppr")
            if pts is not None:
                ros[r.get("player_id")].append((w, pts, r.get("opponent")))

    def player_row(pid):
        p = players.get(pid, {})
        name = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
        pos = p.get("position")
        team = p.get("team")
        act = actual.get(pid, [])
        act_total = sum(x["pts"] for x in act)
        act_ppg = act_total / len(act) if act else 0.0
        last3 = [x for x in act if x["week"] >= 7]
        last3_ppg = sum(x["pts"] for x in last3) / len(last3) if last3 else 0.0
        # form uses last-3 only if at least 2 games there, otherwise season PPG
        form_base = last3_ppg if len(last3) >= 2 else act_ppg
        form_ppg = 0.6 * form_base + 0.4 * act_ppg if act else 0.0
        def avg_usage(rows, key):
            vals = [x[key] for x in rows if x[key] is not None]
            return round(sum(vals) / len(vals), 1) if vals else 0.0
        usage = {
            "touches_pg": avg_usage(act, "touches"),
            "touches_last3": avg_usage(last3, "touches"),
            "targets_pg": avg_usage(act, "targets"),
            "targets_last3": avg_usage(last3, "targets"),
            "snap_pg": avg_usage([x for x in act if x["snap"] is not None], "snap"),
        }
        r = ros.get(pid, [])
        raw_total = sum(x[1] for x in r)
        games = len(r)
        raw_ppg = raw_total / games if games else 0.0
        sched_rows = []
        sched_total = 0.0
        for w, pts, opp in sorted(r):
            f = sched_factor(opp, pos)
            adj = pts * f
            sched_total += adj
            sched_rows.append((w, round(pts, 1), opp, round(f, 2), round(adj, 1)))
        sched_ppg = sched_total / games if games else 0.0
        if args.blend:
            # old v2 blend, kept for comparison only; backtest says it does not help
            blended_ppg = 0.65 * sched_ppg + 0.35 * form_ppg
            blended_total = blended_ppg * games
        elif args.no_schedule:
            blended_ppg = raw_ppg
            blended_total = blended_ppg * games
        elif args.no_blend:
            blended_ppg = sched_ppg
            blended_total = blended_ppg * games
        else:
            blended_ppg = raw_ppg
            blended_total = blended_ppg * games
        byes = [w for w in WEEKS_ROS if w not in {x[0] for x in r}]
        return {
            "id": pid, "name": name, "pos": pos, "team": team,
            "actual_total": round(act_total, 1), "actual_games": len(act),
            "actual_ppg": round(act_ppg, 2), "last3_ppg": round(last3_ppg, 2), "last3_games": len(last3),
            "form_ppg": round(form_ppg, 2),
            "raw_ros_total": round(raw_total, 1), "sched_ros_total": round(sched_total, 1),
            "ros_total": round(blended_total, 1), "ros_games": games,
            "ros_ppg": round(blended_ppg, 2), "raw_ppg": round(raw_ppg, 2), "sched_ppg": round(sched_ppg, 2),
            "bye_weeks_ros": byes, "usage": usage, "sched_rows": sched_rows,
        }

    # replacement, from ROS PPG, with flex accounted for.
    # Fill positional starters first, then fill flex spots greedily with the
    # best remaining RB/WR/TE. Replacement for a position is the PPG of the
    # last player at that position in a starting lineup (including flex),
    # the same last-starter convention as v1/v2, so QB is unchanged and
    # RB/WR replacement drops because flex is mostly WRs and some RBs.
    all_rows = [player_row(pid) for pid in ros.keys()]
    starters = {"QB": args.qb, "RB": args.rb, "WR": args.wr, "TE": args.te, "K": 1, "DEF": 1}
    ranked_by_pos = {}
    for pos in starters:
        ranked_by_pos[pos] = sorted([r for r in all_rows if r["pos"] == pos], key=lambda x: x["ros_ppg"], reverse=True)
    taken = {pos: args.teams * n for pos, n in starters.items()}
    flex_fills = []
    for _ in range(args.teams * args.flex):
        cands = [(ranked_by_pos[pos][taken[pos]]["ros_ppg"], pos, ranked_by_pos[pos][taken[pos]])
                 for pos in ["RB", "WR", "TE"] if taken[pos] < len(ranked_by_pos[pos])]
        if not cands:
            break
        cands.sort(key=lambda x: x[0], reverse=True)
        _, pos, player = cands[0]
        flex_fills.append((pos, player["name"], player["ros_ppg"]))
        taken[pos] += 1
    repl = {}
    for pos in starters:
        if taken[pos] >= 1 and len(ranked_by_pos[pos]) >= taken[pos]:
            last = ranked_by_pos[pos][taken[pos] - 1]
            repl[pos] = last["ros_ppg"]
            repl[pos+"_name"] = last["name"]
            repl[pos+"_rank"] = taken[pos]
        else:
            repl[pos] = 0.0
    print(f"League: {args.teams} teams, {args.qb} QB / {args.rb} RB / {args.wr} WR / {args.te} TE starters, {args.flex} FLEX (RB/WR/TE)")
    print(f"Flex filled by: {chr(44).join(f' {pos} {name} {ppg}' for pos, name, ppg in flex_fills)}")
    print(f"Blend: {'ON (old v2, backtest says it does not help): 65% schedule-adjusted Sleeper + 35% form (60% last-3 + 40% season)' if args.blend else 'OFF (v3 default, raw Sleeper)'}")
    print(f"Schedule: {'OFF (v3 default; backtest: schedule adjustment hurt every position)' if not args.blend else 'ON via --blend: opp allowed / league avg, capped 0.85-1.15, Weeks 1-9 actuals'}")
    print("Replacement levels (ROS PPG, v3 raw):")
    for pos in ["QB","RB","WR","TE"]:
        print(f"  {pos}: {repl[pos]} ({repl.get(pos+'_name','')}, rank {repl.get(pos+'_rank','')})")
    print()

    def with_vor(row):
        vor_ppg = row["ros_ppg"] - repl.get(row["pos"], 0.0)
        row["vor_ppg"] = round(vor_ppg, 2)
        row["vor_total"] = round(vor_ppg * row["ros_games"], 1)
        return row

    def grades(diff):
        a = abs(diff)
        if a >= 40: return ("A", "C")
        if a >= 25: return ("B+", "C")
        if a >= 15: return ("B", "C")
        if a >= 8: return ("C+", "C-")
        if a >= 3: return ("C", "C-")
        return ("C", "C")

    def parse_side(s):
        rows = []
        for n in [x.strip() for x in s.split(",") if x.strip()]:
            pid = name_to_id.get(n.lower())
            if not pid:
                print(f"  NOT FOUND: {n}")
                continue
            rows.append(with_vor(player_row(pid)))
        return rows

    def show_side(label, rows):
        print(f"{label}:")
        for r in rows:
            u = r["usage"]
            print(f"  {r['name']} ({r['pos']}, {r['team']}): ROS {r['ros_total']} in {r['ros_games']}g, {r['ros_ppg']}/g "
                  f"(raw Sleeper {r['raw_ros_total']}, sched-adj {r['sched_ros_total']}), VOR {r['vor_total']} | "
                  f"Actual W1-9: {r['actual_total']} in {r['actual_games']}g, {r['actual_ppg']}/g, last3 {r['last3_ppg']}/g in {r['last3_games']}g, form {r['form_ppg']}/g | Byes: {r['bye_weeks_ros'] or 'none'}")
            print(f"    Usage: touches {u['touches_pg']}/g (last3 {u['touches_last3']}), targets/att {u['targets_pg']}/g (last3 {u['targets_last3']}), snap {u['snap_pg']:.0%} (Sleeper fields sparse, directional only)")
            print(f"    Weekly: {', '.join(f'W{w}:{pts} vs {opp} x{f}={adj}' for w, pts, opp, f, adj in r['sched_rows'])}")
        print(f"  TOTAL: ROS {round(sum(r['ros_total'] for r in rows),1)} pts, VOR {round(sum(r['vor_total'] for r in rows),1)} pts")
        return sum(r["ros_total"] for r in rows), sum(r["vor_total"] for r in rows)

    if args.top:
        pos, n = args.top[0].upper(), int(args.top[1])
        ranked = sorted([with_vor(r) for r in all_rows if r["pos"] == pos], key=lambda x: x["ros_total"], reverse=True)[:n]
        print(f"Top {n} {pos} by ROS total, Weeks 10-17:")
        for i, r in enumerate(ranked, 1):
            print(f"  {i}. {r['name']} ({r['team']}): {r['ros_total']} pts, {r['ros_ppg']}/g in {r['ros_games']}g, VOR {r['vor_total']}, raw {r['raw_ros_total']}")
        return

    if not args.side_a or not args.side_b:
        ap.print_help()
        return

    a_rows = parse_side(args.side_a)
    b_rows = parse_side(args.side_b)
    print(f"Trade: {args.side_a}  vs  {args.side_b}")
    print("Window: Weeks 10-17, half-PPR, Sleeper/Rotowire pulled Nov 9-10, 2026")
    print()
    a_ros, a_vor = show_side("Side A", a_rows)
    print()
    b_ros, b_vor = show_side("Side B", b_rows)
    print()
    vor_diff = a_vor - b_vor
    winner = "Side A" if vor_diff > 0 else "Side B" if vor_diff < 0 else "Even"
    wg, lg = grades(vor_diff)
    print(f"Verdict (on VOR): {winner} wins by {abs(round(vor_diff,1))} VOR pts")
    print(f"  ROS diff: {round(a_ros-b_ros,1)} pts (A {round(a_ros,1)} vs B {round(b_ros,1)})")
    print(f"  VOR diff: {round(vor_diff,1)} pts (A {round(a_vor,1)} vs B {round(b_vor,1)})")
    print(f"  Grades: winner {wg}, loser {lg}")
    print()
    print("Caveats: v3 is raw Sleeper/Rotowire, backtested Weeks 7-9 (692 player-weeks): "
          "MAE 4.36, corr 0.631, best of the methods tried. That is still noisy, "
          "top-50 MAE 6.10, corr 0.315. No injury, role-change, playoff, or roster-need adjustment.")

if __name__ == "__main__":
    main()
