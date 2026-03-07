import os
import smtplib
from email.message import EmailMessage
from typing import List, Dict


def _build_best_jobs_body(best_companies: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    lines.append("Hello from CareerMatch AI,\n")

    if best_companies:
        lines.append("Here are today's best matching roles for your resume:")
        lines.append("")
        for c in best_companies:
            name = c.get("name", "Unknown company")
            role = c.get("role", "Role not specified")
            url = c.get("apply_url", "")
            score = c.get("match_score")

            score_str = f" (match: {score}%)" if isinstance(score, int) else ""
            if url:
                lines.append(f"- {role} at {name}{score_str} – {url}")
            else:
                lines.append(f"- {role} at {name}{score_str}")
        lines.append("")
    else:
        lines.append("We could not find strong matches for your resume today.")
        lines.append("You may want to update your skills or try a different resume.")
        lines.append("")

    lines.append("Best regards,\nCareerMatch AI")
    return "\n".join(lines)


def send_best_jobs_email(
    to_email: str,
    best_companies: List[Dict[str, str]],
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

    host = os.getenv("EMAIL_HOST")
    port = int(os.getenv("EMAIL_PORT", "587"))
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    from_email = os.getenv("EMAIL_FROM") or user
    use_tls = os.getenv("EMAIL_USE_TLS", "1").lower() in ("1", "true", "yes")

    if not host or not user or not password or not from_email:
        # SMTP not configured; skip sending gracefully.
        return False

    subject = "Today's best matching jobs from CareerMatch AI"
    body = _build_best_jobs_body(best_companies)

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
        print("Error sending best jobs email:", exc)
        return False

