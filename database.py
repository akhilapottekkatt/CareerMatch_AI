# database.py

import os
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Generator

# ---------- Config ----------
DB_NAME = "users.db"
DATABASE_URL = f"sqlite:///{DB_NAME}"

# ---------- SQLAlchemy setup ----------
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

# ---------- Raw sqlite connection (optional legacy support) ----------
def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_NAME)

# ---------- FastAPI DB dependency ----------
def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Create tables ----------
def create_users_table():
    """
    Creates all SQLAlchemy tables and ensures users table exists.
    """

    # Create SQLAlchemy tables from models
    Base.metadata.create_all(bind=engine)

    # Legacy users table compatibility
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT UNIQUE,
            password TEXT
        )
    """)

    conn.commit()
    conn.close()