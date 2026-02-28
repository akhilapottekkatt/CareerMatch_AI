import os
import smtplib
from email.message import EmailMessage
from typing import List, Dict


def _build_summary_body(
    skills: List[str],
    sent_companies: List[Dict[str, str]],
    job_links: List[str],
) -> str:
    lines: List[str] = []
    lines.append("Hello from CareerMatch AI,\n")

    if skills:
        lines.append("Skills detected from your resume:")
        lines.append(", ".join(skills))
        lines.append("")

    if sent_companies:
        lines.append("Today we sent your resume to the following companies:")
        for c in sent_companies:
            name = c.get("name", "Unknown company")
            url = c.get("apply_url", "")
            status = c.get("status", "sent")
            if url:
                lines.append(f"- {name} ({status}) – {url}")
            else:
                lines.append(f"- {name} ({status})")
        lines.append("")

    if job_links:
        lines.append("You can also explore more jobs using these links:")
        for link in job_links:
            lines.append(f"- {link}")
        lines.append("")

    lines.append("Best regards,\nCareerMatch AI")
    return "\n".join(lines)


def send_summary_email(
    to_email: str,
    skills: List[str],
    sent_companies: List[Dict[str, str]],
    job_links: List[str],
) -> bool:
    """
    Send a summary email to the user listing today's
    companies and job links. Returns True on success,
    False if sending fails.

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

    host = os.getenv("EMAIL_HOST")
    port = int(os.getenv("EMAIL_PORT", "587"))
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    from_email = os.getenv("EMAIL_FROM") or user
    use_tls = os.getenv("EMAIL_USE_TLS", "1").lower() in ("1", "true", "yes")

    if not host or not user or not password or not from_email:
        # SMTP not configured; skip sending gracefully.
        return False

    subject = "Today's applications from CareerMatch AI"
    body = _build_summary_body(skills, sent_companies, job_links)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port) as server:
            if use_tls:
                server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return True
    except Exception as exc:
        # In a real system, you would log this exception.
        print("Error sending summary email:", exc)
        return False

