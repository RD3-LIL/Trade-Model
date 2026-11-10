#!/usr/bin/env python3
"""
Trade Evaluator v2 - Ron / Lemonheads
Half-PPR, Sleeper (Rotowire) projections, ROS Weeks 10-17, 2026.
No ESPN league data needed. Everything below is from public Sleeper data.

What v2 adds over v1:
1. Configurable league: --teams, --qb, --rb, --wr, --te
   Replacement rank = teams * starters at that position.
   Default 12 teams, 1 QB / 2 RB / 2 WR / 1 TE, same as v1.
2. Blended ROS, not pure Rotowire:
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
  python3 trade_evaluator_v2.py "Alvin Kamara" --vs "TreVeyon Henderson"
  python3 trade_evaluator_v2.py "Chase Brown, Justin Jefferson" --vs "A.J. Brown, Breece Hall" --teams 10
  python3 trade_evaluator_v2.py --top RB 15 --teams 12
  python3 trade_evaluator_v2.py "Alvin Kamara" --vs "TreVeyon Henderson" --no-blend --no-schedule
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
    ap.add_argument("--no-blend", action="store_true", help="pure Sleeper ROS, like v1")
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
        if args.no_blend:
            blended_ppg = sched_ppg if not args.no_schedule else raw_ppg
            blended_total = blended_ppg * games
        else:
            blended_ppg = 0.65 * sched_ppg + 0.35 * form_ppg
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

    # replacement, from blended PPG
    all_rows = [player_row(pid) for pid in ros.keys()]
    starters = {"QB": args.qb, "RB": args.rb, "WR": args.wr, "TE": args.te, "K": 1, "DEF": 1}
    repl = {}
    for pos, n_start in starters.items():
        rank = args.teams * n_start
        ranked = sorted([r for r in all_rows if r["pos"] == pos], key=lambda x: x["ros_ppg"], reverse=True)
        if len(ranked) >= rank:
            repl[pos] = ranked[rank-1]["ros_ppg"]
            repl[pos+"_name"] = ranked[rank-1]["name"]
            repl[pos+"_rank"] = rank
        else:
            repl[pos] = 0.0
    print(f"League: {args.teams} teams, {args.qb} QB / {args.rb} RB / {args.wr} WR / {args.te} TE starters")
    print(f"Blend: {'OFF (pure Sleeper)' if args.no_blend else 'ON: 65% schedule-adjusted Sleeper + 35% form (60% last-3 + 40% season)'}")
    print(f"Schedule: {'OFF' if args.no_schedule else 'ON: opp allowed / league avg, capped 0.85-1.15, Weeks 1-9 actuals'}")
    print("Replacement levels (blended ROS PPG):")
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
            print(f"  {r['name']} ({r['pos']}, {r['team']}): ROS blended {r['ros_total']} in {r['ros_games']}g, {r['ros_ppg']}/g "
                  f"(raw Sleeper {r['raw_ros_total']}, sched-adj {r['sched_ros_total']}), VOR {r['vor_total']} | "
                  f"Actual W1-9: {r['actual_total']} in {r['actual_games']}g, {r['actual_ppg']}/g, last3 {r['last3_ppg']}/g in {r['last3_games']}g, form {r['form_ppg']}/g | Byes: {r['bye_weeks_ros'] or 'none'}")
            print(f"    Usage: touches {u['touches_pg']}/g (last3 {u['touches_last3']}), targets/att {u['targets_pg']}/g (last3 {u['targets_last3']}), snap {u['snap_pg']:.0%} (Sleeper fields sparse, directional only)")
            print(f"    Weekly: {', '.join(f'W{w}:{pts} vs {opp} x{f}={adj}' for w, pts, opp, f, adj in r['sched_rows'])}")
        print(f"  TOTAL: ROS blended {round(sum(r['ros_total'] for r in rows),1)} pts, VOR {round(sum(r['vor_total'] for r in rows),1)} pts")
        return sum(r["ros_total"] for r in rows), sum(r["vor_total"] for r in rows)

    if args.top:
        pos, n = args.top[0].upper(), int(args.top[1])
        ranked = sorted([with_vor(r) for r in all_rows if r["pos"] == pos], key=lambda x: x["ros_total"], reverse=True)[:n]
        print(f"Top {n} {pos} by blended ROS total, Weeks 10-17:")
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
    print(f"Verdict (on blended VOR): {winner} wins by {abs(round(vor_diff,1))} VOR pts")
    print(f"  Blended ROS diff: {round(a_ros-b_ros,1)} pts (A {round(a_ros,1)} vs B {round(b_ros,1)})")
    print(f"  VOR diff: {round(vor_diff,1)} pts (A {round(a_vor,1)} vs B {round(b_vor,1)})")
    print(f"  Grades: winner {wg}, loser {lg}")
    print()
    print("Caveats: blend weights are a starting point, not backtested. Schedule factors are capped, "
          "and are based on 8-9 games of opponent defense. Injury and role change are not in this.")

if __name__ == "__main__":
    main()
