"""Build a newsletter issue from the command line.

    python -m app.newsletter.build                          # last completed week (ending Sunday)
    python -m app.newsletter.build --week-end 2026-10-11    # a specific week
    python -m app.newsletter.build --week-end 2026-10-11 --force   # overwrite an existing issue
    python -m app.newsletter.build --preview                # current week so far, printed, never saved
"""

import argparse
import json
from datetime import date

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.newsletter import service


def _counts(issue: dict) -> dict:
    return {
        "id": issue["id"],
        "week": f"{issue['week_start']}..{issue['week_end']}",
        "partial": issue["partial"],
        "headline": issue["headline"],
        "top_filings": f"{len(issue['top_filings'])} shown of {issue['top_filings_total']}",
        "dilution_watch": len(issue["dilution_watch"]),
        "runway_lookups": issue["runway_lookups"],
        "serious_halts": f"{len(issue['serious_halts'])} shown of {issue['serious_halts_total']}",
        "track_record": {k: issue["track_record"][k] for k in ("recorded", "complete_20d", "collecting")} | {"rows": len(issue["track_record"]["rows"])},
        "research_note": bool(issue["research_note"]),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Build a Small-Cap Filing Radar issue")
    p.add_argument("--week-end", type=date.fromisoformat, help="Last day of the week (normally a Sunday). Default: last completed week")
    p.add_argument("--force", action="store_true", help="Rebuild and overwrite an existing issue")
    p.add_argument("--preview", action="store_true", help="Build the current week so far without saving")
    args = p.parse_args()

    s = get_settings()
    init_db()
    kw = {"user_agent": s.sec_user_agent, "public_base_url": s.public_base_url}
    with SessionLocal() as session:
        if args.preview:
            issue = service.preview(session, s.data_dir, **kw)
            print(json.dumps(_counts(issue), indent=2))
            return
        week_end = args.week_end or service.last_completed_week_end(service.today_et())
        issue, created = service.generate(session, s.data_dir, week_end, force=args.force, **kw)
    print(("Built" if created else "Exists (use --force to rebuild)") + f": {service.issue_dir(s.data_dir)}/{issue['id']}.json|.md|.html")
    print(json.dumps(_counts(issue), indent=2))


if __name__ == "__main__":
    main()
