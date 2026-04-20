# models.py
"""
Pure sqlite3 data access layer.
Converted from SQLAlchemy — all original tables and functions preserved.
BERT cosine matching is kept and fixed (lazy load + returns full job dicts).
"""

import glob
import json
import os
from datetime import datetime
from app.database import get_connection

# ═══════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════


def create_user(email: str, password: str, name: str = "") -> int:
    """
    Create a new user and return user_id
    """
    from app.auth import hash_password

    conn = get_connection()
    try:
        final_name = name or email.split("@")[0]
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]

        # Backward compatibility: older DBs still have NOT NULL users.username.
        if "username" in cols:
            cursor = conn.execute(
                """
                INSERT INTO users (email, password, name, username, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """,
                (
                    email.lower().strip(),
                    hash_password(password),
                    final_name,
                    final_name,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO users (email, password, name, created_at)
                VALUES (?, ?, ?, datetime('now'))
            """,
                (
                    email.lower().strip(),
                    hash_password(password),
                    final_name,
                ),
            )
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
            "SELECT 1 FROM users WHERE email = ?", (email.lower().strip(),)
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
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row(row)
    finally:
        conn.close()


def list_users_admin() -> list:
    """All users without password — for admin UI."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, name, email, created_at, IFNULL(is_admin, 0) AS is_admin
               FROM users ORDER BY id ASC"""
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def set_user_admin(user_id: int, is_admin: int) -> bool:
    """Set is_admin to 0 or 1. Returns True if a row was updated."""
    conn = get_connection()
    try:
        n = conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (1 if is_admin else 0, user_id),
        ).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def admin_delete_user_cascade(target_user_id: int) -> None:
    """
    Remove user and all related rows. Caller must ensure actor is not deleting self.
    Deletes resume files and parsed JSON caches for this user when present.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT file_path FROM resumes WHERE user_id = ?", (target_user_id,)
        ).fetchall()
        for r in rows:
            fp = r["file_path"]
            if fp and os.path.isfile(fp):
                try:
                    os.remove(fp)
                except OSError:
                    pass

        conn.execute("DELETE FROM applied_jobs WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM job_suggestions WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM resumes WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (target_user_id,))
        conn.commit()
    finally:
        conn.close()

    for path in glob.glob(f"parsed_resumes_{target_user_id}_*.json"):
        try:
            os.remove(path)
        except OSError:
            pass
    legacy = f"parsed_resumes_{target_user_id}.json"
    if os.path.isfile(legacy):
        try:
            os.remove(legacy)
        except OSError:
            pass
    for path in glob.glob(f"static/profile_pics/user_{target_user_id}.*"):
        try:
            os.remove(path)
        except OSError:
            pass


def admin_stats() -> dict:
    conn = get_connection()
    try:
        n_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        n_suggestions = conn.execute(
            "SELECT COUNT(*) AS c FROM job_suggestions"
        ).fetchone()["c"]
        n_applied = conn.execute("SELECT COUNT(*) AS c FROM applied_jobs").fetchone()[
            "c"
        ]
        n_resumes = conn.execute("SELECT COUNT(*) AS c FROM resumes").fetchone()["c"]
        return {
            "users": n_users,
            "job_suggestions": n_suggestions,
            "applied_jobs": n_applied,
            "resumes": n_resumes,
        }
    finally:
        conn.close()


def admin_list_job_suggestions(
    limit: int = 50,
    offset: int = 0,
    user_id: int | None = None,
) -> list:
    conn = get_connection()
    try:
        if user_id is not None:
            rows = conn.execute(
                """
                SELECT js.*, u.email AS user_email, u.name AS user_name
                FROM job_suggestions js
                JOIN users u ON u.id = js.user_id
                WHERE js.user_id = ?
                ORDER BY js.date_suggested DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT js.*, u.email AS user_email, u.name AS user_name
                FROM job_suggestions js
                JOIN users u ON u.id = js.user_id
                ORDER BY js.date_suggested DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def admin_count_job_suggestions(user_id: int | None = None) -> int:
    conn = get_connection()
    try:
        if user_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM job_suggestions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM job_suggestions").fetchone()
        return int(row["c"])
    finally:
        conn.close()


def admin_delete_job_suggestion(suggestion_id: int) -> bool:
    conn = get_connection()
    try:
        n = conn.execute(
            "DELETE FROM job_suggestions WHERE id = ?", (suggestion_id,)
        ).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def update_username(user_id: int, username: str):
    # Backward-compatible wrapper used by existing callers.
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (username, user_id))
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
        conn.execute("INSERT INTO user_profiles (user_id) VALUES (?)", (user_id,))
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
    values = list(fields.values()) + [user_id]
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE user_profiles SET {set_clause}, updated_at = datetime('now') WHERE user_id = ?",
            values,
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
            (user_id,),
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def get_pending_resume(user_id: int) -> dict:
    """Latest resume waiting for user confirmation (profile_confirmed = 0)."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM resumes WHERE user_id = ? AND IFNULL(profile_confirmed, 0) = 0
               ORDER BY id DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def update_resume_record(resume_id: int, user_id: int, fields: dict) -> bool:
    """Update resume columns; only allowed keys. Returns True if a row was updated."""
    allowed = {
        "label",
        "role",
        "summary",
        "experience",
        "highest_degree",
        "institution",
        "graduation_year",
        "experience_years",
        "profile_confirmed",
        "is_active",
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return False
    conn = get_connection()
    try:
        n = conn.execute(
            f"UPDATE resumes SET {', '.join(f'{k} = ?' for k in safe)} WHERE id = ? AND user_id = ?",
            list(safe.values()) + [resume_id, user_id],
        ).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def get_resume_by_id(resume_id: int, user_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id)
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def get_all_resumes(user_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM resumes WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def insert_resume(user_id: int, data: dict) -> int:
    """Insert new resume. Returns new resume id."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO resumes
                (user_id, file_path, label, role, summary, experience,
                 is_active, highest_degree, institution, graduation_year, experience_years,
                 profile_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """,
            (
                user_id,
                data.get("file_path", ""),
                data.get("label", ""),
                data.get("role", ""),
                data.get("summary", ""),
                data.get("experience", "[]"),
                data.get("highest_degree", ""),
                data.get("institution", ""),
                data.get("graduation_year", ""),
                data.get("experience_years", 0.0),
                int(data.get("profile_confirmed", 0)),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def deactivate_all_resumes(user_id: int):
    conn = get_connection()
    try:
        conn.execute("UPDATE resumes SET is_active = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def set_active_resume(resume_id: int, user_id: int):
    conn = get_connection()
    try:
        conn.execute("UPDATE resumes SET is_active = 0 WHERE user_id = ?", (user_id,))
        conn.execute(
            "UPDATE resumes SET is_active = 1 WHERE id = ? AND user_id = ?",
            (resume_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_resume(resume_id: int, user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id)
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
            (label, resume_id, user_id),
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
# GLOBAL JOBS CATALOG (scheduler fetch step)
# ═══════════════════════════════════════════════════════════════════


def replace_jobs_catalog(jobs: list) -> int:
    """
    Replace the entire ``jobs`` table with a fresh fetch (one global pool per run).
    Returns number of rows inserted.
    """
    conn = get_connection()
    try:
        conn.execute("DELETE FROM jobs")
        inserted = 0
        for job in jobs:
            apply_url = (job.get("apply_url") or "").strip()
            if not apply_url:
                continue
            conn.execute(
                """
                INSERT INTO jobs (
                    title, company, platform, apply_url, location,
                    description, salary, job_type, posted, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    job.get("title", "") or "",
                    job.get("company", "") or "",
                    job.get("platform", "") or "",
                    apply_url,
                    job.get("location", "") or "",
                    job.get("description", "") or "",
                    job.get("salary", "") or "",
                    job.get("job_type", "") or "",
                    job.get("posted", "") or "",
                ),
            )
            inserted += 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def list_jobs_catalog_for_matching() -> list:
    """
    Load all rows from ``jobs`` in the shape expected by ``match_jobs_batch_users``.
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT title, company, platform, apply_url, location,
                   description, salary, job_type, posted
            FROM jobs
            """).fetchall()
        out: list = []
        for r in rows:
            d = dict(r)
            d["match_score"] = 0.0
            out.append(d)
        return out
    finally:
        conn.close()


def count_jobs_catalog() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()
        return int(row["c"]) if row else 0
    finally:
        conn.close()


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
                (user_id, apply_url),
            ).fetchone()

            if exists:
                continue  # skip duplicate job

            conn.execute(
                """
                INSERT INTO job_suggestions
                    (user_id, title, company, platform, apply_url,
                     match_score, date_suggested, is_applied)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 0)
            """,
                (
                    user_id,
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("platform", ""),
                    apply_url,
                    job.get("match_score", 0.0),
                ),
            )

        conn.commit()
    finally:
        conn.close()


def delete_unapplied_suggestions(user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM job_suggestions WHERE user_id = ? AND is_applied = 0",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def get_suggestions(user_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM job_suggestions
            WHERE user_id = ? AND is_applied = 0
            ORDER BY match_score DESC
            LIMIT 100
        """,
            (user_id,),
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def get_all_suggestions(user_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM job_suggestions
            WHERE user_id = ?
            ORDER BY date_suggested DESC, match_score DESC
            LIMIT 300
        """,
            (user_id,),
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def get_suggestion_by_id(job_id: int, user_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM job_suggestions WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
        return _row(row)
    finally:
        conn.close()


def mark_suggestion_applied(job_id: int, user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE job_suggestions SET is_applied = 1 WHERE id = ? AND user_id = ?",
            (job_id, user_id),
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
            (user_id, apply_url),
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
        conn.execute(
            """
            INSERT INTO applied_jobs
                (user_id, title, company, platform, apply_url,
                 match_score, applied_at, status)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 'applied')
        """,
            (
                user_id,
                job.get("title", ""),
                job.get("company", ""),
                job.get("platform", ""),
                job.get("apply_url", ""),
                job.get("match_score", 0.0),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_applied_jobs(user_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM applied_jobs
            WHERE user_id = ?
            ORDER BY applied_at DESC
        """,
            (user_id,),
        ).fetchall()
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

_sentence_model = None  # lazy — not loaded until first match call


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

    model = _get_model()
    resume_emb = model.encode(resume_text)
    results = []

    for job in jobs:
        job_text = (
            job.get("title", "")
            + " "
            + job.get("description", "")
            + " "
            + job.get("company", "")
        )
        job_emb = model.encode(job_text)
        score = float(cosine_similarity([resume_emb], [job_emb])[0][0])

        if score >= threshold:
            results.append(
                {
                    **job,
                    "match_score": round(score, 3),
                    "match_pct": f"{score:.0%}",
                }
            )

    results.sort(key=lambda x: x["match_score"], reverse=True)

    print(f"✅ BERT matched {len(results)} jobs (threshold={threshold})")
    if results:
        print(
            f"🏆 Top: {results[0].get('title')} @ {results[0].get('company')} — {results[0].get('match_pct')}"
        )

    return results


def match_jobs_batch_users(
    resume_by_user: dict[int, str],
    jobs: list,
    threshold: float = 0.2,
    top_k: int = 50,
) -> dict[int, list]:
    """
    Score **every job** in ``jobs`` against **every user** resume in one batched embedding pass:
    - Job texts encoded once.
    - User resume texts encoded in batch.
    - Cosine similarity matrix (users × jobs), then per-user top_k above threshold.

    Returns ``{ user_id: [ job dicts with match_score, apply_url, ... ] }``.
    """
    from sklearn.metrics.pairwise import cosine_similarity

    out: dict[int, list] = {uid: [] for uid in resume_by_user}

    if not jobs or not resume_by_user:
        return out

    user_ids = [uid for uid, text in resume_by_user.items() if (text or "").strip()]
    if not user_ids:
        return out

    model = _get_model()

    job_texts = [
        (
            (j.get("title", "") or "")
            + " "
            + (j.get("description", "") or "")
            + " "
            + (j.get("company", "") or "")
        ).strip()
        for j in jobs
    ]
    job_embs = model.encode(job_texts)

    resume_texts = [resume_by_user[uid] for uid in user_ids]
    resume_embs = model.encode(resume_texts)

    sims = cosine_similarity(resume_embs, job_embs)

    for i, uid in enumerate(user_ids):
        row = sims[i]
        picked: list = []
        for j, score in enumerate(row):
            if float(score) >= threshold:
                picked.append(
                    {
                        **jobs[j],
                        "match_score": round(float(score), 3),
                        "match_pct": f"{float(score):.0%}",
                    }
                )
        picked.sort(key=lambda x: x["match_score"], reverse=True)
        out[uid] = picked[:top_k]

    print(
        f"✅ Batch BERT: {len(user_ids)} user(s) × {len(jobs)} jobs "
        f"(threshold={threshold}, top_k={top_k} per user)"
    )
    return out
