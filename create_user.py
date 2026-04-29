"""Manually create a user account.

Usage:
    python create_user.py <email>           # prompts for password
    python create_user.py <email> <pw>      # password as second arg (avoid in shared shells)
"""

import getpass
import sys

from auth import hash_password
from db import SessionLocal, User, init_db


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    if "@" not in email:
        print("Error: that doesn't look like an email address.")
        sys.exit(1)

    if len(sys.argv) >= 3:
        password = sys.argv[2]
    else:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm:  ")
        if password != confirm:
            print("Error: passwords don't match.")
            sys.exit(1)

    if len(password) < 8:
        print("Error: password must be at least 8 characters.")
        sys.exit(1)

    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"User {email} already exists. Updating password.")
            existing.password_hash = hash_password(password)
        else:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
            print(f"Created user {email}.")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
