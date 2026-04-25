import html
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Tuple
from dotenv import load_dotenv

load_dotenv()


def _smtp_settings() -> Tuple[str, int, str, str, str, bool]:
    """
    Load SMTP settings.
    Supports both preferred EMAIL_* keys and legacy aliases used in existing .env files.
    """
    host = os.getenv("EMAIL_HOST") or os.getenv("SMTP_server")
    port = int(os.getenv("EMAIL_PORT") or os.getenv("PORT") or "587")
    user = os.getenv("EMAIL_USER") or os.getenv("LOGIN")
    password = os.getenv("EMAIL_PASSWORD") or os.getenv("PASSWORD")
    from_email = os.getenv("EMAIL_FROM") or user
    use_tls = (os.getenv("EMAIL_USE_TLS") or "1").lower() in ("1", "true", "yes")
    return host, port, user, password, from_email, use_tls


def _build_html_and_text(username: str, jobs: List[Dict[str, str]]) -> Tuple[str, str]:
    now = datetime.now().strftime("%d %b %Y %H:%M")
    app_base_url = (os.getenv("APP_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    safe_user = html.escape(username or "there")
    top_jobs = jobs[:5]

    job_rows = ""
    for i, job in enumerate(top_jobs, 1):
        score = job.get("match_score", 0) or 0
        try:
            score_num = float(score)
        except (TypeError, ValueError):
            score_num = 0.0
        score_pct = (
            f"{round(score_num * 100)}%" if score_num <= 1 else f"{int(score_num)}%"
        )

        platform = html.escape(str(job.get("platform", "Job Board")))
        title = html.escape(str(job.get("title", "Role not specified")))
        company = html.escape(str(job.get("company", "Unknown company")))
        apply_url = html.escape(str(job.get("apply_url", "")))

        if score_num >= 0.6:
            color, label = "#10B981", "Strong Match"
        elif score_num >= 0.3:
            color, label = "#F59E0B", "Good Match"
        else:
            color, label = "#6366F1", "Partial Match"

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
            Your daily top 5 job recommendations
          </div>
        </div>

        <div style="
            background:#16213E;
            border:1px solid rgba(124,58,237,0.2);
            border-top:none;
            border-radius:0 0 16px 16px;
            padding:28px 32px;
        ">
          <p style="color:#94a3b8;font-size:14px;margin:0 0 8px;">
            Hi <strong style="color:#f1f5f9;">{safe_user}</strong>,
          </p>
          <p style="color:#94a3b8;font-size:14px;margin:0 0 24px;">
            Here are your top {len(top_jobs)} recommendations for <strong style="color:#f1f5f9;">{now}</strong>.
          </p>

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

          <div style="text-align:center;margin-top:28px;">
            <a href="{app_base_url}/suggestions" style="
                display:inline-block;
                padding:12px 32px;
                background:linear-gradient(135deg,#2563EB,#7C3AED);
                color:#fff;
                border-radius:10px;
                text-decoration:none;
                font-weight:700;
                font-size:14px;
            ">View All Suggestions →</a>
          </div>

          <p style="
              color:#475569;
              font-size:11px;
              text-align:center;
              margin-top:24px;
              border-top:1px solid #1e293b;
              padding-top:16px;
          ">
            This is an automated daily digest from CareerMatch AI.
          </p>
        </div>
      </div>
    </body>
    </html>
    """

    plain_lines = [
        f"Hi {username or 'there'},",
        "",
        f"Your daily recommendations are ready ({now}).",
        "",
    ]
    for i, job in enumerate(top_jobs, 1):
        score = job.get("match_score", 0) or 0
        try:
            score_num = float(score)
        except (TypeError, ValueError):
            score_num = 0.0
        score_pct = (
            f"{round(score_num * 100)}%" if score_num <= 1 else f"{int(score_num)}%"
        )
        plain_lines.append(
            f"{i}. {job.get('title','')} at {job.get('company','')} "
            f"({job.get('platform','')}) — {score_pct}"
        )
        if job.get("apply_url"):
            plain_lines.append(f"   Apply: {job.get('apply_url')}")
        plain_lines.append("")
    plain_lines.append(f"View all: {app_base_url}/suggestions")
    plain_text = "\n".join(plain_lines)
    return html_body, plain_text


def send_best_jobs_email(
    to_email: str,
    best_companies: List[Dict[str, str]],
    username: str = "there",
) -> bool:
    """
    Send an email with the best matching jobs (companies/roles).
    Returns True on success, False if sending fails.

    SMTP configuration is read from environment variables:
    - EMAIL_HOST
    - EMAIL_PORT
    - EMAIL_USER
    - EMAIL_PASSWORD
    - EMAIL_FROM (fallbacks to EMAIL_USER)
    - EMAIL_USE_TLS ("1" / "true" to enable TLS)
    """
    if not to_email:
        return False

    host, port, user, password, from_email, use_tls = _smtp_settings()

    if not host or not user or not password or not from_email:
        print(
            "Error sending best jobs email: missing SMTP config "
            "(EMAIL_HOST/EMAIL_USER/EMAIL_PASSWORD/EMAIL_FROM or legacy aliases)"
        )
        return False

    html_body, plain_text = _build_html_and_text(username=username, jobs=best_companies)

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "CareerMatch AI — Your daily top 5 jobs"
        msg["From"] = from_email
        msg["To"] = to_email
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        if use_tls:
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port) as server:
                server.login(user, password)
                server.send_message(msg)
        return True
    except Exception as exc:
        # In a real system, you would log this exception.
        print("Error sending best jobs email:", exc)
        return False


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """Send a single-use password reset link. Returns True on success."""
    if not to_email or not reset_url:
        return False

    host, port, user, password, from_email, use_tls = _smtp_settings()

    if not host or not user or not password or not from_email:
        print(
            "Error sending password reset: missing SMTP config "
            "(EMAIL_HOST/EMAIL_USER/EMAIL_PASSWORD/EMAIL_FROM or legacy aliases)"
        )
        return False

    safe_url = html.escape(reset_url, quote=True)
    plain = (
        "You requested a password reset for CareerMatch AI.\n\n"
        f"Open this link to choose a new password (valid for 1 hour):\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:24px;background:#f4f5fc;font-family:system-ui,-apple-system,sans-serif;">
  <div style="max-width:520px;margin:0 auto;background:#fff;border:1px solid #e6e8f3;border-radius:16px;padding:28px;">
    <h1 style="margin:0 0 12px;font-size:1.25rem;color:#161d2f;">Reset your password</h1>
    <p style="margin:0 0 20px;color:#5f6780;font-size:0.95rem;line-height:1.5;">
      Click the button below to set a new password. This link expires in one hour.
    </p>
    <p style="margin:0 0 20px;">
      <a href="{safe_url}" style="display:inline-block;background:linear-gradient(135deg,#1f4fee,#2345cc);color:#fff;
        padding:12px 22px;border-radius:999px;text-decoration:none;font-weight:700;font-size:0.9rem;">
        Reset password
      </a>
    </p>
    <p style="margin:0;color:#69728a;font-size:0.8rem;word-break:break-all;">
      If the button does not work, paste this URL into your browser:<br>{safe_url}
    </p>
  </div>
</body>
</html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "CareerMatch AI — Reset your password"
        msg["From"] = from_email
        msg["To"] = to_email
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        if use_tls:
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port) as server:
                server.login(user, password)
                server.send_message(msg)
        return True
    except Exception as exc:
        print("Error sending password reset email:", exc)
        return False
