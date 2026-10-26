# Cyrus NFL Analytics

Player-performance projection and grading pipeline. Every Wednesday and Friday it projects quarterback passing yards and running-back touchdown probability for the upcoming NFL week, publishes the projections at [cyrusforgesystems.com/cyrus/nfl-predictor](https://cyrusforgesystems.com/cyrus/nfl-predictor/), logs each one before kickoff, and grades it against the official box score. The result is a projection model with a public, auditable accuracy record.

Two outputs:

- **RB touchdown probability** — the chance each running back scores a rushing or receiving touchdown.
- **QB passing yards** — Cyrus's projection beside the market consensus line, and which side of it the model expects.

Every projection carries a confidence and a tier: **Best Bet**, **Bet**, **Lean**, **Recheck** (waiting on an injury decision) or **Pass**. The tier names are the product's public vocabulary; internally they are confidence bands.

## How it works

```
nflverse data ─┐
               ├─► project ─► report ─► latest.js (website) + PDF (internal)
market lines ──┘      │
                      ├─► log    ─► projection ledger (Google Sheet, one new version per run)
                      └─► grade  ─► WIN / LOSS / VOID from official stats ─► track record
```

**Model (frozen October 2026).**

- *QB passing yards:* an exponentially weighted baseline from the quarterback's prior starts (half-life 8 games, shrunk toward the league mean), multiplied by an opponent pass-defense factor, plus adjustments fitted on 2021–25 starts for home field, division game, dome, a missing top target, the spread and the game total. The chance of landing on a side is a 50/50 blend of the projection and the market line with a spread of 30% of the mean.
- *RB touchdown probability:* a shrunk per-game TD rate scaled by the team's implied points for the game, with `P(at least one) = 1 − e^(−λ)`. Tiers by probability: 70%+ Best Bet, 60–70% Bet, otherwise Lean.

**Grading rules.** Projections are graded no earlier than 12 hours after kickoff, from nflverse weekly player stats. RB: WIN if rushing + receiving TDs ≥ 1. QB: WIN if yards land on the picked side of the line. VOID if the player has no stats row while his team played. The last projection published before kickoff is the one that counts.

**Honesty rules baked in.** The pipeline never invents a line, injury status or result; if something is missing, it says so. Weeks before the public record started (2026 Week 8) are graded as tests and labeled that way.

## Running it

```bash
pip install pandas numpy reportlab
python3 weekly_props.py project  out/                     # download nflverse data, build projections
python3 weekly_props.py grade    out/ ledger.csv          # grade past projections, write record.json
python3 weekly_props.py report   out/ lines.csv           # PDF + latest.js (lines.csv: player,line,over,under)
python3 weekly_props.py site     out/ site_current.zip    # drop latest.js into the website package
python3 weekly_props.py log      out/ ledger.csv          # log this week's projections to the ledger
```

`samples/` has a real week's inputs and outputs: `lines.sample.csv`, `latest.sample.js`, the PDF report, and the ledger column template.

## Automation

The whole run is a scheduled task (Wednesday and Friday, 6:45 PM Central) that executes the steps in `docs/weekly_run_instructions.txt`: pull the ledger and the current site from Google Drive, run the five commands, verify the outputs, save a new ledger version to Drive, and deliver the PDF, the site zip and a summary. Nothing is deployed automatically; a human uploads the site.

## How it was built

Built over roughly three weeks in October 2026 by Robert Legorreta, working with several AI models in defined roles. The short version: a spreadsheet became a model, the model became a pipeline, and the pipeline became a scheduled job that publishes to a website.

### Phase 1 — Spreadsheet prototype (Week 6 of the 2026 season)

The first version was a Google Sheet. Team offense and defense tables from NFL.com were pasted in each week, defenses were ranked by yards and touchdowns allowed, and quarterback passing-yard projections and running-back touchdown chances were worked out by formula. Projections were labeled Best Bet, Bet or Lean and compared against market lines by hand.

What it proved: the ranking tiers and the market choices (RB anytime TD, QB passing yards) were right. What it exposed: pasting tables every week does not scale, hand comparison against lines is slow, and a sheet cannot grade itself.

### Phase 2 — A scripted model with a fitted adjustment layer

The sheet logic was rebuilt in Python on nflverse's public play and player data, which goes back years and is machine-readable, instead of NFL.com's weekly tables.

- The QB baseline is an exponentially weighted average of the quarterback's prior starts (half-life of eight games), shrunk toward the league mean, multiplied by an opponent pass-defense factor that blends this season with last.
- On top of that sits a small linear adjustment fitted on 2021–25 regular-season starts: home field, division game (the original sheet's "divisional games run 50–60 yards lower" rule turned out to be real but smaller, about −1.3 yards after the other factors), dome, a missing top target, the point spread and the game total.
- The chance of landing over or under the market line is a 50/50 blend of the projection and the line, with a spread of 30% of the mean. The blend is a deliberate humility setting: the model does not pretend to know more than the market, it looks for the cases where they disagree.
- RB anytime TD uses a shrunk per-game touchdown rate scaled by the team's implied points for that game, with P(at least one) = 1 − e^(−λ). Tiers are by probability, not price, because the product is a projection, not a wager.

A decision made early and kept: the method and coefficients are frozen. The job is not allowed to retune itself week to week, so the track record means something.

### Phase 3 — Logging and grading

A projection that is not logged before kickoff does not count, so the pipeline writes every Best Bet, Bet, Lean and Recheck to a ledger with a Central-time timestamp before the games, and a later run grades them from the official box score: WIN, LOSS, or VOID if the player did not play. The last card before kickoff is the one that counts, so the Friday refresh replaces Wednesday's rows for games that have not started. The public record starts at 2026 Week 8; earlier weeks are graded as tests and labeled that way.

### Phase 4 — Website output

The same run writes `latest.js`, a small data file that the public predictor page at cyrusforgesystems.com renders: this week's projections, the passes with reasons, and the season-to-date accuracy record by market and tier. One decision changed the public page late: odds, prices and units were removed. The site tells people who is likely to score and how many yards a quarterback is projected to throw against the market line, and is judged on right or wrong.

### Phase 5 — Automation

The whole run is a scheduled task (Wednesday and Friday, 6:45 PM Central) with the script embedded in its instructions. Each run downloads the ledger and the current site package from Google Drive, runs the five commands, verifies its own outputs (renders the PDF to an image and looks at it, checks the week number, checks the zip contents), saves a new ledger version to Drive, and delivers the PDF, the site zip and a summary. It is told never to invent a line, injury status or result; if something is missing it says so.

### Working with multiple AIs

The project was run as a shared brief with distinct roles: Claude built the model, the pipeline, the website and the automation; Gemini produced the brand imagery (the hawk logo and its turning animation); ChatGPT and Gemini were given the same written brief to critique the approach and propose alternatives, each with a short role prompt first so no model overreached its lane. The founder stayed product owner and made every call. Two lessons: give each model a written role before giving it documents, and judge AI output by testing it, not by how confident it sounds.

### Misses and fixes

- **Daylight-saving bug.** Kickoff times were converted with a fixed one-hour offset from Eastern. Switched to proper time-zone handling (`zoneinfo`, America/Chicago) so November games grade on the right day.
- **Google Sheets reformatting.** The ledger round-trips through a Google Sheet, which silently rewrote ISO timestamps and integers. The loader now normalizes every column on read instead of trusting the file.
- **A bye week looked like a bug.** A test projection for a Detroit back was never graded. The logic was right: Detroit had a bye, and the grader correctly waited for stats that would never come for that week.
- **Base64 transcription errors.** The site was first embedded in the job's instructions as a base64 archive. Three attempts in a row each had a single wrong character, caught by a read-back diff. The archive was replaced with plain-text files, then with a zip fetched from Google Drive, which also removed a 64 KB limit on the job's instructions.
- **The connector can't overwrite.** The Google Drive integration can create files but not replace their content, so each run writes a new dated ledger sheet and the next run picks up the newest one.
- **Scope creep, declined.** Spreads and game totals were on the wish list from day one. They were cut from version one so the two prop markets could be shipped, logged and graded first. They are next.

### What's next

Game-level projections (spread and total) as a third output; a backtest of the player model against historical lines; and pushing `latest.js` to the site repository automatically so the weekly update needs no manual upload.

## Status and limits

- Live since October 2026; the public track record starts with 2026 Week 8.
- The model is market-informed (it uses the spread and total) and has not yet been backtested against historical player lines. Treat the output as research and decision support.
- An accuracy record needs roughly 100 graded projections before hit rates mean much.

## License

MIT (see `LICENSE`). This is an analytics project for information and entertainment; it is not a sportsbook and does not accept wagers.
