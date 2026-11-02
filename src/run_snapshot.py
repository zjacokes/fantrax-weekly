"""Weekly entry point: snapshot the league for the last *completed* scoring period.

Usage (from the repo root):
    python src/run_snapshot.py

The Fantrax API's default "current period" can point at a week that hasn't
started yet, which yields all-zero matchup scores. This script reads the
league's scoring calendar and asks for the most recent period that has ended.
"""

from datetime import datetime, timezone
from pathlib import Path

import requests

from fantrax_snapshot import export_snapshot

LEAGUE_ID = "4hdci1kmmqx2i3l2"
MY_TEAM_NAME = "Hornets"
MY_TEAM_ID = "j9zufumqmqx2i3lu"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"


def last_completed_period(league_info, now=None):
    """Return the number of the latest scoring period whose end date has passed."""
    now = now or datetime.now(timezone.utc)
    finished = [
        p["number"]
        for p in league_info.get("scoringPeriods", [])
        if datetime.strptime(p["endDate"], "%Y-%m-%dT%H:%M:%S.%f%z") < now
    ]
    return max(finished) if finished else None


def main():
    response = requests.get(
        "https://www.fantrax.com/fxea/general/getLeagueInfo",
        params={"leagueId": LEAGUE_ID},
        timeout=30,
    )
    response.raise_for_status()
    info = response.json()

    period = last_completed_period(info)
    print(f"Last completed scoring period: {period}")

    export_snapshot(
        LEAGUE_ID,
        my_team_name=MY_TEAM_NAME,
        my_team_id=MY_TEAM_ID,
        league_info=info,          # reuse; avoids a second call
        matchup_period=period,     # None falls back to the API default
        output_dir=OUTPUT_DIR,
    )


if __name__ == "__main__":
    main()
