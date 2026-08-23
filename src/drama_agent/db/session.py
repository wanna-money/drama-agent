from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from drama_agent.config import settings
from drama_agent.db.models import Base
import asyncio

engine = create_async_engine(settings.database_url, echo=settings.db_echo)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
