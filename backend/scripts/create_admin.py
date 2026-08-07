import argparse
import asyncio
import os
import sys
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.future import select

# Add backend to path so imports work when running from command line
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.config import settings
from backend.models.user import User
from backend.utils.security import get_password_hash


async def create_admin(*, reset_password: bool = False) -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        try:
            result = await session.execute(select(User).where(User.username == "admin"))
            existing = result.scalars().first()

            if existing:
                if reset_password:
                    existing.hashed_password = get_password_hash("admin123")
                    existing.role = "admin"
                    await session.commit()
                    print("Reset admin password to: admin123")
                else:
                    print("Admin user already exists. Use --reset-password to set password to admin123.")
                return

            admin = User(
                username="admin",
                email="admin@testlab.local",
                hashed_password=get_password_hash("admin123"),
                role="admin",
            )
            session.add(admin)
            await session.commit()
            print("Admin user created successfully: admin / admin123")
        finally:
            await session.close()
            await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or reset the local admin user.")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="If admin exists, update password to admin123 (does not create duplicates).",
    )
    args = parser.parse_args()
    asyncio.run(create_admin(reset_password=args.reset_password))
