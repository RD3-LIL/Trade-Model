import json, os, time, urllib.request
BASE=os.path.expanduser("~/workspace/fantasy-football-model/data/raw")
POS=["QB","RB","WR","TE","K","DEF"]
qs="&".join(f"position[]={p}" for p in POS)
def fetch(url, out):
    for i in range(3):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (Ron fantasy model; personal use)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data=r.read()
            with open(out,"wb") as f: f.write(data)
            obj=json.loads(data)
            with_pts=sum(1 for x in obj if x.get("stats",{}).get("pts_half_ppr") is not None)
            print(f"OK {out} rows={len(obj)} with_half_ppr={with_pts} bytes={len(data)}")
            return obj
        except Exception as e:
            print(f"FAIL {i+1} {url}: {e}"); time.sleep(2)
    return None
for week in range(11,18):
    fetch(f"https://api.sleeper.com/projections/nfl/2026/{week}?season_type=regular&{qs}", f"{BASE}/projections_2026_week{week:02d}.json")
