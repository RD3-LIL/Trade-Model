import json, os, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = os.path.expanduser("~/workspace/fantasy-football-model/data/raw")
os.makedirs(BASE, exist_ok=True)
POS = ["QB","RB","WR","TE","K","DEF"]
def qs_pos():
    return "&".join(f"position[]={p}" for p in POS)

def fetch(url, out_path, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (RonPom fantasy model; personal use)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            with open(out_path, "wb") as f:
                f.write(data)
            # validate json
            obj = json.loads(data)
            n = len(obj) if isinstance(obj, (list, dict)) else 1
            print(f"OK {out_path} bytes={len(data)} items={n} url={url}")
            return obj
        except Exception as e:
            print(f"FAIL attempt {i+1} {url}: {e}")
            time.sleep(2)
    return None

def main():
    manifest = {"pulled_at_utc": datetime.now(timezone.utc).isoformat(), "season": 2026, "files": {}}
    # state
    fetch("https://api.sleeper.app/v1/state/nfl", f"{BASE}/state_nfl.json")
    # players map (large)
    fetch("https://api.sleeper.app/v1/players/nfl", f"{BASE}/players_nfl.json")
    # weekly stats weeks 1-9, 2026 regular
    for week in range(1, 10):
        url = f"https://api.sleeper.com/stats/nfl/2026/{week}?season_type=regular&{qs_pos()}"
        obj = fetch(url, f"{BASE}/stats_2026_week{week:02d}.json")
        if obj is None:
            url2 = f"https://api.sleeper.app/v1/stats/nfl/regular/2026/{week}"
            fetch(url2, f"{BASE}/stats_2026_week{week:02d}.json")
    # season stats 2026
    fetch(f"https://api.sleeper.com/stats/nfl/2026?season_type=regular&{qs_pos()}", f"{BASE}/stats_2026_season.json")
    # week 10 projections
    for week in [10]:
        url = f"https://api.sleeper.com/projections/nfl/2026/{week}?season_type=regular&{qs_pos()}"
        obj = fetch(url, f"{BASE}/projections_2026_week{week:02d}.json")
        if obj is None:
            url2 = f"https://api.sleeper.app/v1/projections/nfl/regular/2026/{week}"
            fetch(url2, f"{BASE}/projections_2026_week{week:02d}.json")
    # season projections with ADP half PPR
    fetch(f"https://api.sleeper.com/projections/nfl/2026?season_type=regular&{qs_pos()}&order_by=adp_half_ppr", f"{BASE}/projections_2026_season.json")
    # trending
    fetch("https://api.sleeper.app/v1/players/nfl/trending/add", f"{BASE}/trending_add.json")
    fetch("https://api.sleeper.app/v1/players/nfl/trending/drop", f"{BASE}/trending_drop.json")
    # manifest
    for fn in sorted(os.listdir(BASE)):
        p = os.path.join(BASE, fn)
        manifest["files"][fn] = {"bytes": os.path.getsize(p)}
    with open(os.path.join(BASE, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print("DONE", manifest)

if __name__ == "__main__":
    main()
