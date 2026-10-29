import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

engine = None
AsyncSessionLocal = None

if DATABASE_URL:
    if not DATABASE_URL.startswith("postgresql+asyncpg://"):
        raise ValueError(
            "DATABASE_URL must begin with postgresql+asyncpg://"
        )

    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )

    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db():
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    async with AsyncSessionLocal() as session:
        yield session