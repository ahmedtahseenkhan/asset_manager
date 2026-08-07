"""
Dev-only seed script. Run explicitly from the CLI — never called automatically on startup.

Usage:
    python -m backend.dev_seed
"""
import asyncio
import logging
from sqlalchemy.future import select

from backend.config import settings
from backend.database import async_session
from backend.models.user import User
from backend.utils.security import get_password_hash

logger = logging.getLogger(__name__)


async def seed_admin(username: str = "admin", password: str = "admin123") -> None:
    """Create a default admin user if one does not exist. DEBUG mode only."""
    if not settings.debug:
        raise RuntimeError("seed_admin must only be called with DEBUG=true")

    async with async_session() as session:
        result = await session.execute(select(User).where(User.username == username))
        if result.scalars().first():
            print(f"User '{username}' already exists — skipping.")
            return

        session.add(
            User(
                username=username,
                email=f"{username}@testlab.local",
                hashed_password=get_password_hash(password),
                role="admin",
            )
        )
        await session.commit()
        print(f"Created dev admin: username={username} password={password}")


if __name__ == "__main__":
    asyncio.run(seed_admin())
