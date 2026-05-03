import asyncio
import re
import uuid
from typing import Optional

import psycopg
from fastapi import APIRouter, HTTPException

from agent import main as run_agent
from db import db, gemini, get_agent_inferred_run_id
from models import DiscoverRequest, DiscoverResponse

router = APIRouter()


async def _fuzzy_match_entity(conn: psycopg.AsyncConnection, name: str, threshold: float = 0.4) -> Optional[int]:
    if not name:
        return None
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id FROM unified.entities
            WHERE normalized_name ILIKE '%%' || lower(%s) || '%%'
               OR word_similarity(lower(%s), normalized_name) > %s
            ORDER BY word_similarity(lower(%s), normalized_name) DESC, mention_count DESC
            LIMIT 1
            """,
            (name, name, threshold, name),
        )
        row = await cur.fetchone()
    return row[0] if row else None


def _llm_pick_entity(name: str, candidates: list[tuple]) -> Optional[int]:
    if not candidates:
        return None
    candidate_lines = "\n".join(
        f'{i + 1}. "{r[1]}" (id: {r[0]}, type: {r[2] or "unknown"}, state: {r[3] or "unknown"})'
        for i, r in enumerate(candidates)
    )
    prompt = (
        "You are matching a newly discovered entity name against candidates from a "
        "political campaign finance database.\n\n"
        f'New entity: "{name}"\n\n'
        f"Candidates:\n{candidate_lines}\n\n"
        "Does any candidate refer to the same real-world entity as the new entity? "
        "Reply with ONLY the number of the best match (1, 2, 3 …) or the word 'none'."
    )
    response = gemini.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
    answer = response.text.strip().lower()
    if "none" in answer:
        return None
    m = re.search(r"\d+", answer)
    if m:
        idx = int(m.group()) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx][0]
    return None


async def _resolve_entity(
    conn: psycopg.AsyncConnection,
    name: str,
    entity_type: Optional[str] = None,
) -> tuple[int, bool]:
    if not name:
        return None, False

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, canonical_name, entity_type, state
            FROM unified.entities
            WHERE normalized_name ILIKE '%%' || lower(%s) || '%%'
               OR word_similarity(lower(%s), normalized_name) > 0.3
            ORDER BY word_similarity(lower(%s), normalized_name) DESC, mention_count DESC
            LIMIT 5
            """,
            (name, name, name),
        )
        candidates = await cur.fetchall()

    loop = asyncio.get_event_loop()
    matched_id = await loop.run_in_executor(None, _llm_pick_entity, name, list(candidates))
    if matched_id is not None:
        return matched_id, True

    normalized = name.lower().strip()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO unified.entities
                (run_id, cluster_key, entity_type, canonical_name, normalized_name, mention_count)
            VALUES (%s, %s, %s, %s, %s, 0)
            RETURNING id
            """,
            (get_agent_inferred_run_id(), normalized, entity_type or "organization", name, normalized),
        )
        row = await cur.fetchone()
    return row[0], False


@router.post("/discover", response_model=DiscoverResponse)
async def discover(req: DiscoverRequest):
    conn = await db()
    seed_entity_id = await _fuzzy_match_entity(conn, req.entity_name)
    run_id = str(uuid.uuid4())

    try:
        output = await run_agent(req.entity_name, req.depth, req.max_expand)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}") from exc

    connections = output.get("connections", [])
    verified_count = 0
    inferred_count = 0

    for connection_data in connections:
        target_name = connection_data.get("target_name", "")
        target_entity_id, was_existing = await _resolve_entity(
            conn, target_name, connection_data.get("target_type")
        )
        if was_existing:
            verified_count += 1
        else:
            inferred_count += 1

        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO unified.inferred_edges (
                    seed_entity_id, seed_entity_name, target_name, target_entity_id,
                    target_type, relationship_type, evidence_quotes, source_urls,
                    source_domains, evidence_strength, found_by, depth, found_from,
                    verified, run_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    seed_entity_id,
                    req.entity_name,
                    target_name,
                    target_entity_id,
                    connection_data.get("target_type"),
                    connection_data.get("relationship_type"),
                    connection_data.get("evidence_quotes", []),
                    connection_data.get("source_urls", []),
                    connection_data.get("source_domains", []),
                    connection_data.get("evidence_strength"),
                    connection_data.get("found_by", []),
                    connection_data.get("depth", 1),
                    connection_data.get("found_from"),
                    was_existing,
                    run_id,
                ),
            )

    return DiscoverResponse(
        run_id=run_id,
        seed_entity_id=seed_entity_id,
        seed_entity_name=req.entity_name,
        connections_found=len(connections),
        verified_count=verified_count,
        inferred_count=inferred_count,
    )
