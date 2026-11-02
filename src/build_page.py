"""Build docs/index.html from the most recent snapshot.

Usage (from the repo root):
    python src/build_page.py

No LLM yet: this is the plain-data page the commentary will later sit on top of.
"""

import html
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
INTERNAL_DIR = ROOT / "data" / "internal"
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
.notice { padding: 8px 12px; border: 1px solid var(--line); border-radius: 6px; color: var(--muted); }
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


def load_internal():
    """Newest and previous internal-extras files (either may be None)."""
    files = sorted(INTERNAL_DIR.glob("fantrax_internal_*.json"))
    load = lambda f: json.loads(f.read_text(encoding="utf-8"))
    latest = load(files[-1]) if files else None
    previous = None
    for f in reversed(files[:-1]):  # newest earlier file that actually has scores
        data = load(f)
        if data.get("player_scores"):
            previous = data
            break
    return latest, previous


def period_window(league_info, number):
    fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
    for p in league_info.get("scoringPeriods", []):
        if p["number"] == number:
            return datetime.strptime(p["startDate"], fmt), datetime.strptime(p["endDate"], fmt)
    return None


def extras_sections(snap, mine):
    latest, previous = load_internal()
    if not latest:
        return '<p class="notice">Transactions and player Scores not collected yet.</p>'
    if latest["status"].get("auth") != "ok":
        return (f'<p class="notice">Transactions and player Scores unavailable this week '
                f'(Fantrax login: {e(latest["status"].get("auth"))}).</p>')
    parts = []

    tx = latest.get("transactions") or []
    window = period_window(snap.get("raw", {}).get("league_info", {}),
                           snap.get("context", {}).get("target_period"))
    if window:
        start, end = window
        in_week = lambda t: t["processed_utc"] and start <= datetime.fromisoformat(t["processed_utc"]) <= end
        label = "this scoring period"
    else:
        cutoff = datetime.fromisoformat(latest["exported_utc"]) - timedelta(days=7)
        in_week = lambda t: t["processed_utc"] and datetime.fromisoformat(t["processed_utc"]) >= cutoff
        label = "the last 7 days"
    claims = sorted((t for t in tx if t["type"] == "CLAIM" and in_week(t)),
                    key=lambda t: -(t["bid"] or 0))
    drops_by_set = {t["tx_set_id"]: t["player_name"] for t in tx if t["type"] == "DROP"}
    parts.append(f"<h2>Waiver claims, {label}</h2>")
    parts.append(table(
        ["Team", "Added", "Bid", "Dropped", "Type"],
        [(t["team_name"], t["player_name"], f'${t["bid"]:.0f}' if t["bid"] is not None else "",
          drops_by_set.get(t["tx_set_id"], ""), {"WW": "Waivers", "FA": "Free agent"}.get(t["claim_type"], t["claim_type"] or ""))
         for t in claims],
        highlight=lambda r: r[0] == mine,
    ) if claims else '<p class="notice">No claims.</p>')

    scores = {p["player_id"]: p for p in latest.get("player_scores") or []}
    before = {p["player_id"]: p["score"] for p in (previous or {}).get("player_scores") or []}
    my_ids = [p["player_id"] for p in snap.get("derived", {}).get("rosters", [])
              if p["fantasy_team_name"] == mine]
    rows = []
    for pid in my_ids:
        p = scores.get(pid)
        if not p or p["score"] is None:
            continue
        delta = p["score"] - before[pid] if before.get(pid) is not None else None
        rows.append((p["player_name"], f'{p["score"]:.1f}',
                     "" if delta is None else f"{delta:+.1f}", f'{p["stats"]["PTS"] or 0:.1f}'))
    rows.sort(key=lambda r: -float(r[1]))
    parts.append(f"<h2>{e(mine)} player Scores (season to date)</h2>")
    parts.append(table(["Player", "Score", "Change vs last week", "PTS/G"], rows))
    return "\n".join(parts)


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

  {extras_sections(snap, mine)}
</main>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT} from {snapshots[-1].name}")


if __name__ == "__main__":
    main()
