# database.py
"""
Pure sqlite3 database setup.
No SQLAlchemy — creates all tables that models.py uses.
"""

import os
import sqlite3

DB_NAME = "users.db"


def sync_admins_from_env():
    """
    Promote users listed in ADMIN_EMAILS or ADMIN_EMAIL (comma-separated) to is_admin=1.
    Set in the environment before starting the app (e.g. ADMIN_EMAILS=you@corp.com).
    """
    raw = os.getenv("ADMIN_EMAILS") or os.getenv("ADMIN_EMAIL") or ""
    emails = [e.strip().lower() for e in raw.split(",") if e.strip()]
    if not emails:
        return
    conn = get_connection()
    try:
        for em in emails:
            conn.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (em,))
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────
# Connection
# ─────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """
    Open and return a sqlite3 connection.
    row_factory = sqlite3.Row lets you access columns by name:
        row["email"]  instead of  row[0]
    Always call conn.close() when done — use try/finally in callers.
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────
# Create all tables
# ─────────────────────────────────────────

def create_users_table():
    """
    Creates every table the app needs.
    Safe to call on every startup — uses IF NOT EXISTS.
    Matches all tables used in models.py exactly.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""

        -- ── Users ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT NOT NULL,
            email      TEXT UNIQUE NOT NULL,
            password   TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            is_admin   INTEGER DEFAULT 0
        );

        -- ── User Profiles ───────────────────────────────────────
        CREATE TABLE IF NOT EXISTS user_profiles (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id            INTEGER UNIQUE NOT NULL REFERENCES users(id),

            -- Basic info
            phone              TEXT,
            location           TEXT,
            profile_pic        TEXT,

            -- Skills stored as JSON list e.g. '["Python","React"]'
            skills             TEXT,

            -- Experience
            experience_years   REAL    DEFAULT 0.0,

            -- Job preferences
            expected_roles     TEXT,           -- JSON list
            preferred_location TEXT,           -- Remote / Onsite / Hybrid / Any
            salary_range       TEXT,           -- e.g. "5-10 LPA"
            job_type           TEXT,           -- Full-time / Part-time / Internship

            -- Qualifications
            highest_degree     TEXT,
            institution        TEXT,
            graduation_year    TEXT,

            -- Active resume for matching
            active_resume_id   INTEGER,

            updated_at         TEXT DEFAULT (datetime('now'))
        );

        -- ── Resumes ─────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS resumes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER NOT NULL REFERENCES users(id),
            file_path        TEXT,

            label            TEXT,           -- user-given name e.g. "Data Engineer CV"
            role             TEXT,
            experience       TEXT,           -- JSON list of skills
            summary          TEXT,
            is_active        INTEGER DEFAULT 0,   -- 1 = active, 0 = inactive

            -- Auto-extracted qualification fields
            highest_degree   TEXT,
            institution      TEXT,
            graduation_year  TEXT,
            experience_years REAL    DEFAULT 0.0,

            created_at         TEXT DEFAULT (datetime('now')),
            profile_confirmed  INTEGER DEFAULT 0   -- 0 = user must confirm parsed data before matching
        );

        

      

        -- ── Job Suggestions ─────────────────────────────────────
        CREATE TABLE IF NOT EXISTS job_suggestions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(id),
            title          TEXT,
            company        TEXT,
            platform       TEXT,
            apply_url      TEXT,
            match_score    REAL    DEFAULT 0.0,
            date_suggested TEXT    DEFAULT (datetime('now')),
            is_applied     INTEGER DEFAULT 0    -- 0 = not applied, 1 = applied
        );

        -- ── Applied Jobs ────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS applied_jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            title       TEXT,
            company     TEXT,
            platform    TEXT,
            apply_url   TEXT,
            match_score REAL    DEFAULT 0.0,
            applied_at  TEXT    DEFAULT (datetime('now')),
            status      TEXT    DEFAULT 'applied'  -- applied/interview/offer/rejected
        );

    """)

    # Existing DBs may predate created_at on users — add column if missing.
    rows = conn.execute("PRAGMA table_info(users)").fetchall()
    column_names = [r[1] for r in rows]
    if column_names and "created_at" not in column_names:
        # SQLite ALTER cannot use datetime('now') as a column default; backfill after add.
        conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        conn.execute(
            "UPDATE users SET created_at = datetime('now') WHERE created_at IS NULL"
        )

    resume_rows = conn.execute("PRAGMA table_info(resumes)").fetchall()
    resume_cols = [r[1] for r in resume_rows]
    if resume_cols and "profile_confirmed" not in resume_cols:
        conn.execute("ALTER TABLE resumes ADD COLUMN profile_confirmed INTEGER DEFAULT 0")
        conn.execute("UPDATE resumes SET profile_confirmed = 1")

    user_rows = conn.execute("PRAGMA table_info(users)").fetchall()
    user_cols = [r[1] for r in user_rows]
    if user_cols and "is_admin" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")

    conn.commit()
    conn.close()
    print("✅ All tables ready (sqlite3)")