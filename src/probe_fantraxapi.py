"""One-off probe: what does the unofficial fantraxapi package return for our league?

Usage (from the repo root, inside your venv):
    pip install fantraxapi
    python src/probe_fantraxapi.py

Writes probe_output.json (gitignored) showing the fields each call returns,
or the error it raised (e.g. NotLoggedIn). Lists are truncated so the file
stays small enough to read and share. Read-only: nothing is changed in Fantrax.
"""

import datetime as dt
import json
import os

import requests
from fantraxapi import League

LEAGUE_ID = "4hdci1kmmqx2i3l2"
MY_TEAM_ID = "j9zufumqmqx2i3lu"
SKIP_ATTRS = {"league", "session", "api"}   # back-references that would recurse
MAX_ITEMS, MAX_DEPTH = 15, 5


def dump(obj, depth=0):
    """Turn arbitrary library objects into JSON-friendly dicts for inspection."""
    if depth > MAX_DEPTH:
        return repr(obj)
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        items = list(obj.items())
        out = {str(k): dump(v, depth + 1) for k, v in items[:MAX_ITEMS]}
        if len(items) > MAX_ITEMS:
            out["__truncated__"] = f"{len(items) - MAX_ITEMS} more"
        return out
    if isinstance(obj, (list, tuple, set)):
        seq = list(obj)
        out = [dump(v, depth + 1) for v in seq[:MAX_ITEMS]]
        if len(seq) > MAX_ITEMS:
            out.append(f"... {len(seq) - MAX_ITEMS} more")
        return out
    if hasattr(obj, "__dict__"):
        fields = {
            k: dump(v, depth + 1)
            for k, v in vars(obj).items()
            if not k.startswith("_") and k not in SKIP_ATTRS
        }
        return {"__type__": type(obj).__name__, **fields}
    return repr(obj)


def probe(label, fn, results):
    try:
        results[label] = {"ok": True, "result": dump(fn())}
        print(f"OK     {label}")
    except Exception as exc:  # we want to see every failure mode, not stop at the first
        results[label] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(f"FAILED {label}: {type(exc).__name__}: {exc}")


def make_session():
    """Optional login: reuse the Cookie header from a logged-in browser session.

    Set it in your shell (never in code or git):
        export FANTRAX_COOKIE='<paste the Cookie request header value>'
    """
    cookie = os.environ.get("FANTRAX_COOKIE")
    if not cookie:
        print("FANTRAX_COOKIE not set; trying anonymously.")
        return None
    session = requests.Session()
    session.headers["Cookie"] = cookie
    return session


def main():
    results = {}
    session = make_session()
    league = League(LEAGUE_ID, session=session) if session else League(LEAGUE_ID)
    yesterday = dt.date.today() - dt.timedelta(days=1)

    probe("transactions", lambda: league.transactions(count=25), results)
    probe("scoring_period_results", lambda: league.scoring_period_results(), results)
    probe("standings", lambda: league.standings(), results)
    probe("team_roster_mine", lambda: league.team_roster(MY_TEAM_ID), results)
    probe(f"live_scores_{yesterday}", lambda: league.live_scores(yesterday), results)

    with open("probe_output.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False, default=repr)
    print("\nWrote probe_output.json")


if __name__ == "__main__":
    main()
