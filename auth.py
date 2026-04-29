from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from db import User, get_db


def _truncate(password: str) -> bytes:
    # bcrypt has a 72-byte hard limit; truncating is the standard way to handle it.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(password), hashed.encode("utf-8"))
    except Exception:
        return False


def get_session_user(request: Request, db: Session) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        return None
    return user


def require_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user = get_session_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user
