def is_strong_password(password: str):
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    if not any(c.isupper() for c in password):
        return False, "Must include uppercase letter"

    if not any(c.islower() for c in password):
        return False, "Must include lowercase letter"

    if not any(c.isdigit() for c in password):
        return False, "Must include a number"

    if not any(c in "!@#$%^&*" for c in password):
        return False, "Must include a special character"

    return True, "Strong password"