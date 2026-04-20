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
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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

# ═══════════════════════════════════════════════════════════════════
# EMAIL — sends notification after suggestions are updated
# ═══════════════════════════════════════════════════════════════════


def _send_notification_email(to_email: str, username: str, jobs: list):
    """
    Send an HTML email to the user showing their top 5 new job matches.
    Reads SMTP config from .env — same variables as email_notifier.py.
    Returns True on success, False on failure.
    """
    host = os.getenv("EMAIL_HOST")
    port = int(os.getenv("EMAIL_PORT", "587"))
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    from_email = os.getenv("EMAIL_FROM") or user
    use_tls = os.getenv("EMAIL_USE_TLS", "1").lower() in ("1", "true", "yes")

    # Skip silently if SMTP not configured
    if not host or not user or not password:
        print(f"  ⚠️  SMTP not configured — skipping email to {to_email}")
        return False

    if not to_email:
        return False

    # ── Build HTML email body ──────────────────────────────────────
    now = datetime.now().strftime("%d %b %Y %H:%M")
    top_jobs = jobs[:5]

    # Build one row per job
    job_rows = ""
    for i, job in enumerate(top_jobs, 1):
        score = job.get("match_score", 0)
        score_pct = f"{round(score * 100)}%" if score <= 1 else f"{int(score)}%"
        platform = job.get("platform", "Job Board")
        title = job.get("title", "Role not specified")
        company = job.get("company", "Unknown company")
        apply_url = job.get("apply_url", "")

        # Score colour
        if score >= 0.6:
            color = "#10B981"  # green
            label = "Strong Match"
        elif score >= 0.3:
            color = "#F59E0B"  # amber
            label = "Good Match"
        else:
            color = "#6366F1"  # purple
            label = "Partial Match"

        apply_btn = (
            f"""
            <a href="{apply_url}" style="
                display:inline-block;
                padding:6px 14px;
                background:#2563EB;
                color:#fff;
                border-radius:6px;
                text-decoration:none;
                font-size:12px;
                font-weight:600;
            ">Apply →</a>
        """
            if apply_url
            else ""
        )

        job_rows += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;">
            <div style="font-weight:600;font-size:14px;color:#f1f5f9;">{i}. {title}</div>
            <div style="font-size:12px;color:#94a3b8;margin-top:2px;">{company} · {platform}</div>
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;text-align:center;">
            <span style="
                background:{color}22;
                color:{color};
                border:1px solid {color}55;
                border-radius:20px;
                padding:3px 10px;
                font-size:11px;
                font-weight:700;
            ">{score_pct} {label}</span>
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;text-align:center;">
            {apply_btn}
          </td>
        </tr>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0;padding:0;background:#0f0f13;font-family:'Segoe UI',Arial,sans-serif;">
      <div style="max-width:600px;margin:0 auto;padding:32px 16px;">

        <!-- Header -->
        <div style="
            background:linear-gradient(135deg,#2563EB,#7C3AED);
            border-radius:16px 16px 0 0;
            padding:28px 32px;
            text-align:center;
        ">
          <div style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-0.5px;">
            CareerMatch AI
          </div>
          <div style="font-size:13px;color:rgba(255,255,255,0.8);margin-top:4px;">
            Your hourly job suggestions are ready
          </div>
        </div>

        <!-- Body -->
        <div style="
            background:#16213E;
            border:1px solid rgba(124,58,237,0.2);
            border-top:none;
            border-radius:0 0 16px 16px;
            padding:28px 32px;
        ">
          <p style="color:#94a3b8;font-size:14px;margin:0 0 8px;">
            Hi <strong style="color:#f1f5f9;">{username}</strong>,
          </p>
          <p style="color:#94a3b8;font-size:14px;margin:0 0 24px;">
            We refreshed your job suggestions at <strong style="color:#f1f5f9;">{now}</strong>.
            Here are your top {len(top_jobs)} matches:
          </p>

          <!-- Jobs table -->
          <table style="width:100%;border-collapse:collapse;border-radius:10px;overflow:hidden;">
            <thead>
              <tr style="background:rgba(124,58,237,0.15);">
                <th style="padding:10px 16px;text-align:left;font-size:11px;color:#a78bfa;text-transform:uppercase;letter-spacing:0.05em;">Role</th>
                <th style="padding:10px 16px;text-align:center;font-size:11px;color:#a78bfa;text-transform:uppercase;letter-spacing:0.05em;">Match</th>
                <th style="padding:10px 16px;text-align:center;font-size:11px;color:#a78bfa;text-transform:uppercase;letter-spacing:0.05em;">Apply</th>
              </tr>
            </thead>
            <tbody>
              {job_rows}
            </tbody>
          </table>

          <!-- CTA -->
          <div style="text-align:center;margin-top:28px;">
            <a href="http://127.0.0.1:8000/suggestions" style="
                display:inline-block;
                padding:12px 32px;
                background:linear-gradient(135deg,#2563EB,#7C3AED);
                color:#fff;
                border-radius:10px;
                text-decoration:none;
                font-weight:700;
                font-size:14px;
            ">View All {len(jobs)} Suggestions →</a>
          </div>

          <p style="
              color:#475569;
              font-size:11px;
              text-align:center;
              margin-top:24px;
              border-top:1px solid #1e293b;
              padding-top:16px;
          ">
            This email was sent automatically by CareerMatch AI · Suggestions refresh every hour
          </p>
        </div>
      </div>
    </body>
    </html>
    """

    # ── Plain text fallback ────────────────────────────────────────
    plain_lines = [
        f"Hi {username},",
        f"",
        f"Your job suggestions were updated at {now}.",
        f"Here are your top matches:",
        f"",
    ]
    for i, job in enumerate(top_jobs, 1):
        score = job.get("match_score", 0)
        score_pct = f"{round(score * 100)}%" if score <= 1 else f"{int(score)}%"
        plain_lines.append(
            f"{i}. {job.get('title','')} at {job.get('company','')} "
            f"({job.get('platform','')}) — {score_pct} match"
        )
        if job.get("apply_url"):
            plain_lines.append(f"   Apply: {job.get('apply_url')}")
        plain_lines.append("")

    plain_lines.append("View all suggestions: http://127.0.0.1:8000/suggestions")
    plain_lines.append("")
    plain_lines.append("— CareerMatch AI")
    plain_text = "\n".join(plain_lines)

    # ── Send ───────────────────────────────────────────────────────
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"CareerMatch AI — {len(jobs)} new job suggestions ready"
        msg["From"] = from_email
        msg["To"] = to_email

        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(host, port) as server:
            if use_tls:
                server.starttls()
            server.login(user, password)
            server.send_message(msg)

        print(f"  📧 Email sent → {to_email}")
        return True

    except Exception as e:
        print(f"  ❌ Email failed → {to_email}: {e}")
        return False


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
    then replace unapplied suggestions per user and send notification emails.
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
                _send_notification_email(email, username, jobs)
            success += 1
        except Exception as e:
            print(f"  ❌ Save/email failed for user {uid}: {e}")
            failed += 1

    print(f"\n{'='*55}")
    print(f"✅ Match phase done — {success} user(s) updated, {failed} failed")
    print(f"{'='*55}\n")


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

    _scheduler.start()
    jf = _scheduler.get_job("hourly_fetch_jobs")
    jm = _scheduler.get_job("hourly_match_users")
    print(
        "✅ Scheduler started — fetch at :00 each hour, match at :10 each hour + email"
    )
    print(f"   Next fetch: {jf.next_run_time if jf else 'n/a'}")
    print(f"   Next match: {jm.next_run_time if jm else 'n/a'}")

    t = threading.Thread(target=refresh_all_users, daemon=True)
    t.start()
    print("🚀 Initial fetch+match running in background...")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("🛑 Scheduler stopped")
