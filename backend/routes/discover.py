import asyncio
import re
import sys
import traceback
import uuid
from typing import Optional

import psycopg
from fastapi import APIRouter, HTTPException

from agent import main as run_agent
from db import db, gemini, get_agent_inferred_run_id
from models import DiscoverRequest, DiscoverResponse, InferredEdge

router = APIRouter()

_INFERRED_SELECT = """
    SELECT id, seed_entity_id, seed_entity_name,
           target_name, target_entity_id, target_type, relationship_type,
           COALESCE(evidence_quotes, '{}'),
           COALESCE(source_urls, '{}'),
           COALESCE(source_domains, '{}'),
           evidence_strength,
           COALESCE(found_by, '{}'),
           COALESCE(depth, 1),
           found_from,
           verified,
           created_at
    FROM unified.inferred_edges
"""

_INFERRED_ORDER = """
    ORDER BY
        CASE evidence_strength
            WHEN 'direct'   THEN 1
            WHEN 'indirect' THEN 2
            WHEN 'weak'     THEN 3
            ELSE 4
        END,
        created_at DESC
"""


def _build_inferred_edge(r: tuple) -> InferredEdge:
    return InferredEdge(
        id=r[0],
        seed_entity_id=r[1],
        seed_entity_name=r[2],
        target_name=r[3],
        target_entity_id=r[4],
        target_type=r[5],
        relationship_type=r[6],
        evidence_quotes=list(r[7] or []),
        source_urls=list(r[8] or []),
        source_domains=list(r[9] or []),
        evidence_strength=r[10],
        found_by=list(r[11] or []),
        depth=int(r[12] or 1),
        found_from=r[13],
        verified=r[14],
        created_at=r[15].isoformat() if r[15] else "",
    )


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
    try:
        response = gemini.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    except Exception as exc:
        print(
            f"  [!] Entity resolution LLM failed for {name!r} ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return None
    answer = (response.text or "").strip().lower()
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
) -> tuple[Optional[int], bool]:
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
        print(f"[!] /discover agent failed for {req.entity_name!r}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}") from exc

    connections = output.get("connections", [])

    resolution_tasks: dict[tuple[str, Optional[str]], asyncio.Task[tuple[Optional[int], bool]]] = {}

    async def resolve_cached(name: str, entity_type: Optional[str] = None) -> tuple[Optional[int], bool]:
        key = (name.lower().strip(), entity_type)
        if key not in resolution_tasks:
            resolution_tasks[key] = asyncio.create_task(_resolve_entity(conn, name, entity_type))
        return await resolution_tasks[key]

    target_resolutions = await asyncio.gather(*[
        resolve_cached(c.get("target_name", ""), c.get("target_type"))
        for c in connections
    ])
    source_names = [
        (c.get("found_from") or req.entity_name).strip() or req.entity_name
        for c in connections
    ]
    source_resolutions = await asyncio.gather(*[
        resolve_cached(source_name)
        for source_name in source_names
    ])

    verified_count = sum(1 for _, was_existing in target_resolutions if was_existing)
    inferred_count = len(target_resolutions) - verified_count

    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO unified.inferred_edges (
                seed_entity_id, seed_entity_name, target_name, target_entity_id,
                target_type, relationship_type, evidence_quotes, source_urls,
                source_domains, evidence_strength, found_by, depth, found_from,
                verified, run_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    source_entity_id or seed_entity_id,
                    source_name,
                    c.get("target_name", ""),
                    target_entity_id,
                    c.get("target_type"),
                    c.get("relationship_type"),
                    c.get("evidence_quotes", []),
                    c.get("source_urls", []),
                    c.get("source_domains", []),
                    c.get("evidence_strength"),
                    c.get("found_by", []),
                    c.get("depth", 1),
                    c.get("found_from"),
                    was_existing,
                    run_id,
                )
                for c, source_name, (source_entity_id, _), (target_entity_id, was_existing)
                in zip(connections, source_names, source_resolutions, target_resolutions)
            ],
        )
        await cur.execute(_INFERRED_SELECT + "WHERE run_id = %s" + _INFERRED_ORDER, (run_id,))
        inferred_edges = [_build_inferred_edge(r) for r in await cur.fetchall()]

    return DiscoverResponse(
        run_id=run_id,
        seed_entity_id=seed_entity_id,
        seed_entity_name=req.entity_name,
        connections_found=len(connections),
        verified_count=verified_count,
        inferred_count=inferred_count,
        inferred_edges=inferred_edges,
    )
