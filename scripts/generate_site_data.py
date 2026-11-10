#!/usr/bin/env python3
"""Generate site/data.json for the GitHub Pages trade scenario builder.
v3 logic (Nov 10, 2026 backtest): RAW Sleeper ROS, no blend, no schedule
adjustment. Backtest Weeks 7-9, 692 player-weeks: raw MAE 4.36, corr 0.631,
best overall; schedule adjustment hurt every position, 35% form blend was
a wash. Form and schedule-adjusted totals are kept in the output for
transparency, but ros/ppg (and replacement levels) are raw Sleeper.
Output is compact: only players with a Week 10-17 projection.
Also computes replacement levels for 10, 12, and 14 teams.
"""
import json, os
from collections import defaultdict
BASE=os.path.expanduser("~/workspace/fantasy-football-model/data/raw")
DERIVED=os.path.expanduser("~/workspace/fantasy-football-model/data/derived")
OUT=os.path.expanduser("~/workspace/fantasy-football-model/site/data.json")
WEEKS_ROS=list(range(10,18)); WEEKS_ACTUAL=list(range(1,10))
def load(p):
    with open(p) as f: return json.load(f)
players=load(os.path.join(BASE,"players_nfl.json"))
opp_def=load(os.path.join(DERIVED,"opponent_defense_vs_pos.json"))
league_avg=opp_def["league_avg_allowed_per_game"]; opp_map=opp_def["teams"]
def sched_factor(opp,pos):
    if not opp or pos not in league_avg: return 1.0
    d=opp_map.get(opp,{}).get(pos)
    if not d: return 1.0
    return max(0.85,min(1.15, d["allowed_per_game"]/league_avg[pos]))
actual=defaultdict(list)
for w in WEEKS_ACTUAL:
    for r in load(os.path.join(BASE,f"stats_2026_week{w:02d}.json")):
        s=r.get("stats",{}); pts=s.get("pts_half_ppr")
        if pts is None: continue
        touches=(s.get("rush_att") or 0)+(s.get("rec") or 0)
        targets=s.get("rec_tgt") or 0
        off=s.get("off_snp") or 0; tm=s.get("tm_off_snp") or 0
        actual[r.get("player_id")].append({"week":w,"pts":pts,"touches":touches,"targets":targets,"snap":(off/tm if tm else None)})
ros=defaultdict(list)
for w in WEEKS_ROS:
    for r in load(os.path.join(BASE,f"projections_2026_week{w:02d}.json")):
        pts=r.get("stats",{}).get("pts_half_ppr")
        if pts is not None:
            ros[r.get("player_id")].append((w,pts,r.get("opponent")))
def avg(rows,key):
    vals=[x[key] for x in rows if x.get(key) is not None]
    return round(sum(vals)/len(vals),1) if vals else 0.0
rows=[]
for pid, rlist in ros.items():
    p=players.get(pid,{}); name=f"{p.get('first_name','')} {p.get('last_name','')}".strip()
    pos=p.get("position"); team=p.get("team")
    act=actual.get(pid,[]); act_total=sum(x["pts"] for x in act); act_ppg=act_total/len(act) if act else 0.0
    last3=[x for x in act if x["week"]>=7]; last3_ppg=sum(x["pts"] for x in last3)/len(last3) if last3 else 0.0
    form_base=last3_ppg if len(last3)>=2 else act_ppg
    form_ppg=0.6*form_base+0.4*act_ppg if act else 0.0
    raw_total=sum(x[1] for x in rlist); games=len(rlist); raw_ppg=raw_total/games if games else 0.0
    sched_total=0.0; weekly=[]
    for w,pts,opp in sorted(rlist):
        f=sched_factor(opp,pos); adj=pts*f; sched_total+=adj
        weekly.append([w,round(pts,1),opp,round(f,2),round(adj,1)])
    sched_ppg=sched_total/games if games else 0.0
    blended_ppg=0.65*sched_ppg+0.35*form_ppg  # kept for transparency only, not used for ros
    rows.append({
        "id":pid,"name":name,"pos":pos,"team":team,
        "ros":round(raw_total,1),"ppg":round(raw_ppg,2),
        "blended":round(blended_ppg*games,1),
        "raw":round(raw_total,1),"sched":round(sched_total,1),
        "games":games,"byes":[w for w in WEEKS_ROS if w not in {x[0] for x in rlist}],
        "actual":round(act_total,1),"actual_ppg":round(act_ppg,2),
        "last3_ppg":round(last3_ppg,2),"last3_games":len(last3),"form_ppg":round(form_ppg,2),
        "touches_pg":avg(act,"touches"),"targets_pg":avg(act,"targets"),
        "weekly":weekly,
    })
# replacement levels per team count
starters={"QB":1,"RB":2,"WR":2,"TE":1}
repl={}
for teams in [10,12,14]:
    repl[str(teams)]={}
    for pos,n in starters.items():
        rank=teams*n
        ranked=sorted([r for r in rows if r["pos"]==pos], key=lambda x: x["ppg"], reverse=True)
        if len(ranked)>=rank:
            repl[str(teams)][pos]={"ppg":ranked[rank-1]["ppg"],"name":ranked[rank-1]["name"],"rank":rank}
# add VOR at 12 teams as default, site recomputes for other sizes
for r in rows:
    rep=repl["12"].get(r["pos"],{}).get("ppg",0)
    r["vor"]=round((r["ppg"]-rep)*r["games"],1)
    r["vor_ppg"]=round(r["ppg"]-rep,2)
rows.sort(key=lambda x: x["ros"], reverse=True)
out={"generated":"2026-11-10","season":2026,"window":"Weeks 10-17","scoring":"half-PPR",
     "source":"Sleeper (Rotowire) projections, pulled Nov 9-10, 2026",
     "method":"v3 raw Sleeper (Rotowire) ROS, Weeks 10-17, half-PPR. No form blend, no schedule adjustment. Backtest Weeks 7-9, 692 player-weeks, no leakage: raw MAE 4.36, corr 0.631, best overall; schedule-adjusted MAE 4.47, corr 0.610; blend 35% form MAE 4.38, corr 0.619. Form (60% last-3 + 40% season) and schedule-adjusted totals are still in each player row for transparency.",
     "backtest":"Weeks 7-9, 692 player-weeks, no leakage. Raw MAE 4.36 corr 0.631; sched MAE 4.47 corr 0.610; blend_0.35 MAE 4.38 corr 0.619; blend_0.50 MAE 4.40; form_only MAE 4.67. By position raw MAE: QB 6.03, RB 4.74, WR 4.15, TE 3.38. Top-50 per week raw MAE 6.10 corr 0.315. Where blend and raw disagreed by >=3 pts, raw was better in 11 of 15 cases.",
     "league_avg_allowed":league_avg,
     "replacement":repl,
     "players":rows}
with open(OUT,"w") as f: json.dump(out,f)
print(f"wrote {OUT} players={len(rows)} bytes={os.path.getsize(OUT)}")
print("top 5:", [(r['name'],r['ros']) for r in rows[:5]])
print("replacement 12:", repl["12"])
