# `budgie calibrate`: a forecast backtest (budgie-ytu.11)

## Goal

Answer "how far should I trust the P10-P90 band?" from the project's own
history. For each past reading date d, rebuild the forecast as it stood on d
and compare what it said about spend at each later reading date t with what
was actually booked at t. An honest 80% band holds the actual ~80% of the time.

## Non-goals

- No tuning, no recalibrated bands, no adjustment of anything: it reports.
- No per-person table (readings are shared, hours are noisy per person; team
  level only, in labor dollars).
- No new simulator, no new precedence rule, no files written.
- Non-labor costs are out: they carry no readings, so there is nothing to score.

## Data

`load_snapshot(project)`: its `readings` (weekly.csv cumulative ISO weeks,
else actuals.csv: Budgie's existing precedence), `people`, `plan`, `span`.
Only people with at least one reading are scored (forecast and actual both).

- Forecast dates d: every distinct reading date with a later target.
- Target dates t > d: every distinct reading date. A target is skipped when
  any scored person has no reading on or after t, because `spent_at` would hold
  the line flat, which is extrapolating a reading.
- Actual at t: sum over scored people of `spent_at(series, t) * rate`. Where one
  person has no reading exactly on t this is interpolation between their
  neighbours (stated assumption, as in `monthly`).

## Method

1. Plan in force at d: `Snapshot.with_plan` with only the plan.csv rows whose
   `effective_date <= d`. The file has no "entered on" date, so effective date
   is the stand-in for "known by d". LIMITATION: a row dated after d that was
   known in advance is invisible to the backtest, and a row back-dated after
   the fact is visible. Documented, not modelled.
2. EAC at d: `at_completion(people, readings, span, as_of=d, plan=plan_d)`.
3. Draw hours once per person with a fixed seed (`default_rng(seed)`; the
   project's `seed`, else 1) and `--iterations` (default 2000, versus
   forecast's 10000, for speed; the band is read at the 10th/90th percentile so
   the sampling noise is a point or two of coverage).
4. Cumulative cost at t per draw, the same shape as `monthly`'s `_cum_hours`
   but at any date: for a person with a reading (when, spent) by d,
   `spent + (total - spent) * (done(t) - done(when)) / (1 - done(when))`;
   with none yet, `total * done(t)`. `done` is `plan.fraction_through`, else
   `elapsed_fraction`. Cost = hours x hourly cost, summed.
5. P10/P50/P90 across draws, then scored against the actual at t.

## Output

Team level, rich table (and PI_BLOCKS figures + table when `blocks.wanted()`):

- Figures: pairs, inside P10-P90, below P10, above P90, median P50 error ($, %).
- Table by horizon: 1-3 weeks, 4-7 weeks, 8+ weeks (lower edges 1, 4, 8; a pair's
  weeks are round(days/7)), each with pairs and the same columns.
- Error = actual - P50; positive means spend ran hotter than the median forecast.
- Options: `--project`, `--seed`, `--iterations` (default 2000, said in the output).

## Honesty rules

- Fewer than 8 pairs (overall or in a horizon row): print
  `not enough history: n pairs`, never a percentage or an error.
- No reading is extrapolated (target rule above); no forecast uses a reading
  dated after d.
- Pairs overlap (one overrun shows in many pairs), so they are not independent
  draws; the output says so. The share is a description, not a significance test.
- Words: "inside / below / above the band", never "accuracy" or a ranking.
- A project with no readings, or only one reading date, reports 0 pairs.

## Tests

`budgie/tests/test_calibrate.py`, hand-built project in tmp_path:

- Actuals follow the plan exactly (people.csv, plan.csv, weekly rows equal to
  the plan's hours at each date): all pairs inside the band, median error ~0%.
- Spend 30% hot (actuals = 1.3 x plan): most actuals above P90.
- Fewer than 8 pairs: `not enough history: n pairs`.
- Plan rows dated after d are not used at d; no-extrapolation target skip.
- CLI: `budgie calibrate --project x`, and the PI_BLOCKS JSON lines.
