import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import db, lifespan, db_connection_middleware
from routes.discover import router as discover_router
from routes.enrichment import router as enrichment_router
from routes.entities import router as entities_router
from routes.merge import router as merge_router

_DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]

_extra = os.environ.get("ALLOWED_ORIGINS", "")
CORS_ORIGINS = _DEFAULT_ORIGINS + [o.strip() for o in _extra.split(",") if o.strip()]

app = FastAPI(title="State Political Tracker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(db_connection_middleware)

app.include_router(merge_router)
app.include_router(enrichment_router)
app.include_router(entities_router)
app.include_router(discover_router)


@app.get("/health")
async def health():
    conn = await db()
    async with conn.cursor() as cur:
        await cur.execute("SELECT 1")
    return {"ok": True}
