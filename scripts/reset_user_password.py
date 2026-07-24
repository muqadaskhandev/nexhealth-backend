"""One-off: reset a user's password hash.

  DATABASE_URL=... DB_SSL=true DB_SSL_VERIFY=false \\
    python -m scripts.reset_user_password EMAIL NEW_PASSWORD
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.database import SessionLocal
from app.models.user import User


async def main(email: str, new_password: str) -> None:
    email = email.strip().lower()
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            print(f"User not found: {email}")
            sys.exit(1)
        user.password_hash = hash_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        await db.commit()
        print(f"Password updated for {email}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.reset_user_password EMAIL NEW_PASSWORD")
        sys.exit(2)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
