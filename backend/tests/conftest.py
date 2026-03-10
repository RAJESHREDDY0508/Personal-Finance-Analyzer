"""
Pytest configuration and shared fixtures.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app as fastapi_app
from app.database import Base, get_db
import app.models  # noqa: F401 — must import all models so SQLAlchemy registers relationships

# ── Test DB (SQLite in-memory for speed) ─────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


# Function-scoped: fresh in-memory DB per test so committed data never leaks
@pytest.fixture
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    AsyncTestSession = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with AsyncTestSession() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        """
        Mirrors production get_db: commit after each successful request so that
        multi-request tests (e.g. refresh-token rotation) see committed state.
        """
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    fastapi_app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()
