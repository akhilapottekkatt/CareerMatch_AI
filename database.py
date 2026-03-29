# database.py
"""
Pure sqlite3 database setup.
No SQLAlchemy — creates all tables that models.py uses.
"""

import sqlite3

DB_NAME = "users.db"


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
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    NOT NULL,
            email    TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL
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

            created_at       TEXT DEFAULT (datetime('now'))
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

    conn.commit()
    conn.close()
    print("✅ All tables ready (sqlite3)")