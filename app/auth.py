import hashlib
import secrets

from passlib.context import CryptContext
from sqlite3 import IntegrityError

from app.database import get_connection

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)


def create_user(name, email, password):

    conn = get_connection()
    cursor = conn.cursor()

    hashed_password = hash_password(password)

    try:
        cursor.execute(
            "INSERT INTO users (name,email,password) VALUES (?,?,?)",
            (name, email, hashed_password),
        )

        conn.commit()
        return True
    except IntegrityError:
        return False

    finally:
        conn.close()


def authenticate_user(email, password):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT email,password FROM users WHERE email=?", (email,))

    user = cursor.fetchone()
    conn.close()

    if not user:
        return None

    stored_email, stored_password = user

    if verify_password(password, stored_password):
        return stored_email

    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def delete_pending_reset_tokens_for_user(user_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM password_reset_tokens WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def create_password_reset_token(
    email: str,
) -> tuple[str | None, int | None, str | None]:
    """
    Create a one-time reset token for the user.
    Returns (plain_token, user_id, delivery_email) if the account exists, else three Nones.
    """
    email_n = email.strip().lower()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, email FROM users WHERE lower(trim(email)) = ?",
            (email_n,),
        ).fetchone()
        if not row:
            return None, None, None
        user_id = int(row["id"])
        delivery_email = (row["email"] or "").strip()
        token = secrets.token_urlsafe(32)
        th = _token_hash(token)
        conn.execute(
            "DELETE FROM password_reset_tokens WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        )
        conn.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
            VALUES (?, ?, datetime('now', '+1 hour'))
            """,
            (user_id, th),
        )
        conn.commit()
        return token, user_id, delivery_email
    finally:
        conn.close()


def validate_password_reset_token(token: str) -> dict | None:
    """Return {"token_row_id": int, "user_id": int} if token is valid and unused."""
    if not token or len(token) < 16:
        return None
    th = _token_hash(token)
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, user_id FROM password_reset_tokens
            WHERE token_hash = ? AND used_at IS NULL
              AND datetime(expires_at) > datetime('now')
            """,
            (th,),
        ).fetchone()
        if not row:
            return None
        return {"token_row_id": int(row["id"]), "user_id": int(row["user_id"])}
    finally:
        conn.close()


def reset_password_with_token(token: str, new_password: str) -> bool:
    info = validate_password_reset_token(token)
    if not info:
        return False
    conn = get_connection()
    try:
        hashed = hash_password(new_password)
        conn.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (hashed, info["user_id"]),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used_at = datetime('now') WHERE id = ?",
            (info["token_row_id"],),
        )
        conn.commit()
        return True
    finally:
        conn.close()
