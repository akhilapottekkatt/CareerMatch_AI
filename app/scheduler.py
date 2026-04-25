# scheduler.py
"""
Background scheduler — two-phase hourly pipeline:

1. **Fetch** (cron, top of each hour): scrape a global job pool and replace rows in
   the ``jobs`` table.
2. **Match** (cron, 10 minutes past each hour): load jobs from ``jobs``, batch BERT
   score against all active resumes, write ``job_suggestions``, optional email.

On startup, a background thread runs the full pipeline once immediately.
"""

import os
import json
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import models
from app.database import get_connection
from app.resume_extracter import extract_text
from app.company_matcher import (
    gather_union_queries_from_profiles,
    fetch_global_job_pool,
)
from app.email_notifier import send_best_jobs_email

# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — fetch global pool → ``jobs`` table
# ═══════════════════════════════════════════════════════════════════


def sync_global_jobs_to_database():
    """
    Build union search queries from all users with an active resume,
    fetch one deduped global pool, and replace the ``jobs`` catalog.
    """
    print(f"\n{'='*55}")
    print(f"📥 Job catalog sync — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*55}")

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT u.id AS user_id
            FROM users u
            JOIN resumes r ON r.user_id = u.id AND r.is_active = 1
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        print("ℹ️  No users with active resumes — skipping fetch (catalog unchanged)")
        return

    profiles_for_queries: list[dict] = []
    for row in rows:
        uid = row["user_id"]
        profile = models.get_or_create_profile(uid)
        profiles_for_queries.append(
            {
                "skills": json.loads(profile.get("skills") or "[]"),
                "expected_roles": json.loads(profile.get("expected_roles") or "[]"),
            }
        )

    union_queries = gather_union_queries_from_profiles(profiles_for_queries)
    if not union_queries:
        print(
            "ℹ️  No search queries from any profile — skipping fetch (catalog unchanged)"
        )
        return

    global_jobs = fetch_global_job_pool(union_queries, location="India", max_jobs=300)
    n = models.replace_jobs_catalog(global_jobs)
    print(f"✅ Stored {n} job(s) in ``jobs`` table\n")


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — read ``jobs`` → BERT match → ``job_suggestions``
# ═══════════════════════════════════════════════════════════════════


def match_all_users_from_job_catalog():
    """
    Load the global catalog from ``jobs``, batch-match every eligible resume,
    then replace unapplied suggestions per user.
    """
    print(f"\n{'='*55}")
    print(
        f"🔗 User matching from catalog — {datetime.now().strftime('%d %b %Y %H:%M')}"
    )
    print(f"{'='*55}")

    catalog_jobs = models.list_jobs_catalog_for_matching()
    if not catalog_jobs:
        print("ℹ️  ``jobs`` catalog is empty — skipping match")
        return

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT u.id       AS user_id,
                   u.email,
                   u.name,
                   r.id       AS resume_id,
                   r.file_path
            FROM users u
            JOIN resumes r ON r.user_id = u.id AND r.is_active = 1
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        print("ℹ️  No users with active resumes — skipping match")
        return

    print(
        f"👥 Found {len(rows)} user(s) with active resumes · {len(catalog_jobs)} job(s) in catalog\n"
    )

    resume_by_user: dict[int, str] = {}
    row_by_user: dict[int, dict] = {}

    for row in rows:
        uid = row["user_id"]
        row_by_user[uid] = dict(row)
        file_path = row["file_path"]
        if not file_path or not os.path.exists(file_path):
            print(f"  ⚠️  User {uid}: resume file missing — skip matching")
            continue
        text = extract_text(file_path)
        if not text or len(text.strip()) < 50:
            print(f"  ⚠️  User {uid}: could not extract resume text — skip matching")
            continue
        resume_by_user[uid] = text
        print(f"  📄 User {uid}: {len(text)} chars from resume")

    if not resume_by_user:
        print("⚠️  No resume text for any user — skipping BERT")
        return

    print(
        f"\n🤖 Batch matching {len(catalog_jobs)} jobs × {len(resume_by_user)} user(s)..."
    )
    matched = models.match_jobs_batch_users(
        resume_by_user,
        catalog_jobs,
        threshold=0.2,
        top_k=50,
    )

    for uid in list(matched.keys()):
        profile = models.get_or_create_profile(uid)
        jt = (profile.get("job_type") or "").strip()
        if jt and jt.lower() != "any":
            jlist = matched[uid]
            filt = [
                j for j in jlist if jt.lower() in (j.get("job_type", "") or "").lower()
            ]
            matched[uid] = filt if filt else jlist

    success = 0
    failed = 0

    for uid in resume_by_user:
        email = row_by_user[uid]["email"]
        username = row_by_user[uid]["name"]
        jobs = matched.get(uid) or []

        print(f"─── User {uid} ({email}) — {len(jobs)} suggestions above threshold ───")

        try:
            models.delete_unapplied_suggestions(uid)
            if jobs:
                models.insert_job_suggestions(uid, jobs)
            success += 1
        except Exception as e:
            print(f"  ❌ Save/email failed for user {uid}: {e}")
            failed += 1

    print(f"\n{'='*55}")
    print(f"✅ Match phase done — {success} user(s) updated, {failed} failed")
    print(f"{'='*55}\n")


def send_daily_top5_emails():
    """
    Send one daily digest email per user using the latest stored suggestions.
    """
    print(f"\n{'='*55}")
    print(f"📧 Daily digest run — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*55}")

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, email, name
            FROM users
            WHERE email IS NOT NULL AND trim(email) != ''
            ORDER BY id ASC
        """).fetchall()
    finally:
        conn.close()

    sent = 0
    skipped = 0
    failed = 0

    for row in rows:
        uid = row["id"]
        email = row["email"]
        username = row["name"] or "there"
        jobs = models.get_suggestions(uid)[:5]
        if not jobs:
            skipped += 1
            print(f"  ↪️  User {uid}: no suggestions, skipped")
            continue
        ok = send_best_jobs_email(email, jobs, username=username)
        if ok:
            sent += 1
            print(f"  ✅ User {uid}: email sent")
        else:
            failed += 1
            print(f"  ❌ User {uid}: email failed")

    print(f"✅ Daily digest done — sent={sent}, skipped={skipped}, failed={failed}\n")


# ═══════════════════════════════════════════════════════════════════
# FULL PIPELINE (startup thread + optional manual call)
# ═══════════════════════════════════════════════════════════════════


def refresh_all_users():
    """
    Run phase 1 then phase 2 in one process (fetch → DB, then match from DB).
    """
    sync_global_jobs_to_database()
    match_all_users_from_job_catalog()


# ═══════════════════════════════════════════════════════════════════
# SCHEDULER SETUP
# ═══════════════════════════════════════════════════════════════════

_scheduler = None


def start_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        print("⚠️  Scheduler already running — skipping")
        return

    _scheduler = BackgroundScheduler(job_defaults={"misfire_grace_time": 300})

    _scheduler.add_job(
        func=sync_global_jobs_to_database,
        trigger=CronTrigger(minute=0),
        id="hourly_fetch_jobs",
        name="Hourly fetch → jobs table",
        replace_existing=True,
    )
    _scheduler.add_job(
        func=match_all_users_from_job_catalog,
        trigger=CronTrigger(minute=10),
        id="hourly_match_users",
        name="Hourly match users ← jobs table",
        replace_existing=True,
    )
    daily_hour = int(os.getenv("DAILY_EMAIL_HOUR", "9"))
    daily_minute = int(os.getenv("DAILY_EMAIL_MINUTE", "0"))
    _scheduler.add_job(
        func=send_daily_top5_emails,
        trigger=CronTrigger(hour=daily_hour, minute=daily_minute),
        id="daily_top5_email_digest",
        name="Daily top-5 email digest",
        replace_existing=True,
    )

    _scheduler.start()
    jf = _scheduler.get_job("hourly_fetch_jobs")
    jm = _scheduler.get_job("hourly_match_users")
    jd = _scheduler.get_job("daily_top5_email_digest")
    print("✅ Scheduler started — fetch hourly, match hourly, email daily")
    print(f"   Next fetch: {jf.next_run_time if jf else 'n/a'}")
    print(f"   Next match: {jm.next_run_time if jm else 'n/a'}")
    print(f"   Next daily email: {jd.next_run_time if jd else 'n/a'}")

    t = threading.Thread(target=refresh_all_users, daemon=True)
    t.start()
    print("🚀 Initial fetch+match running in background...")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("🛑 Scheduler stopped")
