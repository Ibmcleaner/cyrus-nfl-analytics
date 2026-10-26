"""Cyrus weekly NFL props report: QB passing yards (vs book lines) and RB anytime TD.
Usage:
  python3 -I weekly_props.py project OUTDIR          # download nflverse data, write projections
  python3 -I weekly_props.py report  OUTDIR LINES    # LINES = csv: player,line,over,under (American odds); also writes latest.js
  python3 -I weekly_props.py grade   OUTDIR LEDGER   # grade past picks in the ledger csv, write record.json (run after project)
  python3 -I weekly_props.py report  OUTDIR LINES    # (see above; uses record.json if present)
  python3 -I weekly_props.py log     OUTDIR LEDGER   # add this week's card to the ledger (latest card before kickoff counts)
  python3 -I weekly_props.py site    OUTDIR SITE_ZIP # unpack the current website (zip from Drive), drop in latest.js, zip it for upload
Method (frozen Oct 2026): prior-games-only QB baseline x opponent pass-defense factor, plus adjustments fitted on
2021-25 QB starts (market-informed: uses the game spread/total). Chance = 50/50 blend of projection and book line,
spread = 30% of mean. RB: shrunk TD rate x (implied team points / team average points), P(1+) = 1 - exp(-lambda).
"""
import sys, os, json, subprocess, datetime as dt
import numpy as np, pandas as pd
from math import erf, sqrt
from zoneinfo import ZoneInfo
CT = ZoneInfo("America/Chicago")
START_WEEK = 8   # public track record starts with 2026 Week 8; earlier weeks are graded as tests
LEDGER_COLS = ["season", "week", "official", "market", "tier", "player", "team", "opp", "kickoff", "kickoff_iso", "pick", "line", "price",
               "fair_odds", "chance", "value", "logged_ct", "stat", "result", "units"]

def now_ct():
    return dt.datetime.now(CT).replace(tzinfo=None)

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
COEF = dict(icpt=-3.93, home=3.98, div=-1.30, indoor=-3.29, top_out=-8.60, spread=1.40, tot=1.45)
DIV = [["LA", "SF", "SEA", "ARI"], ["HOU", "IND", "JAX", "TEN"], ["BAL", "CIN", "CLE", "PIT"], ["BUF", "MIA", "NE", "NYJ"],
       ["CHI", "DET", "GB", "MIN"], ["DAL", "NYG", "PHI", "WAS"], ["ATL", "CAR", "NO", "TB"], ["KC", "LAC", "LV", "DEN"]]
DV = {t: i for i, d in enumerate(DIV) for t in d}

def fetch(url, path):
    if not os.path.exists(path):
        subprocess.run(["curl", "-sSL", "--fail", "-o", path, url], check=True)

def ct_kick(gameday, gametime):
    t = dt.datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M") - dt.timedelta(hours=1)  # schedule is US Eastern
    return t.strftime("%a %b %d, %I:%M %p CT").replace(" 0", " ")

def ct_iso(gameday, gametime):
    return (dt.datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M") - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

def project(out):
    os.makedirs(out, exist_ok=True)
    fetch(GAMES, f"{out}/games.csv")
    g = pd.read_csv(f"{out}/games.csv"); g = g[g.game_type == "REG"]
    today = now_ct().strftime("%Y-%m-%d")
    up_all = g[g.home_score.isna() & (g.gameday >= today)]
    season = int(up_all.season.min()); week = int(up_all[up_all.season == season].week.min())
    UP = up_all[(up_all.season == season) & (up_all.week == week)].copy()
    for y in range(season - 3, season + 1):
        fetch(f"{BASE}/stats_player/stats_player_week_{y}.csv", f"{out}/pw_{y}.csv")
    try:
        fetch(f"{BASE}/injuries/injuries_{season}.csv", f"{out}/inj.csv")
        inj = pd.read_csv(f"{out}/inj.csv"); inj = inj[(inj.week == week) & (inj.game_type == "REG")]
    except Exception:
        inj = pd.DataFrame(columns=["gsis_id", "report_status"])
    status = dict(zip(inj.gsis_id, inj.report_status.fillna("")))
    P = pd.concat([pd.read_csv(f"{out}/pw_{y}.csv", low_memory=False) for y in range(season - 3, season + 1)])
    P = P[P.season_type == "REG"]
    g = g[g.season >= season - 3]
    DONE = g[g.home_score.notna()]
    tp = P.groupby(["game_id", "season", "team", "opponent_team"], as_index=False).agg(yds=("passing_yards", "sum"))
    lg = tp[tp.season == season - 1].yds.mean()
    qs = []
    for _, r in DONE.iterrows():
        qs += [(r.gameday, r.game_id, r.home_team, r.home_qb_id), (r.gameday, r.game_id, r.away_team, r.away_qb_id)]
    QS = pd.DataFrame(qs, columns=["gameday", "game_id", "team", "qb"])
    QS = QS.merge(P[P.position == "QB"][["game_id", "player_id", "passing_yards"]], left_on=["game_id", "qb"], right_on=["game_id", "player_id"]).sort_values("gameday")
    prior_lg = QS.merge(g[["game_id", "season"]], on="game_id").query("season == @season - 1").passing_yards.mean()
    # who actually threw most in each team's latest game this season
    cur = P[(P.season == season) & (P.position == "QB")]
    last_qb = {}
    for t, d in cur.groupby("team"):
        lw = d.week.max(); last_qb[t] = d[d.week == lw].sort_values("attempts").player_id.iloc[-1]
    R = P[(P.season == season) & P.position.isin(["WR", "TE", "RB"])]
    top_t = R.groupby(["team", "player_id", "player_display_name"]).targets.sum().reset_index().sort_values("targets", ascending=False).groupby("team").head(1).set_index("team")
    rows = []
    for _, r in UP.iterrows():
        for home, tm, opp, qb, qbn in ((1, r.home_team, r.away_team, r.home_qb_id, r.home_qb_name), (0, r.away_team, r.home_team, r.away_qb_id, r.away_qb_name)):
            y = QS[QS.qb == qb].passing_yards.values
            if len(y):
                w = 0.5 ** (np.arange(len(y))[::-1] / 8.0); base = (np.sum(w * y) + 4 * prior_lg) / (np.sum(w) + 4)
            else:
                base = prior_lg * 0.85
            th = tp[(tp.opponent_team == opp) & (tp.season == season)].yds; la = tp[(tp.opponent_team == opp) & (tp.season == season - 1)].yds
            fac = ((th.sum() + 0.4 * la.sum() + 6 * lg) / (len(th) + 0.4 * len(la) + 6)) / lg
            spread = r.spread_line if home else -r.spread_line
            tt = top_t.loc[tm] if tm in top_t.index else None
            tstat = status.get(tt.player_id, "") if tt is not None else ""
            indoor = int(str(r.roof) in ("dome", "closed"))
            adj = (COEF["icpt"] + COEF["home"] * home + COEF["div"] * int(DV[tm] == DV[opp]) + COEF["indoor"] * indoor
                   + COEF["top_out"] * int(tstat in ("Out", "Doubtful")) + COEF["spread"] * spread + COEF["tot"] * (r.total_line - 44))
            flags = []
            if status.get(qb, "") in ("Questionable", "Doubtful", "Out"): flags.append(f"QB {status[qb]}")
            if tm in last_qb and last_qb[tm] != qb: flags.append("QB did not start last game")
            if len(y) < 5: flags.append("fewer than 5 starts")
            if tstat == "Questionable": flags.append(f"top target {tt.player_display_name} Questionable")
            if tstat in ("Out", "Doubtful"): flags.append(f"top target {tt.player_display_name} {tstat} (included)")
            rows.append(dict(qb=qbn, team=tm, opp=opp, home=home, kickoff=ct_kick(r.gameday, r.gametime), kickoff_iso=ct_iso(r.gameday, r.gametime), starts=len(y), proj=round(base * fac + adj),
                             spread=spread, total=r.total_line, flags="; ".join(flags)))
    pd.DataFrame(rows).to_csv(f"{out}/qb_proj.csv", index=False)
    # RB anytime TD
    pts = []
    for _, r in DONE[DONE.season == season].iterrows():
        pts += [(r.home_team, r.home_score), (r.away_team, r.away_score)]
    TP = pd.DataFrame(pts, columns=["team", "pts"]).groupby("team").pts.agg(["sum", "count"])
    rb = P[P.position == "RB"].copy(); rb["td"] = rb.rushing_tds.fillna(0) + rb.receiving_tds.fillna(0)
    prev = rb[rb.season == season - 1].groupby("player_id").agg(tdp=("td", "sum"), gp=("td", "size"), carp=("carries", "mean"))
    m = prev[prev.carp >= 10].eval("tdp/gp").mean()
    curb = rb[rb.season == season].groupby(["player_id", "player_display_name", "team"]).agg(td=("td", "sum"), gms=("td", "size"), car=("carries", "mean"), lastwk=("week", "max")).reset_index().merge(prev, on="player_id", how="left")
    team_last = P[P.season == season].groupby("team").week.max()
    out_rb = []
    for _, r in UP.iterrows():
        for home, tm, opp in ((1, r.home_team, r.away_team), (0, r.away_team, r.home_team)):
            spread = r.spread_line if home else -r.spread_line
            implied = r.total_line / 2 + spread / 2
            s, c = TP.loc[tm] if tm in TP.index else (0, 0)
            tavg = (s + 4 * 22.5) / (c + 4)
            for _, b in curb[(curb.team == tm) & (curb.gms >= 3) & (curb.car >= 9)].iterrows():
                st = status.get(b.player_id, "")
                if st in ("Out", "Doubtful"): continue
                prior = m if pd.isna(b.tdp) else (b.tdp + 3 * m) / (b.gp + 3)
                lam = (b.td + 5 * prior) / (b.gms + 5) * implied / tavg
                p = 1 - np.exp(-lam)
                fl = []
                if st: fl.append(st)
                if b.lastwk != team_last.get(tm, b.lastwk): fl.append("missed team's last game")
                out_rb.append(dict(rb=b.player_display_name, team=tm, opp=opp, home=home, kickoff=ct_kick(r.gameday, r.gametime), kickoff_iso=ct_iso(r.gameday, r.gametime), tds=int(b.td), games=int(b.gms),
                                   chance=round(p, 3), fair_odds=(f"{-100*p/(1-p):.0f}" if p > 0.5 else f"+{100*(1-p)/p:.0f}"), flags="; ".join(fl)))
    pd.DataFrame(out_rb).sort_values("chance", ascending=False).to_csv(f"{out}/rb.csv", index=False)
    meta = dict(season=season, week=week, games=len(UP), injury_rows=len(inj), run_ct=now_ct().strftime("%Y-%m-%d %I:%M %p CT"))
    json.dump(meta, open(f"{out}/meta.json", "w"))
    print(json.dumps(meta)); print(pd.read_csv(f"{out}/qb_proj.csv").to_string(index=False))

def prof(a): return a / 100 if a > 0 else 100 / -a
def cdf(x): return 0.5 * (1 + erf(x / sqrt(2)))

def report(out, lines_path):
    meta = json.load(open(f"{out}/meta.json"))
    Q = pd.read_csv(f"{out}/qb_proj.csv").fillna({"flags": ""}); L = pd.read_csv(lines_path)
    L["key"] = L.player.str.lower().str.replace(r"[^a-z]", "", regex=True); Q["key"] = Q.qb.str.lower().str.replace(r"[^a-z]", "", regex=True)
    M = Q.merge(L, on="key", how="left")
    rows = []
    for _, r in M.iterrows():
        if pd.isna(r.line):
            rows.append(dict(**r[["qb", "team", "opp", "home", "kickoff", "kickoff_iso", "proj"]].to_dict(), bet="", chance=np.nan, ev=np.nan, tier="NO LINE", reason=str(r["flags"]))); continue
        mean = (r.proj + r.line) / 2; p = 1 - cdf((r.line - mean) / (0.30 * mean))
        evo = p * prof(r.over) - (1 - p) if not pd.isna(r.over) else -9
        evu = (1 - p) * prof(r.under) - p if not pd.isna(r.under) else -9
        side, ev, ch, pr = ("OVER", evo, p, r.over) if evo >= evu else ("UNDER", evu, 1 - p, r.under)
        f = str(r["flags"])
        if "QB " in f and ("Questionable" in f or "Doubtful" in f or "Out" in f or "did not start" in f): tier = "PASS"
        elif "top target" in f and "Questionable" in f: tier = "RECHECK"
        elif ev >= 0.10 and r.starts >= 20: tier = "BEST BET"
        elif ev > 0.03: tier = "BET"
        elif ev > 0: tier = "LEAN"
        else: tier = "PASS"
        rows.append(dict(qb=r.qb, team=r.team, opp=r.opp, home=r.home, kickoff=r.kickoff, kickoff_iso=r.kickoff_iso, proj=r.proj, bet=f"{side} {r.line} ({int(pr):+d})",
                         side=side, line=r.line, price=int(pr), chance=round(ch, 3), ev=round(ev, 3), tier=tier, reason=f))
    for _, l in L[~L.key.isin(Q.key)].iterrows():   # book has a line for a QB the schedule does not list as starter
        rows.append(dict(qb=l.player, team="", opp="", home=np.nan, kickoff="", kickoff_iso="", proj=np.nan, bet=f"line {l.line}", chance=np.nan, ev=np.nan, tier="PASS",
                         reason="book lists this QB but the schedule lists a different starter: starter uncertain"))
    order = {"BEST BET": 0, "BET": 1, "LEAN": 2, "RECHECK": 3, "PASS": 4, "NO LINE": 5}
    T = pd.DataFrame(rows); T["o"] = T.tier.map(order); T = T.sort_values(["o", "ev"], ascending=[True, False]).drop(columns="o")
    B = rb_card(out)
    T.to_csv(f"{out}/qb_card.csv", index=False)
    rec = json.load(open(f"{out}/record.json")) if os.path.exists(f"{out}/record.json") else None
    web(out, meta, T, B, rec)
    # PDF
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    ss = getSampleStyleSheet(); H = ParagraphStyle("h", parent=ss["Heading1"], textColor=colors.HexColor("#1F3864"), fontSize=16)
    S = ParagraphStyle("s", parent=ss["BodyText"], fontSize=8.5, leading=11); C = ParagraphStyle("c", parent=S, fontSize=7.8, leading=9.5)
    def tbl(df, cols, heads, w):
        data = [heads] + [[Paragraph(str(v), C) for v in row] for row in df[cols].values.tolist()]
        t = Table(data, colWidths=w, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, 0), 8), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t
    T2 = T.copy(); T2["proj"] = T2.proj.map(lambda x: "" if pd.isna(x) else f"{x:.0f}"); T2["chance"] = T2.chance.map(lambda x: "" if pd.isna(x) else f"{x:.0%}"); T2["ev"] = T2.ev.map(lambda x: "" if pd.isna(x) else f"{x:+.2f}")
    B2 = B.head(12).copy(); B2["chance"] = B2.chance.map(lambda x: f"{x:.0%}")
    doc = SimpleDocTemplate(f"{out}/Cyrus_Props_Report_{meta['season']}_W{meta['week']:02d}.pdf", pagesize=landscape(letter), leftMargin=30, rightMargin=30, topMargin=28, bottomMargin=28)
    st = [Paragraph(f"Cyrus NFL Props Report - {meta['season']} Week {meta['week']}", H)]
    if rec:
        st += [Paragraph(f"<b>Track record</b> ({rec['label']}). Graded picks only; voids (player did not play) are excluded. "
                         "RB rows have no book price, so judge them by hit rate against the expected rate.", S)]
        if rec["rows"]:
            R2 = pd.DataFrame(rec["rows"]); R2["units"] = R2.units.map(lambda x: "" if x is None or pd.isna(x) else f"{x:+.2f}")
            R2["win_pct"] = R2.win_pct.map(lambda x: f"{x:.0%}"); R2["expected_pct"] = R2.expected_pct.map(lambda x: f"{x:.0%}")
            st += [tbl(R2, ["market", "tier", "picks", "wins", "losses", "voids", "win_pct", "expected_pct", "units"],
                       ["Market", "Tier", "Graded", "Won", "Lost", "Void", "Hit rate", "Expected", "Units (1/pick)"], [90, 70, 50, 45, 45, 45, 60, 60, 90]), Spacer(1, 6)]
        for t in rec.get("tests", []):
            st += [Paragraph(t, S)]
    st += [Paragraph(f"Run {meta['run_ct']}. Data: nflverse schedules, player stats and injury report ({meta['injury_rows']} injury rows this week); book lines from public odds pages at run time. "
                    "Model is market-informed and not yet backtested against prop lines: treat picks as small, flat-stake leans. Check inactives about 90 minutes before kickoff.", S), Spacer(1, 6),
          Paragraph("<b>RB anytime touchdown</b> (tier by chance: 70%+ Best Bet, 60-70% Bet; bet only if the book pays longer than fair odds)", S),
          tbl(B2, ["tier", "rb", "team", "opp", "kickoff", "tds", "games", "chance", "fair_odds", "flags"], ["Tier", "RB", "Team", "Opp", "Kickoff", "TDs", "G", "Chance", "Fair odds", "Flags"], [52, 110, 34, 34, 112, 30, 24, 44, 50, 230]), Spacer(1, 8),
          Paragraph("<b>QB passing yards</b> (chance = 50/50 blend of projection and book line; value = expected profit per $1)", S),
          tbl(T2, ["tier", "qb", "team", "opp", "kickoff", "proj", "bet", "chance", "ev", "reason"], ["Tier", "QB", "Team", "Opp", "Kickoff", "Proj", "Bet (price)", "Chance", "Value", "Flags / PASS reason"], [52, 100, 32, 32, 112, 32, 96, 42, 38, 194])]
    doc.build(st)
    print(T.to_string(index=False)); print(B.head(12).to_string(index=False))

def game(r):
    if not r.team: return ""
    return f"{r.team} vs {r.opp}" if r.home == 1 else f"{r.team} @ {r.opp}"

def rb_card(out):
    B = pd.read_csv(f"{out}/rb.csv", dtype={"fair_odds": str}).fillna({"flags": ""})
    B["tier"] = np.where(B.chance >= 0.70, "BEST BET", np.where(B.chance >= 0.60, "BET", "LEAN"))
    return B

def web(out, meta, T, B, rec=None):
    """Write latest.js for the website's NFL Predictor page (cyrusforgesystems.com/cyrus/nfl-predictor/)."""
    run = dt.datetime.strptime(meta["run_ct"], "%Y-%m-%d %I:%M %p CT")
    rb = [dict(tier=r.tier, player=r.rb, game=game(r), kickoff=r.kickoff, chance=int(round(r.chance * 100)), note=str(r.flags))
          for r in B[B.chance >= 0.50].head(12).itertuples()]
    shown = T[T.tier.isin(["BEST BET", "BET", "LEAN", "RECHECK"])]
    qb = [dict(tier=r.tier, player=r.qb, game=game(r), kickoff=r.kickoff, pick=f"{r.side.capitalize()} {r.line}", line=float(r.line),
               projection=int(r.proj), chance=int(round(r.chance * 100)),
               note=(str(r.reason).split("top target ")[-1] if r.tier == "RECHECK" else "")) for r in shown.itertuples()]
    P = T[T.tier == "PASS"]
    unsettled = P[P.reason.str.contains("QB |starter uncertain|did not start", regex=True)]
    novalue = P[~P.index.isin(unsettled.index)]
    passed = []
    if len(unsettled): passed.append(dict(players=", ".join(unsettled.qb), count=len(unsettled), reason="the starting quarterback isn't settled, so Cyrus won't make a call."))
    if len(novalue): passed.append(dict(players=", ".join(novalue.qb), count=len(novalue), reason="Cyrus's projection is too close to the casino line to make a call."))
    data = dict(season=int(meta["season"]), week=int(meta["week"]), updated=run.strftime("%a %b %d, %I:%M %p CT").replace(" 0", " "), sample=False,
                next_update=["Wed 6:45 PM CT", "Fri 6:45 PM CT"], rb=rb, qb=qb, passed=passed, record=rec)
    with open(f"{out}/latest.js", "w") as f:
        f.write("// This week's Cyrus card, written by weekly_props.py. Times are Central.\n")
        f.write("window.CYRUS_DATA = " + json.dumps(data, indent=2) + ";\n")
    print(f"latest.js: {len(rb)} RB, {len(qb)} QB shown, {sum(p['count'] for p in passed)} passed")

def load_ledger(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=LEDGER_COLS)
    L = pd.read_csv(path, dtype=str).fillna("")
    for c in LEDGER_COLS:
        if c not in L.columns: L[c] = ""
    L = L[LEDGER_COLS].copy()
    # Google Sheets may reformat values on import/export: normalize them back
    L["kickoff_iso"] = L.kickoff_iso.map(lambda x: pd.to_datetime(x).strftime("%Y-%m-%dT%H:%M") if str(x).strip() else "")
    for c in ["season", "week", "official"]:
        L[c] = L[c].map(lambda x: str(int(float(x))) if str(x).strip() else "")
    L["result"] = L.result.str.strip().str.upper()
    return L

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return np.nan

def summarize(L, season):
    """Season-to-date record from the official (Week 8+) graded rows, by market and tier."""
    L = L[(L.season.astype(str) == str(season))]
    G = L[(L.official == "1") & L.result.isin(["WIN", "LOSS", "VOID"])]
    rows = []
    for (mk, tier), d in G.groupby(["market", "tier"], sort=False):
        dd = d[d.result != "VOID"]
        if not len(dd) and not len(d): continue
        w = int((dd.result == "WIN").sum()); l = int((dd.result == "LOSS").sum())
        u = dd.units.map(num).sum() if mk == "QB YDS" else None
        rows.append(dict(market=mk, tier=tier, picks=len(dd), wins=w, losses=l, voids=int((d.result == "VOID").sum()),
                         win_pct=(w / len(dd) if len(dd) else 0.0), expected_pct=(dd.chance.map(num).mean() if len(dd) else 0.0),
                         units=(round(float(u), 2) if u is not None else None)))
    order = {"BEST BET": 0, "BET": 1, "LEAN": 2, "RECHECK": 3}
    rows.sort(key=lambda r: (r["market"] != "RB TD", order.get(r["tier"], 9)))
    weeks = sorted(set(G.week.astype(int)))
    label = ((f"{season} Week {min(weeks)}" if len(weeks) == 1 else f"{season} Weeks {min(weeks)}-{max(weeks)}") if weeks else f"starts with {season} Week {START_WEEK}; no official week graded yet")
    tests = []
    T = L[(L.official != "1") & L.result.isin(["WIN", "LOSS"])]
    for wk, d in T.groupby("week"):
        parts = []
        for mk, m in d.groupby("market"):
            sel = m[m.tier.isin(["BEST BET", "BET"])]
            if len(sel): parts.append(f"{mk} Best Bet + Bet {int((sel.result == 'WIN').sum())}-{int((sel.result == 'LOSS').sum())}")
        if parts: tests.append(f"Test week {wk} (before the public record): " + "; ".join(parts) + ".")
    return dict(season=int(season), start_week=START_WEEK, through_week=(max(weeks) if weeks else None), label=label, rows=rows, tests=tests)

def grade(out, ledger_path):
    meta = json.load(open(f"{out}/meta.json")); season = meta["season"]
    L = load_ledger(ledger_path)
    P = pd.read_csv(f"{out}/pw_{season}.csv", low_memory=False); P = P[P.season_type == "REG"].copy()
    P["key"] = P.player_display_name.str.lower().str.replace(r"[^a-z]", "", regex=True)
    P["td"] = P.rushing_tds.fillna(0) + P.receiving_tds.fillna(0)
    played = set(zip(P.week, P.team))
    now = now_ct(); n = 0; done = []
    for i, r in L[L.result == ""].iterrows():
        if str(r.season) != str(season) or not r.kickoff_iso: continue
        if dt.datetime.strptime(r.kickoff_iso, "%Y-%m-%dT%H:%M") > now - dt.timedelta(hours=12): continue
        wk = int(r.week)
        if (wk, r.team) not in played: continue          # stats for that game are not posted yet
        key = "".join(ch for ch in r.player.lower() if ch.isalpha())
        m = P[(P.week == wk) & (P.key == key)]
        if not len(m):
            L.loc[i, ["stat", "result", "units"]] = ["", "VOID", "0"]; n += 1
            done.append(f"Wk {wk} {r.market} {r.tier}: {r.player} {r.pick} -> did not play (VOID)"); continue
        if r.market == "RB TD":
            tds = int(m.td.sum()); L.loc[i, ["stat", "result", "units"]] = [str(tds), "WIN" if tds >= 1 else "LOSS", ""]
            done.append(f"Wk {wk} {r.market} {r.tier}: {r.player} {r.pick} -> {tds} TD ({'WIN' if tds >= 1 else 'LOSS'})")
        else:
            yds = float(m.passing_yards.sum()); line = float(r.line)
            win = yds > line if r.pick.startswith("Over") else yds < line
            L.loc[i, ["stat", "result", "units"]] = [f"{yds:.0f}", "WIN" if win else "LOSS", f"{prof(float(r.price)) if win else -1:.3f}"]
            done.append(f"Wk {wk} {r.market} {r.tier}: {r.player} {r.pick} -> {yds:.0f} yds ({'WIN' if win else 'LOSS'})")
        n += 1
    L.to_csv(ledger_path, index=False)
    rec = summarize(L, season)
    json.dump(rec, open(f"{out}/record.json", "w"), indent=2)
    print(f"graded {n} picks; record: {rec['label']}")
    for d in done: print("  " + d)
    print(pd.DataFrame(rec["rows"]).to_string(index=False) if rec["rows"] else "(no official graded picks yet)")
    for t in rec["tests"]: print(t)

def log(out, ledger_path):
    """Add this run's card. The latest card before kickoff counts: rows for games not yet started are replaced."""
    meta = json.load(open(f"{out}/meta.json")); season, week = meta["season"], meta["week"]
    L = load_ledger(ledger_path); now = now_ct(); stamp = now.strftime("%Y-%m-%d %I:%M %p CT")
    def future(iso): return bool(iso) and dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M") > now
    same = (L.season.astype(str) == str(season)) & (L.week.astype(str) == str(week)) & (L.result == "")
    L = L[~(same & L.kickoff_iso.map(future))]
    new = []
    T = pd.read_csv(f"{out}/qb_card.csv").fillna("")
    for r in T[T.tier.isin(["BEST BET", "BET", "LEAN", "RECHECK"])].itertuples():
        if not future(r.kickoff_iso): continue
        new.append(dict(market="QB YDS", tier=r.tier, player=r.qb, team=r.team, opp=r.opp, kickoff=r.kickoff, kickoff_iso=r.kickoff_iso,
                        pick=f"{r.side.capitalize()} {r.line}", line=str(r.line), price=str(int(r.price)), fair_odds="", chance=str(r.chance), value=f"{r.ev:+.2f}"))
    B = rb_card(out)
    for r in B[B.chance >= 0.50].head(12).itertuples():
        if not future(r.kickoff_iso): continue
        new.append(dict(market="RB TD", tier=r.tier, player=r.rb, team=r.team, opp=r.opp, kickoff=r.kickoff, kickoff_iso=r.kickoff_iso,
                        pick="Anytime TD", line="", price="", fair_odds=str(r.fair_odds), chance=str(r.chance), value=""))
    for d in new:
        d.update(season=str(season), week=str(week), official=("1" if week >= START_WEEK else "0"), logged_ct=stamp, stat="", result="", units="")
    L = pd.concat([L, pd.DataFrame(new, columns=LEDGER_COLS)], ignore_index=True)
    L = L.sort_values(["season", "week", "market", "kickoff_iso", "player"], key=lambda c: c.astype(str)).reset_index(drop=True)
    L.to_csv(ledger_path, index=False)
    print(f"logged {len(new)} picks for {season} Week {week}; ledger now {len(L)} rows")

def site(out, pkg):
    """Unpack the current website (zip or tgz from Google Drive), drop in this week's latest.js, zip it for Cloudflare upload."""
    import shutil, tarfile, zipfile
    meta = json.load(open(f"{out}/meta.json"))
    d = f"{out}/site"
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    if zipfile.is_zipfile(pkg):
        with zipfile.ZipFile(pkg) as zf:
            for m in zf.infolist():
                if m.filename.startswith("__MACOSX") or ".." in m.filename: continue
                zf.extract(m, d)
    else:
        with tarfile.open(pkg) as t:
            try: t.extractall(d, filter="data")
            except TypeError: t.extractall(d)
    # if the zip has a single top-level folder, use its contents
    top = [n for n in os.listdir(d) if not n.startswith(".")]
    if len(top) == 1 and os.path.isdir(f"{d}/{top[0]}") and not os.path.exists(f"{d}/index.html"):
        inner = f"{d}/{top[0]}"
        for n in os.listdir(inner): shutil.move(f"{inner}/{n}", d)
        os.rmdir(inner)
    assert os.path.exists(f"{d}/index.html"), "site package has no index.html"
    os.makedirs(f"{d}/data", exist_ok=True); shutil.copy(f"{out}/latest.js", f"{d}/data/latest.js")
    z = f"{out}/CyrusForge_Site_{meta['season']}_W{meta['week']:02d}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(d):
            for fn in files:
                full = os.path.join(root, fn); zf.write(full, os.path.relpath(full, d))
    print("site zip:", z, "files:", sum(len(f) for _, _, f in os.walk(d)))

if __name__ == "__main__":
    if sys.argv[1] == "project": project(sys.argv[2])
    elif sys.argv[1] == "report": report(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "grade": grade(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "log": log(sys.argv[2], sys.argv[3])
    else: site(sys.argv[2], sys.argv[3])
