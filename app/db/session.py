from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import settings

# Remove pgbouncer parameter as asyncpg doesn't support it
db_url = settings.DATABASE_URL
if "?pgbouncer=" in db_url:
    db_url = db_url.split("?pgbouncer=")[0]
elif "&pgbouncer=" in db_url:
    db_url = db_url.split("&pgbouncer=")[0]

# Create engine with statement_cache_size=0 for pgbouncer compatibility
# This prevents "prepared statement already exists" errors when using pgbouncer
engine = create_async_engine(
    db_url, 
    echo=False,
    connect_args={"statement_cache_size": 0}
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

