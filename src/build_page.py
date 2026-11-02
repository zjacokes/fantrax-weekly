"""Build docs/index.html from the most recent snapshot.

Usage (from the repo root):
    python src/build_page.py

No LLM yet: this is the plain-data page the commentary will later sit on top of.
"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
OUT = ROOT / "docs" / "index.html"

STATUS_ORDER = {"ACTIVE": 0, "RESERVE": 1, "INJURED_RESERVE": 2, "MINORS": 3}

CSS = """
:root { --bg:#fafafa; --fg:#1d1d1f; --muted:#6e6e73; --line:#e3e3e8; --accent:#1d4ed8; --mine:#eef2ff; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#111214; --fg:#ececf1; --muted:#9a9aa3; --line:#2a2b30; --accent:#7aa2ff; --mine:#1c2340; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:15px/1.5 -apple-system, system-ui, "Segoe UI", sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { margin: 0 0 4px; font-size: 1.6rem; }
h2 { margin: 36px 0 8px; font-size: 1.15rem; }
.meta { color: var(--muted); font-size: .85rem; }
.wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: .8rem; text-transform: uppercase; letter-spacing: .03em; }
tr.mine td { background: var(--mine); font-weight: 600; }
"""


def e(value):
    return html.escape(str(value))


def table(headers, rows, highlight=None):
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = []
    for row in rows:
        cls = ' class="mine"' if highlight and highlight(row) else ""
        body.append(f"<tr{cls}>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>")
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def wlt(side):
    return f'{side.get("categoryWins", 0):.0f}-{side.get("categoryLosses", 0):.0f}-{side.get("categoryTies", 0):.0f}'


def main():
    snapshots = sorted(SNAPSHOT_DIR.glob("fantrax_snapshot_*.json"))
    if not snapshots:
        raise SystemExit(f"No snapshots found in {SNAPSHOT_DIR}")
    snap = json.loads(snapshots[-1].read_text(encoding="utf-8"))
    raw = snap.get("raw", {})
    mine = snap.get("my_team_name")
    league_name = raw.get("league_info", {}).get("leagueName", "Fantasy League")

    standings = table(
        ["Rank", "Team", "Cat W-L-T", "Win %", "GB"],
        [
            (s["rank"], s["teamName"], s["points"], f'{s["winPercentage"]:.3f}', s["gamesBack"])
            for s in raw.get("standings", [])
        ],
        highlight=lambda r: r[1] == mine,
    )

    scores = raw.get("matchup_scores", {})
    matchups = table(
        ["Away", "Cats", "Home", "Cats"],
        [
            (m["away"]["teamName"], wlt(m["away"]), m["home"]["teamName"], wlt(m["home"]))
            for m in scores.get("matchups", [])
        ],
        highlight=lambda r: mine in (r[0], r[2]),
    )

    my_roster = sorted(
        (p for p in snap.get("derived", {}).get("rosters", []) if p["fantasy_team_name"] == mine),
        key=lambda p: (STATUS_ORDER.get(p["roster_status"], 9), p["roster_position"] or ""),
    )
    roster = table(
        ["Slot", "Status", "Player", "NBA", "Eligible"],
        [
            (p["roster_position"], p["roster_status"].replace("_", " ").title(),
             p["player_name"] or f'(unknown id {p["player_id"]})', p["nba_team"] or "",
             p["league_eligible_positions"] or "")
            for p in my_roster
        ],
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(league_name)} Weekly</title>
<style>{CSS}</style>
</head>
<body>
<main>
  <h1>{e(league_name)}</h1>
  <p class="meta">Snapshot taken {e(snap.get("export_finished_utc", "?"))} UTC</p>

  <h2>Standings</h2>
  {standings}

  <h2>Matchups: scoring period {e(scores.get("period", "?"))}{"" if snap.get("context", {}).get("period_complete", True) else " (in progress)"}</h2>
  {matchups}

  <h2>{e(mine or "My team")} roster</h2>
  {roster}
</main>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT} from {snapshots[-1].name}")


if __name__ == "__main__":
    main()
