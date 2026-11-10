#!/usr/bin/env python3
"""
Trade Evaluator v1 - Ron / Lemonheads
Half-PPR, Sleeper (Rotowire) projections, ROS Weeks 10-17, 2026.
Method, same spirit as the Oct 27-28 / Oct 31 trade sheets:
  ROS total = sum of Sleeper pts_half_ppr, Weeks 10-17.
  Bye weeks = no opponent / no projection, counted as 0.
  ROS PPG = ROS total / games with a projection.
  Actuals = Sleeper stats Weeks 1-9, total and PPG, plus last-3 (Weeks 7-9) PPG.
  Value over replacement (VOR) = (ROS PPG - replacement PPG) * games.
    Replacement is the ROS PPG at the starter cutoff for a 12-team league:
    QB12, RB24, WR24, TE12, K12, DEF12. Configurable below.
  Grades are on VOR difference, not raw points, so a QB does not win
  a trade just by scoring a lot in a 1QB league.
No ESPN login, no private league data. Public Sleeper data only.
Usage:
  python3 trade_evaluator.py "Alvin Kamara" --vs "TreVeyon Henderson"
  python3 trade_evaluator.py "Chase Brown, Aaron Jones Sr." --vs "Deebo Samuel Sr., A.J. Brown"
  python3 trade_evaluator.py --top RB 20
"""
import json, os, sys, argparse
from collections import defaultdict

BASE = os.path.expanduser("~/workspace/fantasy-football-model/data/raw")
WEEKS_ROS = list(range(10, 18))
WEEKS_ACTUAL = list(range(1, 10))
# 12-team, 1QB / 2RB / 2WR / 1TE / 1 FLEX
REPLACEMENT_RANK = {"QB": 12, "RB": 24, "WR": 24, "TE": 12, "K": 12, "DEF": 12}

def load_json(fn):
    with open(os.path.join(BASE, fn)) as f:
        return json.load(f)

def main():
    players = load_json("players_nfl.json")
    name_to_id = {}
    for pid, p in players.items():
        name = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
        if name:
            name_to_id[name.lower()] = pid
            # also allow without Jr./Sr. suffix for lookup convenience
            short = name.replace(" Jr.", "").replace(" Sr.", "").replace(" III", "")
            name_to_id.setdefault(short.lower(), pid)

    # weekly actuals
    actual = defaultdict(list)  # pid -> [(week, pts_half_ppr)]
    for w in WEEKS_ACTUAL:
        try:
            rows = load_json(f"stats_2026_week{w:02d}.json")
        except FileNotFoundError:
            continue
        for r in rows:
            pts = r.get("stats", {}).get("pts_half_ppr")
            if pts is not None:
                actual[r.get("player_id")].append((w, pts))

    # weekly ROS projections
    ros = defaultdict(list)  # pid -> [(week, pts, opponent)]
    for w in WEEKS_ROS:
        rows = load_json(f"projections_2026_week{w:02d}.json")
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
        act_total = sum(x[1] for x in act)
        act_ppg = act_total / len(act) if act else 0.0
        last3 = [x[1] for x in act if x[0] >= 7]
        last3_ppg = sum(last3) / len(last3) if last3 else 0.0
        r = ros.get(pid, [])
        ros_total = sum(x[1] for x in r)
        games = len(r)
        ros_ppg = ros_total / games if games else 0.0
        byes = [w for w in WEEKS_ROS if w not in {x[0] for x in r}]
        return {
            "id": pid, "name": name, "pos": pos, "team": team,
            "actual_total": round(act_total, 1), "actual_games": len(act),
            "actual_ppg": round(act_ppg, 2), "last3_ppg": round(last3_ppg, 2),
            "ros_total": round(ros_total, 1), "ros_games": games,
            "ros_ppg": round(ros_ppg, 2), "bye_weeks_ros": byes,
            "weekly_ros": [(w, round(pts, 1), opp) for w, pts, opp in sorted(r)],
        }

    # replacement levels from ROS PPG ranking
    all_rows = [player_row(pid) for pid in ros.keys()]
    repl = {}
    for pos, rank in REPLACEMENT_RANK.items():
        ranked = sorted([r for r in all_rows if r["pos"] == pos], key=lambda x: x["ros_ppg"], reverse=True)
        if len(ranked) >= rank:
            repl[pos] = ranked[rank-1]["ros_ppg"]
            repl[f"{pos}_name"] = ranked[rank-1]["name"]
        else:
            repl[pos] = 0.0
    print("Replacement levels (ROS PPG, 12-team starters):")
    for pos in REPLACEMENT_RANK:
        print(f"  {pos}: {repl[pos]} ({repl.get(pos+'_name','')}, rank {REPLACEMENT_RANK[pos]})")
    print()

    def with_vor(row):
        vor_ppg = row["ros_ppg"] - repl.get(row["pos"], 0.0)
        row["vor_ppg"] = round(vor_ppg, 2)
        row["vor_total"] = round(vor_ppg * row["ros_games"], 1)
        return row

    def grades_from_vor_diff(diff):
        a = abs(diff)
        if a >= 40: return ("A", "C")
        if a >= 25: return ("B+", "C")
        if a >= 15: return ("B", "C")
        if a >= 8: return ("C+", "C-")
        if a >= 3: return ("C", "C-")
        return ("C", "C")

    def parse_side(s):
        names = [x.strip() for x in s.split(",") if x.strip()]
        rows = []
        for n in names:
            pid = name_to_id.get(n.lower())
            if not pid:
                print(f"  NOT FOUND: {n} (check spelling, try full name with Jr./Sr.)")
                continue
            rows.append(with_vor(player_row(pid)))
        return rows

    def show_side(label, rows):
        print(f"{label}:")
        for r in rows:
            print(f"  {r['name']} ({r['pos']}, {r['team']}): ROS {r['ros_total']} in {r['ros_games']}g, {r['ros_ppg']}/g, "
                  f"VOR {r['vor_total']} | Actual W1-9: {r['actual_total']} in {r['actual_games']}g, {r['actual_ppg']}/g, last3 {r['last3_ppg']}/g | Byes ROS: {r['bye_weeks_ros'] or 'none'}")
            print(f"    Weekly ROS: {', '.join(f'W{w}:{pts} vs {opp}' for w, pts, opp in r['weekly_ros'])}")
        tot_ros = sum(r["ros_total"] for r in rows)
        tot_vor = sum(r["vor_total"] for r in rows)
        print(f"  TOTAL: ROS {round(tot_ros,1)} pts, VOR {round(tot_vor,1)} pts")
        return tot_ros, tot_vor

    ap = argparse.ArgumentParser()
    ap.add_argument("side_a", nargs="?", default=None)
    ap.add_argument("--vs", dest="side_b", default=None)
    ap.add_argument("--top", nargs=2, metavar=("POS", "N"), default=None)
    args = ap.parse_args()

    if args.top:
        pos, n = args.top[0].upper(), int(args.top[1])
        ranked = sorted([with_vor(r) for r in all_rows if r["pos"] == pos], key=lambda x: x["ros_total"], reverse=True)[:n]
        print(f"Top {n} {pos} by ROS total, Weeks 10-17 (half-PPR):")
        for i, r in enumerate(ranked, 1):
            print(f"  {i}. {r['name']} ({r['team']}): {r['ros_total']} pts, {r['ros_ppg']}/g in {r['ros_games']}g, VOR {r['vor_total']}")
        return

    if not args.side_a or not args.side_b:
        ap.print_help()
        print("\nExample: python3 trade_evaluator.py \"Alvin Kamara\" --vs \"TreVeyon Henderson\"")
        return

    a_rows = parse_side(args.side_a)
    b_rows = parse_side(args.side_b)
    print(f"Trade: {args.side_a}  vs  {args.side_b}")
    print("Window: Weeks 10-17, half-PPR, Sleeper/Rotowire projections pulled Nov 9-10, 2026")
    print()
    a_ros, a_vor = show_side("Side A", a_rows)
    print()
    b_ros, b_vor = show_side("Side B", b_rows)
    print()
    raw_diff = a_ros - b_ros
    vor_diff = a_vor - b_vor
    winner = "Side A" if vor_diff > 0 else "Side B" if vor_diff < 0 else "Even"
    print(f"Verdict (on VOR, not raw points): {winner} wins by {abs(round(vor_diff,1))} VOR pts")
    print(f"  Raw ROS diff: {round(raw_diff,1)} pts (A {round(a_ros,1)} vs B {round(b_ros,1)})")
    print(f"  VOR diff: {round(vor_diff,1)} pts (A {round(a_vor,1)} vs B {round(b_vor,1)})")
    wg, lg = grades_from_vor_diff(vor_diff)
    print(f"  Grades: winner {wg}, loser {lg} (grade scale is VOR-based, see README)")
    print()
    print("Caveats: projections are Rotowire via Sleeper, not a backtested model yet. "
          "Injury, role change, and schedule after Week 17 are not in this. "
          "QB raw totals overstate value in 1QB, that is why VOR is the verdict.")

if __name__ == "__main__":
    main()
