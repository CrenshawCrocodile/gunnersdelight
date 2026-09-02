"""Sequential FPL API client. Parallel requests to this API time out, so every
call goes one at a time with a short pause and a few retries."""
import json, os, time, urllib.request

BASE = "https://fantasy.premierleague.com/api"
UA = {"User-Agent": "Mozilla/5.0 (compatible; rosner-tracker/1.0)"}
PAUSE = float(os.environ.get("FPL_PAUSE", "0.4"))


class FPLError(RuntimeError):
    pass


def get(path, tries=3, timeout=45):
    url = "%s/%s" % (BASE, path.lstrip("/"))
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise FPLError("HTTP %s from %s" % (r.status, url))
                return json.loads(r.read().decode())
        except Exception as exc:            # noqa: BLE001 - reported verbatim below
            last = exc
            if attempt < tries - 1:
                time.sleep(2 + 2 * attempt)
    raise FPLError("FPL API call failed after %d attempts: %s -> %r" % (tries, url, last))


def bootstrap():
    return get("bootstrap-static/")


def league(league_id):
    """Classic league standings, following pagination if the league ever grows."""
    page, results, meta = 1, [], None
    while True:
        d = get("leagues-classic/%s/standings/?page_standings=%d" % (league_id, page))
        meta = meta or d["league"]
        results.extend(d["standings"]["results"])
        if not d["standings"].get("has_next"):
            return meta, results
        page += 1
        time.sleep(PAUSE)


def entry(entry_id):
    time.sleep(PAUSE)
    return get("entry/%d/" % entry_id)


def picks(entry_id, gw):
    time.sleep(PAUSE)
    return get("entry/%d/event/%d/picks/" % (entry_id, gw))


def live(gw):
    time.sleep(PAUSE)
    return get("event/%d/live/" % gw)
