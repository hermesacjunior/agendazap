from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agendazap.db")

# Convert postgres:// to postgresql+asyncpg:// for async support
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Supabase session pooler (port 5432): asyncpg keeps a dedicated backend per
# connection, so prepared statements are safe (the transaction pooler on 6543
# multiplexes backends and breaks asyncpg's named prepared statements).
# pool_pre_ping revalidates connections that went stale while the Lambda was frozen.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    from app.models import user, schedule, booking, plan, push  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all nao altera tabelas existentes; garante colunas novas no
        # Postgres (Supabase) de forma idempotente. No SQLite local a coluna ja
        # vem do create_all, entao nao roda o ALTER.
        if engine.dialect.name == "postgresql":
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "email_notifications boolean NOT NULL DEFAULT true"
            ))
            await conn.execute(text(
                "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS share_token varchar(64)"
            ))
            for ddl in (
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_digest_enabled boolean NOT NULL DEFAULT false",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_digest_hour integer NOT NULL DEFAULT 7",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_digest_email boolean NOT NULL DEFAULT true",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_digest_whatsapp boolean NOT NULL DEFAULT false",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_digest_last_sent varchar(10)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_enabled boolean NOT NULL DEFAULT false",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_hours integer NOT NULL DEFAULT 24",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_email boolean NOT NULL DEFAULT true",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_whatsapp boolean NOT NULL DEFAULT false",
                "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_sent boolean NOT NULL DEFAULT false",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar text",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked boolean NOT NULL DEFAULT false",
            ):
                await conn.execute(text(ddl))
