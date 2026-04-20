from passlib.context import CryptContext
from app.database import get_connection
from sqlite3 import IntegrityError

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
