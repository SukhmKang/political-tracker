import json

from fastapi import APIRouter, HTTPException

from db import db
from enrich import enrich_entity as run_enrichment
from models import EntityEnrichment, EnrichmentSource, NewsItem

router = APIRouter()

_ENRICHMENT_SELECT = """
    SELECT id, entity_id, enriched_at,
           entity_type, description, occupation, employer,
           political_party, office_held, mission, founded_year, jurisdiction,
           recent_news, sources
    FROM unified.entity_enrichments
"""


def _row_to_enrichment(r: tuple) -> EntityEnrichment:
    return EntityEnrichment(
        id=r[0],
        entity_id=r[1],
        enriched_at=r[2].isoformat() if r[2] else "",
        entity_type=r[3],
        description=r[4],
        occupation=r[5],
        employer=r[6],
        political_party=r[7],
        office_held=r[8],
        mission=r[9],
        founded_year=r[10],
        jurisdiction=r[11],
        recent_news=[NewsItem(**item) for item in (r[12] or [])],
        sources=[EnrichmentSource(**item) for item in (r[13] or [])],
    )


async def _enrichment_hints(conn, entity_id: int) -> dict:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                CASE
                    WHEN seed_entity_id = %s THEN target_name
                    ELSE seed_entity_name
                END AS connected_name
            FROM unified.inferred_edges
            WHERE seed_entity_id = %s OR target_entity_id = %s
            ORDER BY created_at DESC
            LIMIT 12
            """,
            (entity_id, entity_id, entity_id),
        )
        connected_names = []
        for (name,) in await cur.fetchall():
            if name and name not in connected_names:
                connected_names.append(name)

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT DISTINCT unnest(COALESCE(source_domains, '{}')) AS domain
            FROM unified.inferred_edges
            WHERE seed_entity_id = %s OR target_entity_id = %s
            LIMIT 12
            """,
            (entity_id, entity_id),
        )
        source_domains = []
        for (domain,) in await cur.fetchall():
            if domain and domain not in source_domains:
                source_domains.append(domain)

    return {
        "connected_entities": connected_names[:3],
        "source_domains": source_domains[:3],
    }


@router.post("/entities/{entity_id}/enrich", response_model=EntityEnrichment)
async def enrich_entity(entity_id: int):
    conn = await db()

    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT canonical_name, entity_type, state FROM unified.entities WHERE id = %s",
            (entity_id,),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

    entity_name, entity_type, state = row
    hints = await _enrichment_hints(conn, entity_id)

    try:
        result = await run_enrichment(entity_name, entity_type or "organization", state, hints)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {exc}") from exc

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO unified.entity_enrichments
                (entity_id, entity_type, description, occupation, employer,
                 political_party, office_held, mission, founded_year, jurisdiction,
                 recent_news, sources, raw_output)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, entity_id, enriched_at,
                      entity_type, description, occupation, employer,
                      political_party, office_held, mission, founded_year, jurisdiction,
                      recent_news, sources
            """,
            (
                entity_id, entity_type,
                result.get("description"), result.get("occupation"), result.get("employer"),
                result.get("political_party"), result.get("office_held"), result.get("mission"),
                result.get("founded_year"), result.get("jurisdiction"),
                json.dumps(result.get("recent_news", [])),
                json.dumps(result.get("sources", [])),
                json.dumps(result),
            ),
        )
        saved = await cur.fetchone()

    return _row_to_enrichment(saved)


@router.get("/entities/{entity_id}/enrichment", response_model=EntityEnrichment)
async def get_enrichment(entity_id: int):
    conn = await db()

    async with conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM unified.entities WHERE id = %s", (entity_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

    async with conn.cursor() as cur:
        await cur.execute(
            _ENRICHMENT_SELECT + "WHERE entity_id = %s ORDER BY enriched_at DESC LIMIT 1",
            (entity_id,),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"No enrichment found for entity {entity_id}")

    return _row_to_enrichment(row)


@router.delete("/entities/{entity_id}/enrichment", status_code=200)
async def delete_enrichment(entity_id: int):
    conn = await db()
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM unified.entity_enrichments WHERE entity_id = %s", (entity_id,)
        )
        deleted = cur.rowcount
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"No enrichment found for entity {entity_id}")
    return {"deleted": deleted}
