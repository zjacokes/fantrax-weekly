"""Export Fantrax league data for roster, trade, and waiver analysis.

Run in Jupyter:
    from fantrax_snapshot import export_snapshot
    path = export_snapshot(LEAGUE_ID, my_team_name="Your team name")

Requires requests for live calls. Uses only read-only documented endpoints.
Sources: https://www.fantrax.com/developer
         https://pkg.go.dev/github.com/pmurley/go-fantrax
The derived roster parser checks the published map/rosterItems/id structure.
If it differs, raw responses are retained and candidate derivation is withheld.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _derive(info, roster_response, registry):
    """Derive ownership by ID; never interpret roster status as availability."""
    teams = info.get("teamInfo")
    pool = info.get("playerInfo")
    rosters = roster_response.get("rosters")
    warnings = []
    result = {"rosters": [], "unrostered_candidates": None, "warnings": warnings}
    if not isinstance(teams, dict) or not teams:
        warnings.append("Team map missing/unrecognized; inspect raw league_info.")
        return result
    if not isinstance(rosters, dict):
        warnings.append("Roster map unrecognized; inspect raw team_rosters.")
        return result
    complete = set(teams) == set(rosters)
    if not complete:
        warnings.append("Team/roster ID sets differ; unrostered list withheld.")
    registry = registry if isinstance(registry, dict) else {}
    pool_ok = isinstance(pool, dict) and bool(pool)
    pool = pool if isinstance(pool, dict) else {}

    def player_details(pid):
        identity = registry.get(pid, {})
        eligibility = pool.get(pid, {})
        identity = identity if isinstance(identity, dict) else {}
        eligibility = eligibility if isinstance(eligibility, dict) else {}
        return {
            "player_id": pid,
            "player_name": identity.get("name") or eligibility.get("name"),
            "nba_team": identity.get("team"),
            "position": identity.get("position"),
            "league_eligible_positions": eligibility.get("eligiblePos"),
            "league_player_status_raw": eligibility.get("status"),
        }

    owned = set()
    for tid, roster in rosters.items():
        if not isinstance(roster, dict) or not isinstance(roster.get("rosterItems"), list):
            complete = False
            warnings.append(f"Unrecognized roster for team {tid}; candidate list withheld.")
            continue
        team = teams.get(tid, {})
        team = team if isinstance(team, dict) else {}
        for item in roster["rosterItems"]:
            if not isinstance(item, dict) or item.get("id") in (None, ""):
                complete = False
                warnings.append(f"Unrecognized roster entry on {tid}; candidate list withheld.")
                continue
            pid = str(item["id"])
            owned.add(pid)  # Includes ACTIVE, RESERVE, MINORS, and INJURED_RESERVE.
            result["rosters"].append({
                **player_details(pid),
                "fantasy_team_id": tid,
                "fantasy_team_name": roster.get("teamName") or team.get("name"),
                "roster_position": item.get("position"),
                "roster_status": item.get("status"),
            })
    if not pool_ok:
        warnings.append("League player pool missing/empty; candidate list withheld.")
    if complete and pool_ok:
        # Restrict to THIS league's pool, not the entire NBA player registry.
        result["unrostered_candidates"] = [
            {**player_details(pid), "availability": "unrostered_eligibility_unverified"}
            for pid in sorted(set(pool) - owned)
        ]
    unresolved = sum(not p["player_name"] for p in result["rosters"])
    if unresolved:
        warnings.append(f"{unresolved} roster entries lack names; IDs retained for reconciliation.")
    result["counts"] = {
        "teams": len(teams), "rosters_returned": len(rosters),
        "roster_entries": len(result["rosters"]), "unique_rostered_players": len(owned),
        "league_player_pool": len(pool),
        "unrostered_candidates": (
            len(result["unrostered_candidates"])
            if result["unrostered_candidates"] is not None else None
        ),
    }
    return result


def export_snapshot(
    league_id,
    *,
    my_team_name=None,
    my_team_id=None,
    league_info=None,
    rosters=None,
    context=None,
    matchup_period=None,
    output_dir=".",
    fetch=None,
):
    """Create one timestamped JSON file; return its absolute pathlib.Path.

    league_info/rosters: optionally reuse the two responses already fetched.
    context: optional dict with budget, bid rules, team plans, and trade notes.
    matchup_period: optional SCORING period number; defaults to API current period.
    fetch: optional callable(endpoint, **params) returning decoded JSON.
           Its params are explicit; it should not silently select another league.

    Endpoint failures are recorded separately, never converted into empty rosters
    or empty draft inventories. Raw draft-pick data is retained to preserve
    ownership, years, rounds, and any special fields actually returned.
    """
    league_id = str(league_id).strip()
    if not league_id:
        raise ValueError("Provide the correct current league ID.")
    now = datetime.now(timezone.utc)
    snapshot = {
        "schema_version": 1,
        "export_started_utc": now.isoformat(),
        "league_id": league_id,
        "my_team_name": my_team_name,
        "my_team_id": my_team_id,
        "context": context or {},
        "raw": {}, "endpoint_status": {}, "errors": {},
        "limitations": [
            "Unrostered candidates are not confirmed claimable free agents.",
            "Check waiver deadlines, locks, eligibility rules, and pending moves in Fantrax.",
            "Budgets, bid history, and trade restrictions may require a separate export or notes.",
            "Draft data reflects only the years and assets returned by the API.",
            "Current-period matchup results may be empty before the season starts.",
            "Reused responses retain their original roster period; collection is not atomic.",
        ],
    }
    owned_session = None
    if fetch is None:
        import requests
        owned_session = requests.Session()

        def fetch(endpoint, **params):
            response = owned_session.get(
                f"https://www.fantrax.com/fxea/general/{endpoint}",
                params=params, timeout=30,
            )
            response.raise_for_status()
            return response.json()

    jobs = [
        ("league_info", "getLeagueInfo", {"leagueId": league_id}, league_info),
        ("team_rosters", "getTeamRosters", {"leagueId": league_id}, rosters),
        ("player_ids", "getPlayerIds", {"sport": "NBA"}, None),
        ("draft_picks", "getDraftPicks", {"leagueId": league_id}, None),
        ("draft_results", "getDraftResults", {"leagueId": league_id}, None),
        ("standings", "getStandings", {"leagueId": league_id}, None),
        ("matchup_scores", "getMatchupScores", {
            "leagueId": league_id,
            **({"period": matchup_period} if matchup_period is not None else {}),
        }, None),
    ]
    try:
        for label, endpoint, params, existing in jobs:
            try:
                data = existing if existing is not None else fetch(endpoint, **params)
                if not isinstance(data, (dict, list)):
                    raise ValueError("Expected a JSON object or array.")
                snapshot["raw"][label] = data
                if isinstance(data, dict):
                    error_keys = [k for k in ("error", "errors", "errorCode") if data.get(k)]
                    if error_keys or data.get("success") is False:
                        raise ValueError("API reports an error; original response retained.")
                required = {
                    "league_info": {"teamInfo", "playerInfo"},
                    "team_rosters": {"period", "rosters"},
                }.get(label, set())
                if required and (not isinstance(data, dict) or not required <= data.keys()):
                    raise ValueError(f"Expected fields missing: {sorted(required)}")
                snapshot["endpoint_status"][label] = {
                    "status": "received", "endpoint": endpoint, "params": params,
                    "source": "existing_response" if existing is not None else "live_request",
                    "recorded_utc": datetime.now(timezone.utc).isoformat(),
                }
                print(f"Received: {label}")
            except Exception as exc:
                # Preserve successes when one optional endpoint fails.
                snapshot["errors"][label] = f"{type(exc).__name__}: {exc}"
                snapshot["endpoint_status"][label] = {"status": "failed", "endpoint": endpoint}
                print(f"Unavailable: {label} ({type(exc).__name__}); continuing.")
    finally:
        if owned_session is not None:
            owned_session.close()

    if not ({"league_info", "team_rosters"} & snapshot["errors"].keys()):
        try:
            snapshot["derived"] = _derive(
                snapshot["raw"]["league_info"], snapshot["raw"]["team_rosters"],
                snapshot["raw"].get("player_ids", {}),
            )
        except Exception as exc:
            snapshot["errors"]["derivation"] = f"{type(exc).__name__}: {exc}"
    snapshot["export_finished_utc"] = datetime.now(timezone.utc).isoformat()
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"fantrax_snapshot_{now:%Y%m%d_%H%M%S_%f}_UTC.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"\nSaved: {path}")
    counts = snapshot.get("derived", {}).get("counts")
    if counts:
        print("Counts:", counts)
    for warning in snapshot.get("derived", {}).get("warnings", []):
        print("Review:", warning)
    if snapshot["errors"]:
        print("Some sections are unavailable; details are included in the file.")
    print("Upload this JSON file for analysis.")
    return path
