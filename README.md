# Rosner's Relegation Battle — tracker builder

Rebuilds the league tracker from the public Fantasy Premier League API and
publishes it to a Claude Artifact. League **184717**, 23 managers, 2026/27.

Live tracker: https://claude.ai/code/artifact/1dbdb62f-c2bc-45b2-8cc7-138c72d39d6f

## Running it

```bash
python3 build_tracker.py --previous out/previous.json
```

No dependencies beyond the Python 3 standard library. Writes to `out/`:

| file | what it is |
|---|---|
| `data.json` | the full `DEFAULT_DATA` payload |
| `facts.json` | structured facts for writing this week's recap prose |
| `tracker.html` | the finished page, ready to publish |

Useful flags: `--previous FILE` (carry recap prose forward from the live
artifact), `--recap FILE` (`{"gw": N, "bullets": [...]}` to override one week),
`--template`, `--outdir`, `--league`.

## How it works

Every run recomputes the entire season from the API, so there is no local state
that can drift. Requests are sequential on purpose: parallel calls to this API
time out.

**Gameweek selection.** Only gameweeks that are both `finished` and
`data_checked` are used, so a week is never published before bonus points land.

**Ranks.** FPL's own `rank` is not reproducible by competition ranking — one
payload tied 138/138 at 18 and 113/113 at 20 but split 161/161 into 9 and 10.
So the builder never out-computes it: it uses the API's `rank` for the current
week and `last_rank` for the week before. Only older weeks, which the API no
longer reports, fall back to a derived ranking, and any disagreement is logged.

**Payout periods.** August and September pay out together; every later month
stands alone. "Current Month" sums the active period, where "active" is
today's calendar month (not the month of the last finalised gameweek). A
period that is no longer active flips to a `final` status, shown on the page
as "Paid" with its winner locked in.

**Recap prose.** The one thing that cannot be derived. Precedence:
`--previous` (the live artifact, so past weeks keep their wording) →
`recaps/gwN.json` → auto-generated from the week's facts. A new gameweek always
starts auto-generated and is meant to be rewritten from `facts.json`.

## Sanity checks

The build exits non-zero rather than publishing questionable data if the current
week's ranks disagree with the league API, transfer counts disagree with the
entry endpoint, captain picks do not sum to the number of managers, the template
placeholder is missing, or no gameweek is finalised yet.

## Weekly routine

A scheduled cloud agent runs daily, exits quietly when no new gameweek has
finalised, and otherwise rebuilds, rewrites the newest recap, and republishes to
the same artifact URL. See `ROUTINE.md` for the exact prompt.
