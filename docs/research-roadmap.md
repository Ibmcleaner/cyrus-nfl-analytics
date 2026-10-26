# Research roadmap: what could move a player's number, and how we will find out

*Written October 26, 2026. The public model is frozen for the 2026 season's beta (two outputs: QB passing yards, RB touchdown probability). Nothing below changes the live model until it has been tested on past seasons and shown to improve accuracy.*

## The rule

A factor earns a place in the model, or on a player's card, only after it has been tested on 2021-2025 data and shown to improve projections out of sample. Until then it is a hypothesis. This is the difference between an analytics product and a column of hunches: we may cite fewer factors than a tipster, but every one we cite comes with a number behind it.

Testing method: hold out one season at a time, fit on the other four, score the projection error (and, for over/under, hit rate against the closing line) with and without the candidate factor. Keep it if it helps on every held-out season, not just on average.

## What is already available in our data (nflverse)

- Game environment: roof (dome, open, closed, outdoors), surface (grass, turf types), temperature, wind, time slot, days of rest, home/away, division game.
- Per player per game: pass attempts, completions, air yards, yards after catch, sacks, interceptions, targets, carries, red-zone opportunities (derivable from play-by-play), snap counts.
- Per team: points, pace, pass/run ratio, and everything the opponent allowed.
- Market context: spread, total, implied team points, moneyline.
- Head coaches per game. Defensive coordinators are not in the data; a hand-maintained table (32 teams x 5 seasons) is needed to test coordinator effects.

## Candidate factors, in order of expected payoff

1. **Attempts first, then efficiency.** Passing yards are attempts times yards per attempt. Project attempts from pace, game script (spread), opponent run/pass tendencies and weather, then efficiency from the matchup. This is the foundation for receiver projections later (targets = team attempts x target share).
2. **Wind.** Sustained wind above about 15 mph measurably cuts passing yards and attempts. Temperature and dome effects are small once wind is separated out; test them anyway.
3. **Pass defense split into secondary and pass rush.** Yards per attempt allowed (coverage) and pressure/sack rate (rush) affect quarterbacks differently. A mobile quarterback against a heavy rush is a different projection from a pocket passer.
4. **Red-zone and goal-line share for running backs.** Carries inside the 10 and inside the 5 predict touchdowns far better than total carries. Also: whether the quarterback or a second back takes goal-line work.
5. **Opponent touchdown allowance by position.** Rushing TDs allowed to backs versus receiving TDs allowed to backs, not the combined number used today.
6. **Defensive coordinator history.** Build the coordinator table, then test whether a quarterback's record against a coordinator's scheme (not just the team) carries any signal after accounting for the defense's current talent. Expect small samples; this may end up as context on the card rather than a model input.
7. **Surface and time slot.** Turf versus grass, and prime-time versus early-window games.
8. **Rest and travel.** Short weeks (Thursday), bye-week bounces, cross-country trips, altitude (Denver).
9. **Injuries beyond the top target.** Offensive line absences for running backs; the second and third receivers for quarterbacks.
10. **Pace and play volume.** Teams that run more plays give everyone more chances; neutral-situation pace is a stable team trait.

## What this unlocks later

- Receiving yards and receptions (needs attempts projection and target share).
- Rushing yards (needs carries projection, run defense split by front, and game script).
- Game lines (spread and total), which many of the same inputs feed.
- A per-player "why" card on the site with only the factors that passed testing, each with its measured effect, so a visitor can see not just the projection but the evidence.

## Credibility checklist

- Every factor shown publicly has a measured effect and a sample size.
- The model's frozen version is dated; changes are logged with the test results that justified them.
- The public accuracy record is never reset when the model changes; a new model version is marked in the ledger and graded alongside the old one.
