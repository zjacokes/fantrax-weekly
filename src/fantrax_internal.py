"""Logged-in extras from Fantrax's internal API: transactions (with FAAB bids)
and every player's Fantrax "Score".

These need a browser cookie (FANTRAX_COOKIE). The cookie WILL expire at some
point, so nothing here is allowed to break the weekly run: every fetch returns
a status, and callers write whatever succeeded.

Writes data/internal/fantrax_internal_<UTC timestamp>.json with compact,
already-parsed rows (not the raw responses, which are mostly UI metadata).
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

URL = "https://www.fantrax.com/fxpa/req"
EASTERN = ZoneInfo("America/New_York")
TX_DATE_FORMAT = "%a %b %d, %Y, %I:%M%p"   # "Sun Nov 1, 2026, 3:00AM" (Fantrax labels it EST)
PAUSE_SECONDS = 0.5                        # be polite: ~70 small requests per weekly run
MAX_PAGES = 200                            # hard stop so a paging bug can't loop forever


class AuthExpired(Exception):
    """Cookie missing, expired, or not a member of the league."""


def call(session, league_id, method, **data):
    payload = {"msgs": [{"method": method, "data": {"leagueId": league_id, **data}}]}
    resp = session.post(URL, params={"leagueId": league_id}, json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    code = body.get("pageError", {}).get("code")
    if code in ("WARNING_NOT_LOGGED_IN", "NOT_MEMBER_OF_LEAGUE"):
        raise AuthExpired(code)
    if code:
        raise RuntimeError(f"Fantrax pageError {code}: {body['pageError']}")
    return body["responses"][0]["data"]


def paged(session, league_id, method, rows_of, **data):
    """Yield rows from every page; Fantrax reports totalNumPages on each response."""
    page = 1
    while page <= MAX_PAGES:
        resp = call(session, league_id, method, pageNumber=str(page), **data)
        yield from (r for r in rows_of(resp) if isinstance(r, dict))
        total = resp.get("paginatedResultSet", {}).get("totalNumPages", 1)
        if page >= total:
            return
        page += 1
        time.sleep(PAUSE_SECONDS)


# ---------- transactions ----------

def parse_transactions(rows):
    """Flatten claim/drop rows.

    Fantrax groups a claim and its paired drop under one txSetId and only puts
    the team and date cells on the group's first row (HTML rowspan), so we carry
    those forward within the group.
    """
    out, group = [], {}
    for row in rows:
        cells = {c.get("key"): c for c in row.get("cells", [])}
        tx_set = row.get("txSetId")
        if "team" in cells:  # first row of a group
            group = {
                "tx_set_id": tx_set,
                "team_id": cells["team"].get("teamId"),
                "team_name": cells["team"].get("content"),
                "processed_raw": cells.get("date", {}).get("content"),
            }
        elif group.get("tx_set_id") != tx_set:
            group = {"tx_set_id": tx_set}  # orphan row (group split across pages)

        processed = None
        if group.get("processed_raw"):
            processed = (datetime.strptime(group["processed_raw"], TX_DATE_FORMAT)
                         .replace(tzinfo=EASTERN).astimezone(timezone.utc).isoformat())
        bid_text = cells.get("bid", {}).get("content") or ""
        scorer = row.get("scorer", {})
        out.append({
            "tx_set_id": tx_set,
            "team_id": group.get("team_id"),
            "team_name": group.get("team_name"),
            "type": row.get("transactionCode"),          # CLAIM / DROP
            "claim_type": row.get("claimType") or None,  # FA / WW (waivers)
            "bid": float(bid_text) if bid_text else None,
            "processed_utc": processed,
            "daily_period": int(cells["week"]["content"]) if "week" in cells else None,
            "player_id": scorer.get("scorerId"),
            "player_name": scorer.get("name"),
            "nba_team": scorer.get("teamShortName"),
            "executed": row.get("executed"),
        })
    return out


def fetch_transactions(session, league_id):
    rows = paged(session, league_id, "getTransactionDetailsHistory",
                 lambda r: r.get("table", {}).get("rows", []),
                 maxResultsPerPage="200")
    return parse_transactions(list(rows))


# ---------- player scores ----------

def _num(text):
    text = (text or "").replace("%", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_player_page(resp):
    headers = [h.get("shortName") for h in resp.get("tableHeader", {}).get("cells", [])]
    out = []
    for row in resp.get("statsTable", []):
        if not isinstance(row, dict):
            continue
        scorer = row.get("scorer", {})
        values = dict(zip(headers, (c.get("content") for c in row.get("cells", []))))
        out.append({
            "player_id": scorer.get("scorerId"),
            "player_name": scorer.get("name"),
            "nba_team": scorer.get("teamShortName"),
            "positions": scorer.get("posShortNames"),
            "fantasy_status": values.get("Sta"),    # fantasy team abbrev, or FA/W
            "age": _num(values.get("Age")),
            "score": _num(values.get("Score")),
            "rank": _num(values.get("Rk")),
            "pct_rostered": _num(values.get("Ros")),
            "stats": {k: _num(values.get(k)) for k in
                      ("FG%", "3PTM", "FT%", "PTS", "REB", "AST", "ST", "BLK", "TO")},
        })
    return out


def fetch_player_scores(session, league_id):
    # Season-to-date per-game view, sorted by Score. Snapshotting this weekly is
    # what turns Fantrax's single current number into a season-long time series.
    players = []
    page = 1
    while page <= MAX_PAGES:
        resp = call(session, league_id, "getPlayerStats",
                    statusOrTeamFilter="ALL", sortType="SCORE",
                    maxResultsPerPage="500", pageNumber=str(page))
        players.extend(parse_player_page(resp))
        if page >= resp.get("paginatedResultSet", {}).get("totalNumPages", 1):
            break
        page += 1
        time.sleep(PAUSE_SECONDS)
    return players


# ---------- entry point ----------

def export_internal(league_id, output_dir, context=None):
    """Fetch everything we can; never raise. Returns the status dict."""
    started = datetime.now(timezone.utc)
    result = {"exported_utc": started.isoformat(), "context": context or {},
              "status": {}, "transactions": None, "player_scores": None}

    cookie = os.environ.get("FANTRAX_COOKIE")
    if not cookie:
        result["status"] = {"auth": "no_cookie"}
    else:
        session = requests.Session()
        session.headers["Cookie"] = cookie
        session.headers["User-Agent"] = "Mozilla/5.0 (weekly league snapshot)"
        result["status"]["auth"] = "ok"
        for name, fn in (("transactions", fetch_transactions),
                         ("player_scores", fetch_player_scores)):
            try:
                result[name] = fn(session, league_id)
                result["status"][name] = f"ok ({len(result[name])} rows)"
            except AuthExpired as exc:
                result["status"]["auth"] = f"expired ({exc})"
                result["status"][name] = "skipped: auth"
                break
            except Exception as exc:  # degrade, don't die
                result["status"][name] = f"error: {type(exc).__name__}: {exc}"[:500]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"fantrax_internal_{started:%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Internal extras -> {path.name}: {result['status']}")
    return result["status"]
