"""
Quick manual mailer test.

How to use:
1) Set TO_EMAIL below to a registered user (uses real job_suggestions if found)
   or any email (falls back to sample rows for SMTP-only testing).
2) Ensure your .env has SMTP credentials.
3) Run from project root: python3 scripts/test_mailer.py
"""

import os
from pathlib import Path
import sys

# Ensure project root is importable and DB path resolves when cwd differs
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.email_notifier import send_best_jobs_email
from app import models

# TODO: set this before running
TO_EMAIL = "replace-with-your-email@example.com"


def _dummy_jobs():
    return [
        {
            "title": "Python Backend Developer",
            "company": "Acme Labs",
            "platform": "RemoteOK",
            "apply_url": "https://example.com/jobs/python-backend",
            "match_score": 0.82,
        },
        {
            "title": "FastAPI Engineer",
            "company": "NextStack",
            "platform": "LinkedIn",
            "apply_url": "https://example.com/jobs/fastapi",
            "match_score": 0.77,
        },
        {
            "title": "ML Engineer",
            "company": "DataNova",
            "platform": "Indeed",
            "apply_url": "https://example.com/jobs/ml-engineer",
            "match_score": 0.69,
        },
        {
            "title": "Software Engineer (Backend)",
            "company": "CloudForge",
            "platform": "JSearch",
            "apply_url": "https://example.com/jobs/backend-se",
            "match_score": 0.63,
        },
        {
            "title": "API Integration Engineer",
            "company": "StreamWorks",
            "platform": "RemoteOK",
            "apply_url": "https://example.com/jobs/api-integration",
            "match_score": 0.58,
        },
    ]


def _suggestions_for_mailer(rows: list) -> list:
    """Map DB job_suggestion rows to dicts expected by send_best_jobs_email."""
    out = []
    for r in rows[:5]:
        out.append(
            {
                "title": r.get("title") or "",
                "company": r.get("company") or "",
                "platform": r.get("platform") or "",
                "apply_url": r.get("apply_url") or "",
                "match_score": r.get("match_score", 0.0) or 0.0,
            }
        )
    return out


def main() -> None:
    user = models.get_user_by_email(TO_EMAIL.strip().lower())
    if user:
        pending = models.get_suggestions(user["id"])
        if pending:
            jobs = _suggestions_for_mailer(pending)
            username = (user.get("name") or "").strip() or "there"
            print(
                f"Using {len(jobs)} real suggestion(s) from DB for user id={user['id']} ({TO_EMAIL})."
            )
        else:
            jobs = _dummy_jobs()
            username = (user.get("name") or "").strip() or "there"
            print(
                "User exists but has no pending (unapplied) suggestions — "
                "using sample data for layout/SMTP test."
            )
    else:
        jobs = _dummy_jobs()
        username = "there"
        print(
            f"No account with email {TO_EMAIL!r} — using sample data for layout/SMTP test."
        )

    ok = send_best_jobs_email(
        to_email=TO_EMAIL,
        best_companies=jobs,
        username=username,
    )
    print("Mailer status:", "SUCCESS" if ok else "FAILED")


if __name__ == "__main__":
    main()
