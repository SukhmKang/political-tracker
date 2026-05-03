import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Optional

import psycopg
from dotenv import load_dotenv
from google import genai
from psycopg_pool import AsyncConnectionPool

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

_branch = os.environ.get("NEON_BRANCH", "").upper()
DB_URL = os.environ[f"DB_URL_{_branch}"] if _branch else os.environ["DB_URL"]
DB_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "10"))

gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

_pool: Optional[AsyncConnectionPool] = None
_request_conn: ContextVar[Optional[psycopg.AsyncConnection]] = ContextVar("_request_conn", default=None)
_agent_inferred_run_id: Optional[int] = None


@asynccontextmanager
async def lifespan(app):
    global _pool, _agent_inferred_run_id
    _pool = AsyncConnectionPool(
        DB_URL,
        min_size=DB_POOL_MIN_SIZE,
        max_size=DB_POOL_MAX_SIZE,
        kwargs={"autocommit": True},
        open=False,
    )
    await _pool.open()
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO unified.entity_resolution_runs (name, description)
                VALUES ('agent_inferred', 'Entities created by the discovery agent')
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
            )
            row = await cur.fetchone()
            _agent_inferred_run_id = row[0]
    yield
    if _pool:
        await _pool.close()


async def db_connection_middleware(request, call_next):
    if _pool is None:
        raise RuntimeError("DB not connected")
    async with _pool.connection() as conn:
        token = _request_conn.set(conn)
        try:
            return await call_next(request)
        finally:
            _request_conn.reset(token)


async def db() -> psycopg.AsyncConnection:
    conn = _request_conn.get()
    if conn is None:
        raise RuntimeError("DB connection unavailable outside request context")
    return conn


def get_agent_inferred_run_id() -> Optional[int]:
    return _agent_inferred_run_id
