"""Weekly entry point: snapshot the league for the most recently *finished* matchup week.

Usage (from the repo root):
    python src/run_snapshot.py

Why not just use the API's "current period"? On Monday morning Fantrax already
reports next week's period as current (all zeros). And the league calendar
closes each week at Monday's first tip-off, not at midnight Sunday, so a naive
"period whose end date has passed" check misses the week whose games all
finished last night.

Rule used here: the target week is the scoring period that contained the
moment 12 hours ago. Run Monday morning ET and that lands on Sunday evening,
i.e. the week that just finished, before any of next week's games exist.
If the target period still has more than a day left (e.g. the two-week periods
around the NBA Cup and All-Star break), the snapshot is labeled in-progress.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from fantrax_internal import export_internal
from fantrax_snapshot import export_snapshot

LEAGUE_ID = "4hdci1kmmqx2i3l2"
MY_TEAM_NAME = "Hornets"
MY_TEAM_ID = "j9zufumqmqx2i3lu"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR = DATA_DIR / "snapshots"
INTERNAL_DIR = DATA_DIR / "internal"

LOOKBACK = timedelta(hours=12)
COMPLETE_IF_ENDS_WITHIN = timedelta(hours=24)
FANTRAX_TIME = "%Y-%m-%dT%H:%M:%S.%f%z"


def target_period(league_info, now=None):
    """Return (period_number, is_complete), or (None, False) outside the season."""
    now = now or datetime.now(timezone.utc)
    probe = now - LOOKBACK
    for p in league_info.get("scoringPeriods", []):
        start = datetime.strptime(p["startDate"], FANTRAX_TIME)
        end = datetime.strptime(p["endDate"], FANTRAX_TIME)
        if start <= probe <= end:
            return p["number"], (end - now) <= COMPLETE_IF_ENDS_WITHIN
    return None, False


def main():
    response = requests.get(
        "https://www.fantrax.com/fxea/general/getLeagueInfo",
        params={"leagueId": LEAGUE_ID},
        timeout=30,
    )
    response.raise_for_status()
    info = response.json()

    period, complete = target_period(info)
    print(f"Target scoring period: {period} ({'complete' if complete else 'IN PROGRESS'})")

    export_snapshot(
        LEAGUE_ID,
        my_team_name=MY_TEAM_NAME,
        my_team_id=MY_TEAM_ID,
        league_info=info,
        matchup_period=period,
        context={"target_period": period, "period_complete": complete},
        output_dir=OUTPUT_DIR,
    )

    # Logged-in extras (transactions + player Scores). Never fails the run:
    # if the cookie is missing or expired, the file records why and we move on.
    export_internal(
        LEAGUE_ID,
        output_dir=INTERNAL_DIR,
        context={"target_period": period, "period_complete": complete},
    )


if __name__ == "__main__":
    main()
