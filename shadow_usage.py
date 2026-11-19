"""Cyrus Emerging Usage Watch: a PRIVATE shadow log. It does not change the frozen 2026 model or anything published.

Each week it looks for a running back who is NOT his team's lead back on the season but who, over the team's last
three games, has had more red-zone opportunities (carries plus targets inside the opponent's 20) than the lead back.
Those players are logged, the strongest one is marked as the weekly pick, and after the games each row is graded on
whether the player scored. The point is evidence: by 2027 we will know whether this signal deserves a place in RB 2.0.

Usage (run `weekly_props.py project OUTDIR` first; this reads the files it leaves in OUTDIR):
  python3 -I shadow_usage.py flag  OUTDIR SHADOW_LOG   # add or refresh this week's flags (before kickoff)
  python3 -I shadow_usage.py grade OUTDIR SHADOW_LOG   # fill in results for weeks that have been played
  python3 -I shadow_usage.py show  OUTDIR SHADOW_LOG   # print the log and the running record

Rule v0 (frozen Nov 19, 2026; change the RULE label if any threshold changes, never edit old rows):
  window        = the team's last 3 completed games this season
  lead back     = the team's RB with the most carries this season
  flagged back  = another RB on the team with MORE red-zone opportunities than the lead back in the window,
                  at least MIN_RZ of them, and at least one touch in the team's most recent game
  health check  = the lead back must have played in at least 2 of the 3 window games (otherwise the gap is an
                  absence, not a role change), and the flagged back must not be listed Out or Doubtful
  signal        = "red zone + yards" if he also out-gained the lead back from scrimmage in the window, else "red zone"
  weekly pick   = the flagged back with the biggest red-zone margin (ties: more scrimmage yards)
"""
import sys, os, json, subprocess, datetime as dt
import pandas as pd
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
RULE = "v0"
WINDOW = 3
MIN_RZ = 4
PBP = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{y}.csv.gz"
COLS = ["season", "week", "rule", "team", "opp", "kickoff_iso", "player", "player_id", "lead_back", "rz_player", "rz_lead",
        "yds_player", "yds_lead", "window_games", "lead_games_played", "signal", "weekly_pick", "status", "lead_status",
        "price", "logged_ct", "player_td", "lead_td", "result"]


def now_ct():
    return dt.datetime.now(CT).replace(tzinfo=None)


def load_log(path):
    if os.path.exists(path):
        L = pd.read_csv(path, dtype=str).fillna("")
    else:
        L = pd.DataFrame(columns=COLS)
    for c in COLS:
        if c not in L.columns:
            L[c] = ""
    return L[COLS]


def load(out):
    meta = json.load(open(f"{out}/meta.json")); season, week = int(meta["season"]), int(meta["week"])
    g = pd.read_csv(f"{out}/games.csv"); g = g[(g.game_type == "REG") & (g.season == season)]
    P = pd.read_csv(f"{out}/pw_{season}.csv", low_memory=False); P = P[P.season_type == "REG"]
    return season, week, g, P


def red_zone(out, season):
    path = f"{out}/pbp_{season}.csv.gz"
    subprocess.run(["curl", "-sSL", "--fail", "-o", path, PBP.format(y=season)], check=True)   # always refresh
    want = {"game_id", "week", "season_type", "posteam", "yardline_100", "rusher_player_id", "receiver_player_id",
            "rush_attempt", "pass_attempt", "two_point_attempt"}
    B = pd.read_csv(path, low_memory=False, usecols=lambda c: c in want)
    B = B[(B.season_type == "REG") & (B.yardline_100 <= 20) & (B.two_point_attempt.fillna(0) == 0)]
    runs = B[B.rush_attempt == 1][["week", "posteam", "rusher_player_id"]].rename(columns={"rusher_player_id": "player_id"})
    tgts = B[B.pass_attempt == 1][["week", "posteam", "receiver_player_id"]].rename(columns={"receiver_player_id": "player_id"})
    R = pd.concat([runs, tgts]).dropna(subset=["player_id"])
    return R.groupby(["posteam", "week", "player_id"]).size().rename("rz").reset_index().rename(columns={"posteam": "team"})


def flag(out, log_path):
    season, week, g, P = load(out)
    RZ = red_zone(out, season)
    UP = g[g.week == week]
    try:
        inj = pd.read_csv(f"{out}/inj.csv"); inj = inj[(inj.week == week) & (inj.game_type == "REG")]
        status = dict(zip(inj.gsis_id, inj.report_status.fillna("")))
    except Exception:
        status = {}
    rb = P[(P.position == "RB") & (P.week < week)].copy()
    for c in ("carries", "targets", "rushing_yards", "receiving_yards"):
        rb[c] = rb[c].fillna(0)
    rb["touch"] = rb.carries + rb.targets; rb["yds"] = rb.rushing_yards + rb.receiving_yards
    rows = []
    for _, r in UP.iterrows():
        for tm, opp in ((r.home_team, r.away_team), (r.away_team, r.home_team)):
            t = rb[rb.team == tm]
            weeks = sorted(P[(P.team == tm) & (P.week < week)].week.unique())[-WINDOW:]
            if len(weeks) < WINDOW or t.empty:
                continue
            lead_id = t.groupby("player_id").carries.sum().idxmax()
            w = t[t.week.isin(weeks)]
            rz = RZ[(RZ.team == tm) & RZ.week.isin(weeks)].groupby("player_id").rz.sum()
            yds = w.groupby("player_id").yds.sum()
            played = w[w.touch > 0].groupby("player_id").week.nunique()
            names = t.groupby("player_id").player_display_name.last()
            lead_rz, lead_yds, lead_gp = int(rz.get(lead_id, 0)), float(yds.get(lead_id, 0)), int(played.get(lead_id, 0))
            if lead_gp < 2:
                continue                                    # the gap would be an absence, not a role change
            last_week = set(w[(w.week == weeks[-1]) & (w.touch > 0)].player_id)
            for pid in w.player_id.unique():
                if pid == lead_id or pid not in last_week:
                    continue
                st = status.get(pid, "")
                p_rz = int(rz.get(pid, 0))
                if st in ("Out", "Doubtful") or p_rz < MIN_RZ or p_rz <= lead_rz:
                    continue
                p_yds = float(yds.get(pid, 0))
                kick = (dt.datetime.strptime(f"{r.gameday} {r.gametime}", "%Y-%m-%d %H:%M") - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
                rows.append(dict(season=season, week=week, rule=RULE, team=tm, opp=opp, kickoff_iso=kick, player=names[pid],
                                 player_id=pid, lead_back=names[lead_id], rz_player=p_rz, rz_lead=lead_rz, yds_player=int(p_yds),
                                 yds_lead=int(lead_yds), window_games=len(weeks), lead_games_played=lead_gp,
                                 signal="red zone + yards" if p_yds > lead_yds else "red zone", weekly_pick=0,
                                 status=st, lead_status=status.get(lead_id, ""), price="",
                                 logged_ct=now_ct().strftime("%Y-%m-%d %I:%M %p CT"), player_td="", lead_td="", result=""))
    new = pd.DataFrame(rows, columns=COLS)
    if len(new):
        new["m"] = new.rz_player - new.rz_lead
        top = new.sort_values(["m", "yds_player"], ascending=False).index[0]
        new.loc[top, "weekly_pick"] = 1
        new = new.drop(columns="m")
    L = load_log(log_path)
    now = now_ct().strftime("%Y-%m-%dT%H:%M")
    same = (L.season == str(season)) & (L.week == str(week))
    locked = L[same & (L.kickoff_iso <= now)]             # games already kicked off keep their logged rows
    keep_new = new[~new.team.isin(locked.team)] if len(new) else new
    L = pd.concat([L[~same], locked, keep_new.astype(str)], ignore_index=True)
    L.to_csv(log_path, index=False)
    print(f"{season} Week {week}: {len(keep_new)} flagged ({len(locked)} locked rows kept); log now {len(L)} rows")
    if len(keep_new):
        print(keep_new[["team", "opp", "player", "lead_back", "rz_player", "rz_lead", "yds_player", "yds_lead", "signal", "weekly_pick", "status"]].to_string(index=False))


def grade(out, log_path):
    season, week, g, P = load(out)
    L = load_log(log_path)
    P = P.copy(); P["td"] = P.rushing_tds.fillna(0) + P.receiving_tds.fillna(0)
    names = P.groupby("player_display_name").player_id.last()
    done = set(zip(g[g.home_score.notna()].week, g[g.home_score.notna()].home_team)) | set(zip(g[g.home_score.notna()].week, g[g.home_score.notna()].away_team))
    n = 0
    for i, r in L.iterrows():
        if r.season != str(season) or r.result or (int(r.week), r.team) not in done:
            continue
        wk = P[P.week == int(r.week)]
        me = wk[wk.player_id == r.player_id]
        lead = wk[wk.player_id == names.get(r.lead_back, "")]
        L.loc[i, "player_td"] = "" if me.empty else str(int(me.td.sum()))
        L.loc[i, "lead_td"] = "" if lead.empty else str(int(lead.td.sum()))
        L.loc[i, "result"] = "DNP" if me.empty else ("HIT" if me.td.sum() >= 1 else "MISS")
        n += 1
    L.to_csv(log_path, index=False)
    print(f"graded {n} rows"); show(out, log_path)


def show(out, log_path):
    L = load_log(log_path)
    if L.empty:
        print("shadow log is empty"); return
    print(L[["season", "week", "team", "player", "lead_back", "rz_player", "rz_lead", "signal", "weekly_pick", "price", "player_td", "lead_td", "result"]].to_string(index=False))
    G = L[L.result.isin(["HIT", "MISS"])]
    for label, d in (("all flags", G), ("weekly picks", G[G.weekly_pick == "1"])):
        if len(d):
            print(f"{label}: {int((d.result == 'HIT').sum())}-{int((d.result == 'MISS').sum())} ({(d.result == 'HIT').mean():.0%} scored)")


if __name__ == "__main__":
    {"flag": flag, "grade": grade, "show": show}[sys.argv[1]](sys.argv[2], sys.argv[3])
