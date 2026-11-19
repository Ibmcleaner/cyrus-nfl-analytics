#!/usr/bin/env python3
"""Cyrus NFL Analytics - season chronicle builder.

Reads the pick ledger (CSV exported from the newest "Cyrus Pick Ledger - ..." sheet) and the
GitHub commit history of the website's data/latest.js, and writes data/chronicle.js: a
week-by-week record for both markets plus a log of every run that produced a card and
whether it published itself.

Usage:
  python3 -I chronicle.py LEDGER.csv COMMITS.json OUT.js [MILESTONES.json]

  LEDGER.csv      the ledger sheet exported as CSV
  COMMITS.json    output of: curl -sS "https://api.github.com/repos/Ibmcleaner/cyrusforgesystems-site/commits?path=data/latest.js&per_page=100"
  OUT.js          where to write the chronicle (the site expects data/chronicle.js)
  MILESTONES.json optional list of {"date": "...", "text": "..."} shown under the chronicle

Rules (same as the pipeline): the public record starts with 2026 Week 8; earlier weeks are
tests. Voids (player did not play) are excluded from hit rates. Nothing here re-grades a pick;
it only counts what the ledger already says.
"""
import csv, json, re, sys
import datetime as dt
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
START_WEEK = 8
LEGACY_TIER = {"BEST BET": "STRONG", "BET": "MODERATE", "LEAN": "SLIGHT"}
AUTO_MSG = re.compile(r"^Week (\d+) card \((Wed|Fri|Sun|Mon|Tue|Thu|Sat) run, (\d{4}-\d{2}-\d{2}) CT\)")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_ledger(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        r = {k: (v or "").strip() for k, v in r.items()}
        if not r.get("season") or not r.get("week"):
            continue
        r["season"] = str(int(float(r["season"])))
        r["week"] = int(float(r["week"]))
        r["official"] = str(int(float(r["official"]))) if r.get("official") else "0"
        r["result"] = r.get("result", "").upper()
        t = r.get("tier", "").upper()
        r["tier"] = LEGACY_TIER.get(t, t)
        out.append(r)
    return out


def tally(rows):
    graded = [r for r in rows if r["result"] in ("WIN", "LOSS")]
    voids = sum(1 for r in rows if r["result"] == "VOID")
    wins = sum(1 for r in graded if r["result"] == "WIN")
    losses = len(graded) - wins
    chances = [num(r.get("chance")) for r in graded]
    chances = [c for c in chances if c is not None]
    pending = sum(1 for r in rows if r["result"] == "")
    return dict(logged=len(rows), picks=len(graded), wins=wins, losses=losses, voids=voids, pending=pending,
                win_pct=(wins / len(graded) if graded else None),
                expected_pct=(sum(chances) / len(chances) if chances else None))


def parse_logged(s):
    # ledger stamps look like "2026-11-18 06:49 PM CT"
    for fmt in ("%Y-%m-%d %I:%M %p CT", "%Y-%m-%d %H:%M CT", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).replace(tzinfo=CT)
        except ValueError:
            pass
    return None


def fmt_ct(d):
    return d.strftime("%a %b %-d, %-I:%M %p CT")


def load_commits(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for c in data if isinstance(data, list) else []:
        try:
            when = dt.datetime.strptime(c["commit"]["committer"]["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).astimezone(CT)
            msg = c["commit"]["message"].splitlines()[0]
        except (KeyError, ValueError, IndexError):
            continue
        m = AUTO_MSG.match(msg)
        wk = int(m.group(1)) if m else (int(re.match(r"^Week (\d+) card", msg).group(1)) if re.match(r"^Week (\d+) card", msg) else None)
        out.append(dict(when=when, msg=msg, week=wk, auto=bool(m), sha=c.get("sha", "")[:7]))
    return out


def build(ledger, commits, season, milestones):
    season = str(season)
    L = [r for r in ledger if r["season"] == season]
    weeks = sorted(set(r["week"] for r in L))
    used = set()
    out_weeks = []
    for wk in weeks:
        W = [r for r in L if r["week"] == wk]
        official = any(r["official"] == "1" for r in W)
        rb = tally([r for r in W if r["market"] == "RB TD"])
        qb = tally([r for r in W if r["market"] == "QB YDS"])
        # runs: every distinct logged_ct stamp is a run that produced a card and logged it
        stamps = sorted(set(r.get("logged_ct", "") for r in W if r.get("logged_ct")))
        runs = []
        for s in stamps:
            when = parse_logged(s)
            run = dict(logged=(fmt_ct(when) if when else s), day=(when.strftime("%a") if when else ""), sort=(when.isoformat() if when else s))
            match = None
            if when:
                for c in commits:
                    if c["sha"] in used or c["week"] != wk:
                        continue
                    if abs((c["when"] - when).total_seconds()) <= 3 * 3600:
                        match = c
                        break
            if match:
                used.add(match["sha"])
                run["published"] = "auto" if match["auto"] else "manual"
                run["pushed"] = fmt_ct(match["when"])
                run["commit"] = match["sha"]
            else:
                run["published"] = "offline"   # card logged; the site was updated outside GitHub (zip upload) or not at all
            runs.append(run)
        # commits for this week that match no ledger stamp (e.g. a re-publish by hand)
        for c in commits:
            if c["week"] == wk and c["sha"] not in used:
                used.add(c["sha"])
                runs.append(dict(logged="", day=c["when"].strftime("%a"), published=("auto" if c["auto"] else "manual"),
                                 pushed=fmt_ct(c["when"]), commit=c["sha"], note=c["msg"], sort=c["when"].isoformat()))
        runs.sort(key=lambda r: r["sort"])
        for r in runs: r.pop("sort", None)
        graded = rb["picks"] + qb["picks"] + rb["voids"] + qb["voids"]
        pending = rb["pending"] + qb["pending"]
        status = "graded" if graded and not pending else ("partial" if graded else ("in_play" if pending else "empty"))
        out_weeks.append(dict(week=wk, official=official, status=status, rb=rb, qb=qb, runs=runs))
    O = [r for r in L if r["official"] == "1"]
    totals = dict(rb=tally([r for r in O if r["market"] == "RB TD"]), qb=tally([r for r in O if r["market"] == "QB YDS"]))
    graded_weeks = [w["week"] for w in out_weeks if w["official"] and w["status"] in ("graded", "partial")]
    label = (f"{season} Weeks {min(graded_weeks)}-{max(graded_weeks)}" if len(graded_weeks) > 1 else
             (f"{season} Week {graded_weeks[0]}" if graded_weeks else f"no official week graded yet"))
    return dict(season=int(season), start_week=START_WEEK, generated=fmt_ct(dt.datetime.now(CT)), label=label,
                weeks=out_weeks, totals=totals, milestones=milestones)


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    ledger = load_ledger(argv[1])
    commits = load_commits(argv[2])
    milestones = []
    if len(argv) > 4:
        with open(argv[4], encoding="utf-8") as f:
            milestones = json.load(f)
    season = max(int(r["season"]) for r in ledger) if ledger else dt.datetime.now(CT).year
    data = build(ledger, commits, season, milestones)
    with open(argv[3], "w", encoding="utf-8") as f:
        f.write("// Season chronicle, written by chronicle.py from the pick ledger and the site's commit history. Times are Central.\n")
        f.write("window.CYRUS_CHRONICLE = " + json.dumps(data, indent=2) + ";\n")
    for w in data["weeks"]:
        rb, qb = w["rb"], w["qb"]
        print(f"Week {w['week']:>2} {'official' if w['official'] else 'test    '} {w['status']:<8} "
              f"RB {rb['wins']}-{rb['losses']} ({rb['voids']} void)  QB {qb['wins']}-{qb['losses']}  runs: "
              + "; ".join(f"{r.get('day')} {r.get('published')}" for r in w["runs"]))
    print(f"totals (official): RB {data['totals']['rb']['wins']}-{data['totals']['rb']['losses']}, QB {data['totals']['qb']['wins']}-{data['totals']['qb']['losses']}  [{data['label']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
