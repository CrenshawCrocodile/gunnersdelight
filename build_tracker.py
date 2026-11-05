#!/usr/bin/env python3
"""Rebuild the Rosner's Relegation Battle tracker from live FPL data.

Every run recomputes the whole season from the API, so there is no local state
to drift. Recap prose is the one thing that cannot be derived: it is carried
forward from the previously published artifact (--previous), then from
recaps/gwN.json, and only auto-generated as a last resort.

Exits non-zero with a clear message on any API failure or failed sanity check,
rather than publishing guessed data.
"""
import argparse, datetime as dt, json, os, re, sys

import fetch_fpl as api

LEAGUE_ID = 184717
BUY_IN = 65
EOY_PAYOUTS = ["$712", "$324", "$155"]
CUP_PAYOUT = "$104"
CONTACT = "adamslj5@gmail.com"
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
CHIP_ORDER = ["bboost", "3xc", "freehit", "wildcard"]
CHIP_NAMES = {"bboost": "Bench Boost", "3xc": "Triple Captain",
              "freehit": "Free Hit", "wildcard": "Wild Card"}
TEAM_COLORS = {
    "Arsenal": "#EF0107", "Aston Villa": "#95BFE5", "Bournemouth": "#DA291C",
    "Brentford": "#E30613", "Brighton": "#0057B8", "Chelsea": "#034694",
    "Coventry City": "#78D0F3", "Crystal Palace": "#1B458F", "Everton": "#003399",
    "Fulham": "#1B1B1B", "Hull City": "#F5971D", "Ipswich Town": "#3A64A3",
    "Leeds": "#B39B57", "Liverpool": "#C8102E", "Man City": "#6CABDD",
    "Man Utd": "#DA291C", "Newcastle": "#241F20", "Nott'm Forest": "#DD0000",
    "Spurs": "#132257", "Sunderland": "#EB172B",
}
FALLBACK_COLOR = "#37003C"
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def die(msg):
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(1)


def period_for(month_key):
    """Payout periods: August and September pay out together, then monthly."""
    year, month = int(month_key[:4]), int(month_key[5:7])
    if month in (8, 9):
        return "Aug / Sep"
    return MONTHS[month - 1]


def display_name(el):
    """web_name is often 'B.Fernandes'. Expand just the initial and keep FPL's
    own surname, so this yields 'Bruno Fernandes', not 'Bruno Borges Fernandes'."""
    web = el["web_name"]
    m = re.match(r"^[A-Z]\.\s*(\S.*)$", web)
    if m and el.get("first_name"):
        return "%s %s" % (el["first_name"].strip(), m.group(1).strip())
    return web


def competition_rank(rows, key):
    """Standard competition ranking (1,2,2,4) on descending key."""
    rows = sorted(rows, key=lambda r: -r[key])
    rank = 0
    for i, r in enumerate(rows):
        if i == 0 or r[key] != rows[i - 1][key]:
            rank = i + 1
        r["rank"] = rank
    return rows


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


def collect(league_id=LEAGUE_ID):
    boot = api.bootstrap()
    events = boot["events"]
    final = [e for e in events if e.get("finished") and e.get("data_checked")]
    if not final:
        die("no finalised gameweek yet (need finished and data_checked)")
    current = max(e["id"] for e in final)
    gws = sorted(e["id"] for e in final)
    if gws != list(range(1, current + 1)):
        sys.stderr.write("WARNING: finalised gameweeks are not contiguous: %s\n" % gws)

    months = {e["id"]: e["deadline_time"][:7] for e in events}
    meta, results = api.league(league_id)
    if not results:
        die("league %s returned no standings rows" % league_id)

    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}

    fixtures = api.fixtures()
    fixture_month = {f["id"]: f["kickoff_time"][:7] for f in fixtures if f.get("kickoff_time")}

    # A gameweek's points are tied to the fixture(s) each player's team actually
    # played, not to the gameweek's own deadline. A gameweek's matches can
    # straddle a calendar-month boundary, so keep the per-fixture breakdown
    # ("explain") alongside the gameweek total for accurate month-by-month splits.
    live, live_fixtures = {}, {}
    for gw in gws:
        live[gw] = {}
        live_fixtures[gw] = {}
        for e in api.live(gw)["elements"]:
            pid = e["id"]
            live[gw][pid] = e["stats"]["total_points"]
            per_fixture = {}
            for ex in e.get("explain", []):
                per_fixture[ex["fixture"]] = per_fixture.get(ex["fixture"], 0) + sum(
                    s["points"] for s in ex["stats"])
            live_fixtures[gw][pid] = per_fixture

    entries, picks = {}, {}
    for r in results:
        eid = r["entry"]
        entries[eid] = api.entry(eid)
        for gw in gws:
            picks[(eid, gw)] = api.picks(eid, gw)

    return dict(boot=boot, events=events, current=current, gws=gws, months=months,
                meta=meta, results=results, elements=elements, teams=teams,
                live=live, live_fixtures=live_fixtures, fixture_month=fixture_month,
                entries=entries, picks=picks)


def build(raw, previous=None, recap_dir="recaps"):
    gws, cur, results = raw["gws"], raw["current"], raw["results"]
    picks, live, months = raw["picks"], raw["live"], raw["months"]
    live_fixtures, fixture_month = raw["live_fixtures"], raw["fixture_month"]
    elements, teams, entries = raw["elements"], raw["teams"], raw["entries"]
    total_mgrs = len(results)
    me = {r["entry"] for r in results if r.get("entry") and
          (r["player_name"] or "").strip().lower() == "lyle adams"}

    def pill(pid):
        el = elements[pid]
        tname = teams[el["team"]]["name"]
        return {"name": display_name(el), "pos": POS[el["element_type"]],
                "team": tname, "color": TEAM_COLORS.get(tname, FALLBACK_COLOR)}

    def cume(pid, gw):
        return sum(live[g].get(pid, 0) for g in gws if g <= gw)

    def period_split(eid, gw):
        """Split one manager's one-gameweek score by the calendar month each
        counted player's fixture was actually played in, so a gameweek whose
        matches span two months pays out to both correctly."""
        out = {}
        for pk in picks[(eid, gw)]["picks"]:
            mult = pk["multiplier"]
            if not mult:
                continue
            pid = pk["element"]
            for fid, pts in live_fixtures[gw].get(pid, {}).items():
                mkey = fixture_month.get(fid)
                if mkey is None:
                    die("GW%d fixture %d has no known kickoff date" % (gw, fid))
                p = period_for(mkey)
                out[p] = out.get(p, 0) + pts * mult
        return out

    # ---- per-gameweek standings ----
    # FPL's own `rank` is not reproducible by competition ranking: in one payload
    # it tied 138/138 at 18 and 113/113 at 20 but split 161/161 into 9 and 10. So
    # never out-compute it. Use the API's rank for the current week and its
    # last_rank for the week before; only older weeks, which the API no longer
    # reports, fall back to a derived ranking.
    api_order = {r["entry"]: i for i, r in enumerate(results)}
    api_rank = {r["entry"]: r["rank"] for r in results}
    api_last = {r["entry"]: r["last_rank"] for r in results if r.get("last_rank")}
    ranks_by_gw = {}
    cum_period_pts = {r["entry"]: {} for r in results}
    for gw in gws:
        rows = []
        for r in results:
            eid = r["entry"]
            h = picks[(eid, gw)]["entry_history"]
            split = period_split(eid, gw)
            if sum(split.values()) != h["points"]:
                die("GW%d month split for %s totals %d, API says %d"
                    % (gw, r["entry_name"], sum(split.values()), h["points"]))
            for p, pts in split.items():
                cum_period_pts[eid][p] = cum_period_pts[eid].get(p, 0) + pts
            rows.append({"entry": eid, "name": r["player_name"], "team": r["entry_name"],
                         "total": h["total_points"], "lastGW": h["points"],
                         "transfers": sum(picks[(eid, g)]["entry_history"]["event_transfers"]
                                          for g in gws if g <= gw),
                         "monthPts": cum_period_pts[eid].get(period_for(months[gw]), 0)})
        derived = {r["entry"]: r["rank"] for r in competition_rank(rows, "total")}
        if gw == cur:
            authoritative, source = api_rank, "league API rank"
        elif gw == cur - 1 and len(api_last) == len(results):
            authoritative, source = api_last, "league API last_rank"
        else:
            authoritative, source = None, "derived"
        if authoritative:
            off = [(r["team"], derived[r["entry"]], authoritative[r["entry"]])
                   for r in rows if derived[r["entry"]] != authoritative[r["entry"]]]
            if off:
                sys.stderr.write("NOTE: GW%d %s differs from a derived ranking for %d team(s); "
                                 "using the API value. %s\n" % (gw, source, len(off), off[:5]))
            for r in rows:
                r["rank"] = authoritative[r["entry"]]
        else:
            for r in rows:
                r["rank"] = derived[r["entry"]]
        ranks_by_gw[gw] = {r["entry"]: r["rank"] for r in rows}
        rows.sort(key=lambda r: (r["rank"], api_order[r["entry"]]))
        for r in rows:
            prev = ranks_by_gw.get(gw - 1)
            r["move"] = (prev[r["entry"]] - r["rank"]) if prev else None
            r["isMe"] = r["entry"] in me
            if r["entry"] in me:
                r["commissioner"] = True
        raw.setdefault("standings_by_gw", {})[gw] = rows

    # ---- sanity checks against the API's own numbers ----
    for r in raw["standings_by_gw"][cur]:
        declared = entries[r["entry"]].get("last_deadline_total_transfers")
        if declared is not None and declared != r["transfers"]:
            die("transfer count mismatch for %s: summed %d, entry endpoint says %d"
                % (r["team"], r["transfers"], declared))

    # ---- per-gameweek league metrics ----
    metrics = {}
    for gw in gws:
        cap, own, owned = {}, {}, set()
        for r in results:
            for pk in picks[(r["entry"], gw)]["picks"]:
                pid = pk["element"]
                own[pid] = own.get(pid, 0) + 1
                owned.add(pid)
                if pk["is_captain"]:
                    cap[pid] = cap.get(pid, 0) + 1
        if sum(cap.values()) != total_mgrs:
            die("GW%d captain count is %d, expected %d" % (gw, sum(cap.values()), total_mgrs))
        cpid = max(cap, key=lambda p: (cap[p], live[gw].get(p, 0)))
        tpid = max(owned, key=lambda p: (live[gw].get(p, 0), own[p]))
        top3 = sorted(own, key=lambda p: (-own[p], -cume(p, gw)))[:3]
        metrics[gw] = {
            "mostCaptained": dict(pill(cpid), count=cap[cpid], total=total_mgrs),
            "topPlayer": dict(pill(tpid), pts=live[gw][tpid]),
            "mostOwned": [dict(pill(p), count=own[p], total=total_mgrs,
                               gwPts=live[gw].get(p, 0), seasonPts=cume(p, gw)) for p in top3],
            "_captainPts": live[gw].get(cpid, 0),
            "_topOwners": own[tpid],
        }

    # ---- chips, all season (each chip is available once per half) ----
    chips = []
    for r in results:
        for gw in gws:
            chip = picks[(r["entry"], gw)].get("active_chip")
            if chip:
                chips.append({"manager": r["player_name"], "team": r["entry_name"],
                              "entry": r["entry"], "chip": chip, "gw": gw,
                              "pts": picks[(r["entry"], gw)]["entry_history"]["points"]})
    chips.sort(key=lambda c: (CHIP_ORDER.index(c["chip"]) if c["chip"] in CHIP_ORDER else 9,
                              c["gw"], -c["pts"]))

    # ---- recap prose: previous artifact > committed file > generated ----
    def recap_for(gw):
        if previous:
            prior = (previous.get("gameweeks") or {}).get(str(gw), {}).get("gwSummary")
            if prior:
                return list(prior)
        path = os.path.join(recap_dir, "gw%d.json" % gw)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)["bullets"]
        return auto_recap(gw)

    def auto_recap(gw):
        rows = raw["standings_by_gw"][gw]
        by_pts = sorted(rows, key=lambda r: -r["lastGW"])
        hi, lo = by_pts[0], by_pts[-1]
        lead = rows[0]
        m = metrics[gw]
        out = ["%s leads on %d points after Gameweek %d." % (lead["team"], lead["total"], gw),
               "%s posted the highest score of the week with %d points." % (hi["team"], hi["lastGW"]),
               "%s had the lowest score of the week with %d points." % (lo["team"], lo["lastGW"])]
        movers = [r for r in rows if r.get("move") is not None]
        if movers:
            up = max(movers, key=lambda r: r["move"])
            down = min(movers, key=lambda r: r["move"])
            if up["move"] > 0:
                out.append("%s climbed %d places to %s." % (up["team"], up["move"], ordinal(up["rank"])))
            if down["move"] < 0:
                out.append("%s fell %d places to %s." % (down["team"], abs(down["move"]), ordinal(down["rank"])))
        out.append("%s was the most captained pick with %d of %d armbands, returning %d points."
                   % (m["mostCaptained"]["name"], m["mostCaptained"]["count"], total_mgrs, m["_captainPts"]))
        out.append("The highest scoring player owned in this league was %s with %d points, held by %d of %d teams."
                   % (m["topPlayer"]["name"], m["topPlayer"]["pts"], m["_topOwners"], total_mgrs))
        played = [c for c in chips if c["gw"] == gw]
        if played:
            out.append("%d chip%s played this week: %s." % (
                len(played), "" if len(played) == 1 else "s",
                ", ".join(sorted({CHIP_NAMES.get(c["chip"], c["chip"]) for c in played}))))
        return out

    gameweeks = {}
    for gw in gws:
        m = {k: v for k, v in metrics[gw].items() if not k.startswith("_")}
        gameweeks[str(gw)] = dict(standings=raw["standings_by_gw"][gw],
                                  gwSummary=recap_for(gw), **m)

    # ---- payouts ----
    # A payout period is a calendar window (two, for Aug/Sep), not a set of
    # whole gameweeks, so its status follows today's date rather than which
    # gameweek last finalised.
    order, seen = [], set()
    for e in raw["events"]:
        p = period_for(e["deadline_time"][:7])
        if p not in seen:
            seen.add(p)
            order.append(p)

    period_months = {}
    for mkey in set(months.values()) | set(fixture_month.values()):
        period_months.setdefault(period_for(mkey), set()).add(mkey)

    today_key = dt.date.today().strftime("%Y-%m")
    active = period_for(today_key)

    def period_status(p):
        mkeys = period_months.get(p)
        if not mkeys:
            return "tbd"
        if today_key in mkeys:
            return "live"
        return "final" if max(mkeys) < today_key else "tbd"

    monthly = []
    for p in order:
        payout = 40 if p == "Aug / Sep" else 20
        has_data = any(p in cum_period_pts[r["entry"]] for r in results)
        status = period_status(p)
        if status == "tbd" or not has_data:
            monthly.append({"period": p, "status": "tbd", "leader": None, "pts": None, "payout": payout})
            continue
        tally = {r["player_name"]: cum_period_pts[r["entry"]].get(p, 0) for r in results}
        best = max(tally.values())
        leaders = sorted(n for n, v in tally.items() if v == best)
        monthly.append({"period": p, "status": status,
                        "leader": " and ".join(leaders), "pts": best, "payout": payout})

    top = raw["standings_by_gw"][cur][:3]
    projected = [{"place": ordinal(i + 1), "name": r["name"], "team": r["team"],
                  "pts": r["total"], "payout": EOY_PAYOUTS[i]} for i, r in enumerate(top)]
    projected.append({"place": "Cup Winner", "name": "TBD", "team": "—", "pts": None, "payout": CUP_PAYOUT})

    pot_total = BUY_IN * total_mgrs
    monthly_pool = sum(m["payout"] for m in monthly)
    eoy = pot_total - monthly_pool
    if eoy != sum(int(x.strip("$").replace(",", "")) for x in EOY_PAYOUTS) + int(CUP_PAYOUT.strip("$")):
        sys.stderr.write("WARNING: EOY pool %d does not match the fixed payout table\n" % eoy)

    cur_rows = raw["standings_by_gw"][cur]
    notes = [
        '"Current Month" sums each manager\'s points from games actually played within the active '
        'payout period (%s); a gameweek whose fixtures span two months has its points split between '
        'them. August and September pay out together; every later month stands alone.' % active,
        "The gameweek picker in the header rewinds the Standings, the Recap and the League Metrics "
        "to any completed week. Chips Played and the Payouts tab always show the latest state.",
        "The movement arrow next to each manager's name compares this week's rank to last week's. "
        "Gameweek 1 has no arrows because it was the first standings snapshot.",
        '"Transfers" is each manager\'s total transfers made this season to date. %d have been made league wide so far.'
        % sum(r["transfers"] for r in cur_rows),
        "The field is locked at %d managers for the season. One manager joined after the GW1 deadline had "
        "passed and opted not to participate, so the pot and the standings are final at %d." % (total_mgrs, total_mgrs),
        "Cup Winner payout is still TBD. The FPL Cup is a separate knockout bracket that has not started yet.",
        "Team names in the Recap, the Standings and Chips Played all link to that team's official FPL page. "
        "Recap and Standings links follow the gameweek picker; a chip row links to the gameweek that chip was played.",
    ]

    return {
        "updated": dt.date.today().isoformat(),
        "throughGW": cur,
        "contactEmail": CONTACT,
        "gameweeks": gameweeks,
        "pot": {"totalPot": "$%s" % format(pot_total, ","),
                "buyInCaption": "$%d buy-in × %d" % (BUY_IN, total_mgrs),
                "participants": total_mgrs,
                "eoyPool": "$%s" % format(eoy, ","),
                "monthlyPool": "$%s" % format(monthly_pool, ",")},
        "monthlyWinners": monthly,
        "projected": projected,
        "chips": chips,
        "notes": notes,
    }


def facts(raw, data):
    """Structured inputs for writing this week's recap prose."""
    cur = data["throughGW"]
    wk = data["gameweeks"][str(cur)]
    rows = wk["standings"]
    prev = data["gameweeks"].get(str(cur - 1), {}).get("standings")
    by_pts = sorted(rows, key=lambda r: -r["lastGW"])
    movers = [r for r in rows if r.get("move") is not None]
    return {
        "gameweek": cur,
        "managers": len(rows),
        "leader": {"team": rows[0]["team"], "total": rows[0]["total"], "gwPts": rows[0]["lastGW"]},
        "previousLeader": prev[0]["team"] if prev else None,
        "highestScore": {"team": by_pts[0]["team"], "pts": by_pts[0]["lastGW"],
                         "rank": by_pts[0]["rank"], "move": by_pts[0].get("move")},
        "lowestScore": {"team": by_pts[-1]["team"], "pts": by_pts[-1]["lastGW"],
                        "rank": by_pts[-1]["rank"], "move": by_pts[-1].get("move")},
        "biggestRiser": max(movers, key=lambda r: r["move"], default=None),
        "biggestFaller": min(movers, key=lambda r: r["move"], default=None),
        "mostCaptained": wk["mostCaptained"],
        "topPlayer": wk["topPlayer"],
        "mostOwned": wk["mostOwned"],
        "chipsThisWeek": [c for c in data["chips"] if c["gw"] == cur],
        "transfersThisWeek": sum(r["transfers"] for r in rows) -
                             (sum(r["transfers"] for r in prev) if prev else 0),
        "teamsWithNoTransfersEver": sum(1 for r in rows if r["transfers"] == 0),
        "top": [{"rank": r["rank"], "team": r["team"], "total": r["total"],
                 "gwPts": r["lastGW"], "move": r.get("move")} for r in rows[:6]],
        "bottom": [{"rank": r["rank"], "team": r["team"], "total": r["total"],
                    "gwPts": r["lastGW"], "move": r.get("move")} for r in rows[-3:]],
    }


def render(data, template_path, out_path):
    with open(template_path, encoding="utf-8") as fh:
        tpl = fh.read()
    if "__TRACKER_DATA__" not in tpl:
        die("template %s has no __TRACKER_DATA__ placeholder" % template_path)
    html = tpl.replace("__TRACKER_DATA__", json.dumps(data, ensure_ascii=False, indent=2))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="template.html")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--previous", help="data.json extracted from the live artifact")
    ap.add_argument("--recap", help="override this week's bullets: {\"gw\":N,\"bullets\":[...]}")
    ap.add_argument("--league", type=int, default=LEAGUE_ID)
    args = ap.parse_args()

    previous = None
    if args.previous and os.path.exists(args.previous):
        with open(args.previous, encoding="utf-8") as fh:
            previous = json.load(fh)

    raw = collect(args.league)
    data = build(raw, previous=previous)

    if args.recap:
        with open(args.recap, encoding="utf-8") as fh:
            ov = json.load(fh)
        gw = str(ov["gw"])
        if gw not in data["gameweeks"]:
            die("recap override targets GW%s, which is not a finalised gameweek" % gw)
        data["gameweeks"][gw]["gwSummary"] = ov["bullets"]

    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.outdir, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(facts(raw, data), fh, ensure_ascii=False, indent=2)
    render(data, args.template, os.path.join(args.outdir, "tracker.html"))

    print("Gameweek %d | %d managers | leader %s on %d"
          % (data["throughGW"], len(data["gameweeks"][str(data["throughGW"])]["standings"]),
             data["gameweeks"][str(data["throughGW"])]["standings"][0]["team"],
             data["gameweeks"][str(data["throughGW"])]["standings"][0]["total"]))
    print("Wrote %s/data.json, %s/facts.json, %s/tracker.html" % (args.outdir, args.outdir, args.outdir))


if __name__ == "__main__":
    main()
