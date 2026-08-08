"""
Create or reset the initial admin user.

    python -m backend.scripts.create_admin [--username NAME] [--email ADDR] [--reset-password]

The password is prompted interactively (or taken from the ADMIN_PASSWORD env
var for unattended installs). Nothing is ever defaulted to a known value.
"""
import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.future import select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.config import settings
from backend.models.user import User
from backend.utils.security import get_password_hash

MIN_LEN = 8


def _get_password() -> str:
    pw = os.environ.get("ADMIN_PASSWORD")
    if pw:
        source = "ADMIN_PASSWORD env var"
    else:
        pw = getpass.getpass("New admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if pw != confirm:
            sys.exit("Passwords do not match.")
        source = "prompt"
    if len(pw) < MIN_LEN:
        sys.exit(f"Password must be at least {MIN_LEN} characters (from {source}).")
    return pw


async def create_admin(username: str, email: str, reset_password: bool) -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        try:
            result = await session.execute(select(User).where(User.username == username))
            existing = result.scalars().first()

            if existing:
                if not reset_password:
                    print(f"User '{username}' already exists. "
                          "Use --reset-password to set a new password.")
                    return
                existing.hashed_password = get_password_hash(_get_password())
                existing.role = "admin"
                existing.is_active = True
                await session.commit()
                print(f"Password updated for admin '{username}'.")
                return

            session.add(User(
                username=username,
                email=email,
                hashed_password=get_password_hash(_get_password()),
                role="admin",
            ))
            await session.commit()
            print(f"Admin user '{username}' created.")
        finally:
            await session.close()
            await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or reset the initial admin user.")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--email", default=None,
                        help="Defaults to <username>@localhost")
    parser.add_argument("--reset-password", action="store_true",
                        help="Update the password if the user already exists.")
    args = parser.parse_args()
    asyncio.run(create_admin(
        username=args.username,
        email=args.email or f"{args.username}@localhost",
        reset_password=args.reset_password,
    ))
