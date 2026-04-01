from passlib.context import CryptContext
from database import get_connection
from sqlite3 import IntegrityError

from utils import is_strong_password

# auth.py
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain, hashed):
    try:
        return pwd_context.verify(plain, hashed)
    except:
        return False






def create_user(username, email, password):

    valid, message = is_strong_password(password)

    if not valid:
        return False, message   # send error to frontend

    hashed_password = hash_password(password)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (username,email,password) VALUES (?,?,?)",
            (username, email, hashed_password)
        )
        conn.commit()
        return True, "User created successfully"

    except IntegrityError:
        return False, "Email already exists"

    finally:
        conn.close()

def authenticate_user(email, password):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT email,password FROM users WHERE email=?",
        (email,)
    )

    user = cursor.fetchone()
    conn.close()

    if not user:
        return None

    stored_email, stored_password = user

    if verify_password(password, stored_password):
        return stored_email

    return None