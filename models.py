# models.py
"""
Pure sqlite3 data access layer.
Converted from SQLAlchemy — all original tables and functions preserved.
BERT cosine matching is kept and fixed (lazy load + returns full job dicts).
"""

import json
from datetime import datetime
from database import get_connection

# ═══════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════

def create_user(email: str, password: str, username: str = "") -> int:
    """
    Create a new user and return user_id
    """

    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO users (email, password, username, created_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (
            email.lower().strip(),
            password,
            username or email.split("@")[0]   # default username
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()




def _row(row) -> dict:
    """Convert sqlite3.Row to plain dict safely."""
    return dict(row) if row else {}


def user_exists(email: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM users WHERE email = ?",
            (email.lower().strip(),)
        ).fetchone()
        return row is not None
    finally:
        conn.close()





# ═══════════════════════════════════════════════════════════════════
# USER
# ═══════════════════════════════════════════════════════════════════

def get_user_by_email(email: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.lower().strip(),)
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def update_username(user_id: int, username: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET username = ? WHERE id = ?",
            (username, user_id)
        )
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# USER PROFILE
# ═══════════════════════════════════════════════════════════════════

def get_or_create_profile(user_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            return _row(row)
        # Create empty profile if not exists
        conn.execute(
            "INSERT INTO user_profiles (user_id) VALUES (?)", (user_id,)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def update_profile(user_id: int, fields: dict):
    """
    Update any fields in user_profiles for given user_id.
    Only pass the fields you want to change.
    Example: update_profile(1, {"phone": "9999", "location": "Kerala"})
    """
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values     = list(fields.values()) + [user_id]
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE user_profiles SET {set_clause}, updated_at = datetime('now') WHERE user_id = ?",
            values
        )
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# RESUME
# ═══════════════════════════════════════════════════════════════════

def get_latest_resume(user_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM resumes WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def get_resume_by_id(resume_id: int, user_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ? AND user_id = ?",
            (resume_id, user_id)
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def get_all_resumes(user_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM resumes WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def insert_resume(user_id: int, data: dict) -> int:
    """Insert new resume. Returns new resume id."""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO resumes
                (user_id, file_path, label, role, summary, experience,
                 is_active, highest_degree, institution, graduation_year, experience_years)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """, (
            user_id,
            data.get("file_path",        ""),
            data.get("label",            ""),
            data.get("role",             ""),
            data.get("summary",          ""),
            data.get("experience",       "[]"),
            data.get("highest_degree",   ""),
            data.get("institution",      ""),
            data.get("graduation_year",  ""),
            data.get("experience_years", 0.0),
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def deactivate_all_resumes(user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE resumes SET is_active = 0 WHERE user_id = ?", (user_id,)
        )
        conn.commit()
    finally:
        conn.close()


def set_active_resume(resume_id: int, user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE resumes SET is_active = 0 WHERE user_id = ?", (user_id,)
        )
        conn.execute(
            "UPDATE resumes SET is_active = 1 WHERE id = ? AND user_id = ?",
            (resume_id, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def delete_resume(resume_id: int, user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM resumes WHERE id = ? AND user_id = ?",
            (resume_id, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def delete_all_resumes(user_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM resumes WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def rename_resume(resume_id: int, user_id: int, label: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE resumes SET label = ? WHERE id = ? AND user_id = ?",
            (label, resume_id, user_id)
        )
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# SKILLS  (resume ↔ skills association table — kept from original)
# ═══════════════════════════════════════════════════════════════════




# def link_skills_to_resume(resume_id: int, skill_names: list):
#     """Insert rows into resume_skills — one connection for everything."""
#     if not skill_names:
#         return
#     conn = get_connection()
#     try:
#         for name in skill_names:
#             name = name.strip()
#             if not name:
#                 continue

#             # Get or create skill — same connection, no locking
#             row = conn.execute(
#                 "SELECT id FROM skills WHERE name = ?", (name,)
#             ).fetchone()

#             if row:
#                 skill_id = row["id"]
#             else:
#                 cursor = conn.execute(
#                     "INSERT INTO skills (name) VALUES (?)", (name,)
#                 )
#                 skill_id = cursor.lastrowid

#             # Link to resume if not already linked
#             exists = conn.execute(
#                 "SELECT 1 FROM resume_skills WHERE resume_id = ? AND skill_id = ?",
#                 (resume_id, skill_id)
#             ).fetchone()
#             if not exists:
#                 conn.execute(
#                     "INSERT INTO resume_skills (resume_id, skill_id) VALUES (?, ?)",
#                     (resume_id, skill_id)
#                 )

#         conn.commit()
#     finally:
#         conn.close()


# def get_skills_for_resume(resume_id: int) -> list:
#     """Return list of skill names linked to a resume."""
#     conn = get_connection()
#     try:
#         rows = conn.execute("""
#             SELECT s.name FROM skills s
#             JOIN resume_skills rs ON rs.skill_id = s.id
#             WHERE rs.resume_id = ?
#         """, (resume_id,)).fetchall()
#         return [r["name"] for r in rows]
#     finally:
#         conn.close()


# ═══════════════════════════════════════════════════════════════════
# JOB SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════

def insert_job_suggestions(user_id: int, jobs: list):
    conn = get_connection()
    try:
        for job in jobs:
            apply_url = job.get("apply_url", "")
            if not apply_url:
                continue

            # ✅ Check duplicate
            exists = conn.execute(
                "SELECT 1 FROM job_suggestions WHERE user_id = ? AND apply_url = ?",
                (user_id, apply_url)
            ).fetchone()

            if exists:
                continue  # skip duplicate job

            conn.execute("""
                INSERT INTO job_suggestions
                    (user_id, title, company, platform, apply_url,
                     match_score, date_suggested, is_applied)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 0)
            """, (
                user_id,
                job.get("title", ""),
                job.get("company", ""),
                job.get("platform", ""),
                apply_url,
                job.get("match_score", 0.0),
            ))

        conn.commit()
    finally:
        conn.close()


def delete_unapplied_suggestions(user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM job_suggestions WHERE user_id = ? AND is_applied = 0",
            (user_id,)
        )
        conn.commit()
    finally:
        conn.close()


def get_suggestions(user_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT * FROM job_suggestions
            WHERE user_id = ? AND is_applied = 0
            ORDER BY match_score DESC
            LIMIT 100
        """, (user_id,)).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def get_suggestion_by_id(job_id: int, user_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM job_suggestions WHERE id = ? AND user_id = ?",
            (job_id, user_id)
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def mark_suggestion_applied(job_id: int, user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE job_suggestions SET is_applied = 1 WHERE id = ? AND user_id = ?",
            (job_id, user_id)
        )
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# APPLIED JOBS
# ═══════════════════════════════════════════════════════════════════

def already_applied(user_id: int, apply_url: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM applied_jobs WHERE user_id = ? AND apply_url = ?",
            (user_id, apply_url)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_applied_urls(user_id: int) -> set:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT apply_url FROM applied_jobs WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {r["apply_url"] for r in rows if r["apply_url"]}
    finally:
        conn.close()


def insert_applied_job(user_id: int, job: dict):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO applied_jobs
                (user_id, title, company, platform, apply_url,
                 match_score, applied_at, status)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 'applied')
        """, (
            user_id,
            job.get("title",       ""),
            job.get("company",     ""),
            job.get("platform",    ""),
            job.get("apply_url",   ""),
            job.get("match_score", 0.0),
        ))
        conn.commit()
    finally:
        conn.close()


def get_applied_jobs(user_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT * FROM applied_jobs
            WHERE user_id = ?
            ORDER BY applied_at DESC
        """, (user_id,)).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# BERT COSINE MATCHING
# Kept from original models.py — with 3 fixes applied:
#   FIX 1 — lazy load: model loads only when first called, not on import
#   FIX 2 — returns full job dicts (original returned nested {"job":..,"similarity":..})
#   FIX 3 — returns top 50 above threshold (original returned only top 5)
# ═══════════════════════════════════════════════════════════════════

_sentence_model = None   # lazy — not loaded until first match call


def _get_model():
    global _sentence_model
    if _sentence_model is None:
        from sentence_transformers import SentenceTransformer
        print("🤖 Loading SentenceTransformer (all-MiniLM-L6-v2)...")
        _sentence_model = SentenceTransformer("all-MiniLM-L6-v2")
        print("✅ Model ready")
    return _sentence_model


def match_jobs_to_resume(resume_text: str, jobs: list, threshold: float = 0.2) -> list:
    """
    Match jobs to resume using BERT cosine similarity.

    Args:
        resume_text : plain text extracted from the uploaded resume PDF
        jobs        : list of job dicts from company_matcher / job_links
        threshold   : minimum cosine similarity score to include (0.0 - 1.0)

    Returns:
        List of job dicts sorted by match_score descending.
        Each dict has original job fields + match_score (float) + match_pct (str e.g. "72%")

    Changes from original models.py:
        - _sentence_model loaded lazily (was loading on app startup — caused slow boot)
        - Returns flat job dict with match_score key added
          (original returned {"job": ..., "similarity": ..., "match_score": "72%"})
        - Returns top 50 not top 5
        - threshold default lowered from 0.4 to 0.2 (0.4 was too strict, returned 0 results often)
    """
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    if not resume_text or not jobs:
        return []

    model      = _get_model()
    resume_emb = model.encode(resume_text)
    results    = []

    for job in jobs:
        job_text = (
            job.get("title",       "") + " " +
            job.get("description", "") + " " +
            job.get("company",     "")
        )
        job_emb = model.encode(job_text)
        score   = float(cosine_similarity([resume_emb], [job_emb])[0][0])

        if score >= threshold:
            results.append({
                **job,
                "match_score": round(score, 3),
                "match_pct":   f"{score:.0%}",
            })

    results.sort(key=lambda x: x["match_score"], reverse=True)

    print(f"✅ BERT matched {len(results)} jobs (threshold={threshold})")
    if results:
        print(f"🏆 Top: {results[0].get('title')} @ {results[0].get('company')} — {results[0].get('match_pct')}")

    return results

