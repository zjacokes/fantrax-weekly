"""Second probe: raw Fantrax internal-API responses, bypassing fantraxapi's parsers.

Why: fantraxapi's parsers assume a points league. In this category/FAAB league,
its transaction parser chokes (it expects a date where the bid amount sits) and
fantasy-point fields come back empty. The login itself works, so we read the
raw JSON and decide what to parse ourselves.

Usage (same terminal where FANTRAX_COOKIE is exported):
    python src/probe_raw.py

Writes probe_raw.json (gitignored). Read-only calls only.
"""

import json
import os

import requests
from fantraxapi.api import Method, _request

LEAGUE_ID = "4hdci1kmmqx2i3l2"
MY_TEAM_ID = "j9zufumqmqx2i3lu"
MAX_LIST = 40  # keep the file readable; we only need the shape plus some rows


def trim(obj, depth=0):
    if depth > 12:
        return "..."
    if isinstance(obj, dict):
        return {k: trim(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        out = [trim(v, depth + 1) for v in obj[:MAX_LIST]]
        if len(obj) > MAX_LIST:
            out.append(f"... {len(obj) - MAX_LIST} more")
        return out
    return obj


def main():
    cookie = os.environ.get("FANTRAX_COOKIE")
    if not cookie:
        raise SystemExit("Set FANTRAX_COOKIE first (see earlier instructions).")
    session = requests.Session()
    session.headers["Cookie"] = cookie

    calls = {
        # Transaction history; we expect bid amounts in the row cells.
        "transactions": Method("getTransactionDetailsHistory", maxResultsPerPage="50"),
        # Roster with the stats view; any per-player score column should show up here.
        "my_roster_stats": Method("getTeamRosterInfo", teamId=MY_TEAM_ID, view="STATS"),
        # Experimental: the player-list endpoint the website's Players page uses.
        # Not in fantraxapi; if Fantrax rejects it we just record the error.
        "player_list_experimental": Method("getPlayerStats", statusOrTeamFilter="ALL", pageNumber="1"),
    }

    results = {}
    for label, method in calls.items():
        try:
            results[label] = {"ok": True, "raw": trim(_request(LEAGUE_ID, method, session=session))}
            print(f"OK     {label}")
        except Exception as exc:
            results[label] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:2000]}
            print(f"FAILED {label}: {type(exc).__name__}")

    with open("probe_raw.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print("\nWrote probe_raw.json")


if __name__ == "__main__":
    main()
