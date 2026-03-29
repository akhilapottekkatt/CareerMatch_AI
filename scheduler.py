# scheduler.py
"""
Background scheduler — runs every 1 hour automatically.
After each refresh, sends an email to each user with their
top 5 new job suggestions.
"""

import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text       import MIMEText
from datetime              import datetime
from apscheduler.schedulers.background import BackgroundScheduler

import models
from database  import get_connection
from resume_extracter import extract_text
from company_matcher  import get_best_matching_companies_from_profile


# ═══════════════════════════════════════════════════════════════════
# EMAIL — sends notification after suggestions are updated
# ═══════════════════════════════════════════════════════════════════

def _send_notification_email(to_email: str, username: str, jobs: list):
    """
    Send an HTML email to the user showing their top 5 new job matches.
    Reads SMTP config from .env — same variables as email_notifier.py.
    Returns True on success, False on failure.
    """
    host       = os.getenv("EMAIL_HOST")
    port       = int(os.getenv("EMAIL_PORT", "587"))
    user       = os.getenv("EMAIL_USER")
    password   = os.getenv("EMAIL_PASSWORD")
    from_email = os.getenv("EMAIL_FROM") or user
    use_tls    = os.getenv("EMAIL_USE_TLS", "1").lower() in ("1", "true", "yes")

    # Skip silently if SMTP not configured
    if not host or not user or not password:
        print(f"  ⚠️  SMTP not configured — skipping email to {to_email}")
        return False

    if not to_email:
        return False

    # ── Build HTML email body ──────────────────────────────────────
    now        = datetime.now().strftime("%d %b %Y %H:%M")
    top_jobs   = jobs[:5]

    # Build one row per job
    job_rows = ""
    for i, job in enumerate(top_jobs, 1):
        score     = job.get("match_score", 0)
        score_pct = f"{round(score * 100)}%" if score <= 1 else f"{int(score)}%"
        platform  = job.get("platform",  "Job Board")
        title     = job.get("title",     "Role not specified")
        company   = job.get("company",   "Unknown company")
        apply_url = job.get("apply_url", "")

        # Score colour
        if score >= 0.6:
            color = "#10B981"   # green
            label = "Strong Match"
        elif score >= 0.3:
            color = "#F59E0B"   # amber
            label = "Good Match"
        else:
            color = "#6366F1"   # purple
            label = "Partial Match"

        apply_btn = f"""
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
        """ if apply_url else ""

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
        score     = job.get("match_score", 0)
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
        msg["From"]    = from_email
        msg["To"]      = to_email

        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_body,  "html"))

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
# CORE JOB — runs every hour for every user
# ═══════════════════════════════════════════════════════════════════

def refresh_all_users():
    """
    Called every hour by the scheduler.
    For each user with an active resume:
      1. Fetch fresh jobs
      2. BERT match
      3. Save suggestions
      4. Send email notification
    """
    print(f"\n{'='*55}")
    print(f"⏰ Hourly job refresh started — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*55}")

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT u.id       AS user_id,
                   u.email,
                   u.username,
                   r.id       AS resume_id,
                   r.file_path
            FROM users u
            JOIN resumes r ON r.user_id = u.id AND r.is_active = 1
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        print("ℹ️  No users with active resumes — skipping")
        return

    print(f"👥 Found {len(rows)} user(s)\n")

    success = 0
    failed  = 0

    for row in rows:
        user_id   = row["user_id"]
        email     = row["email"]
        username  = row["username"]
        resume_id = row["resume_id"]
        file_path = row["file_path"]

        print(f"─── User {user_id} ({email}) ───────────────────────")

        try:
            new_jobs = _refresh_user(user_id, resume_id, file_path)

            # Send email only if we got new jobs
            if new_jobs:
                _send_notification_email(email, username, new_jobs)

            success += 1

        except Exception as e:
            print(f"  ❌ Failed for user {user_id}: {e}")
            failed += 1

    print(f"\n{'='*55}")
    print(f"✅ Refresh done — {success} success, {failed} failed")
    print(f"{'='*55}\n")


def _refresh_user(user_id: int, resume_id: int, file_path: str) -> list:
    """
    Refresh job suggestions for one user.
    Returns the list of new jobs saved (empty list if nothing saved).
    """

    # ── Step 1: Check file exists ──
    if not file_path or not os.path.exists(file_path):
        print(f"  ⚠️  Resume file not found — skipping")
        return []

    # ── Step 2: Extract text ──
    text = extract_text(file_path)
    if not text or len(text.strip()) < 50:
        print(f"  ⚠️  Could not extract text — skipping")
        return []

    print(f"  📄 {len(text)} chars extracted")

    # ── Step 3: Build profile ──
    profile = models.get_or_create_profile(user_id)
    full_profile = {
        "skills":             json.loads(profile.get("skills")         or "[]"),
        "experience_years":   profile.get("experience_years",          0),
        "expected_roles":     json.loads(profile.get("expected_roles") or "[]"),
        "preferred_location": profile.get("preferred_location",        ""),
        "job_type":           profile.get("job_type",                  ""),
    }

    if not full_profile["skills"] and not full_profile["expected_roles"]:
        print(f"  ⚠️  No skills or roles — skipping")
        return []

    print(f"  ⚡ {len(full_profile['skills'])} skills found")

    # ── Step 4: Fetch jobs ──
    print(f"  🔍 Fetching jobs...")
    raw_jobs = get_best_matching_companies_from_profile(full_profile, limit=100)
    print(f"  📦 {len(raw_jobs)} raw jobs fetched")

    if not raw_jobs:
        print(f"  ⚠️  No jobs fetched — keeping existing suggestions")
        return []

    # ── Step 5: BERT match ──
    best_matches = models.match_jobs_to_resume(text, raw_jobs, threshold=0.2)
    if not best_matches:
        best_matches = raw_jobs[:50]
        print(f"  ℹ️  BERT fallback — using top 50 raw jobs")

    print(f"  🎯 {len(best_matches)} matched jobs")

    # ── Step 6: Save — only deletes unapplied, keeps applied ──
    
    # ── Step 6: Save WITHOUT deleting old + avoid duplicates ──

    # Get already stored job URLs
    existing_jobs = models.get_suggestions(user_id)
    existing_urls = {j["apply_url"] for j in existing_jobs if j.get("apply_url")}

    # Filter only NEW jobs
    new_jobs = [j for j in best_matches if j.get("url") not in existing_urls]

    if not new_jobs:
        print("  ℹ️ No new jobs — skipping save")
        return []

    # Save only new jobs
    models.insert_job_suggestions(user_id, new_jobs)

    print(f"  💾 Saved {len(new_jobs)} NEW suggestions (no duplicates)")
    return new_jobs


# ═══════════════════════════════════════════════════════════════════
# SCHEDULER SETUP
# ═══════════════════════════════════════════════════════════════════

_scheduler = None


def start_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        print("⚠️  Scheduler already running — skipping")
        return

    _scheduler = BackgroundScheduler(
        job_defaults={"misfire_grace_time": 300}
    )

    _scheduler.add_job(
        func             = refresh_all_users,
        trigger          = "interval",
        hours            = 1,
        id               = "hourly_refresh",
        name             = "Hourly job suggestions refresh",
        replace_existing = True,
    )

    _scheduler.start()
    print("✅ Scheduler started — refreshes every 1 hour + sends email")
    print(f"   Next run: {_scheduler.get_job('hourly_refresh').next_run_time}")

    # Run immediately on startup
    import threading
    t = threading.Thread(target=refresh_all_users, daemon=True)
    t.start()
    print("🚀 Initial refresh running in background...")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("🛑 Scheduler stopped")